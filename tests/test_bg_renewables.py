"""National renewable inventory regression coverage.
No settlement-centre coordinates are accepted as a solar installation location.
"""
import importlib.util
import io
import json
import unittest
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('bg_cache',Path(__file__).parents[1]/'scripts/refresh-bg-renewables.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class InventoryTest(unittest.TestCase):
 def test_hydro_registry_and_osm_do_not_reappear_as_separate_rows(self):
  root=Path(__file__).parents[1]
  identities=json.loads((root/'map/data/bg-renewables-identities-v1.json').read_text())['entities']
  cache=json.loads((root/'map/data/bg-renewables-cache-v1.geojson').read_text())['features']
  by_id={f['id']:f for f in cache}
  for entity in identities:
   canonical=by_id[entity['canonicalId']]
   if canonical['properties']['technology'] not in ('hydro','pumped_hydro'):continue
   with self.subTest(plant=entity['canonicalId']):
    self.assertIsNotNone(canonical['geometry'])
    self.assertNotIn('possibleDuplicateIds',canonical['properties'])
    self.assertTrue(set(entity['memberIds'])<=set(canonical['properties']['mergedIds']))
    rows=[]
    for member in entity['memberIds']:
     is_osm=member.startswith('OSM-')
     source=next(u for u in canonical['properties']['sources'] if ('openstreetmap.org' in u)==is_osm)
     rows.append(m.feature({'id':member,'name':canonical['properties']['name'],'mw':canonical['properties']['mw']+(1 if is_osm else 0),'technology':canonical['properties']['technology'],'status':'operating','sourceMode':'osm' if is_osm else 'veiregistar:hydro','source':source,'retrievedAt':'2026-11-02T00:00:00+00:00'},canonical['geometry'] if is_osm else None))
    merged=m.merge(list(reversed(rows)))
    self.assertEqual(len(merged),1)
    self.assertEqual(merged[0]['id'],entity['canonicalId'])
    self.assertEqual(merged[0]['geometry'],canonical['geometry'])
    self.assertEqual(merged[0]['properties']['mw'],canonical['properties']['mw'])
    self.assertEqual(merged[0]['properties']['geometrySourceMode'],'osm')
    self.assertEqual(len(merged[0]['properties']['capacityObservations']),2)
    self.assertEqual(m.merge(merged+rows),merged)
 def test_similar_hydro_names_and_unverified_names_are_not_merged(self):
  rows=[m.feature({'id':'unverified-'+str(i),'name':name,'mw':7,'technology':'hydro','source':f'https://example.org/plant/{i}'}) for i,name in enumerate(['ВЕЦ Въча 1','ВЕЦ Въча 2','ВЕЦ Еднакво име','ВЕЦ Еднакво име'])]
  self.assertEqual(len(m.merge(rows)),4)
 def test_identity_members_are_unique(self):
  identities=json.loads((Path(__file__).parents[1]/'map/data/bg-renewables-identities-v1.json').read_text())['entities']
  members=[member for entity in identities for member in entity['memberIds']]
  self.assertEqual(len(members),len(set(members)))
  for entity in identities:self.assertIn(entity['canonicalId'],entity['memberIds'])
 def test_hydro_refresh_with_stale_osm_retains_one_located_plant(self):
  registry=m.feature({'id':'VEIREG-vets-batak','name':'ВЕЦ Батак','mw':46,'technology':'hydro','status':'operating','source':'https://www.veiregistar.bg/object/vets-batak','sourceMode':'veiregistar:test','retrievedAt':'2026-11-02T00:00:00+00:00'})
  osm=m.feature({'id':'OSM-BG-W299988326','name':'ВЕЦ Батак','mw':46.8,'technology':'hydro','status':'operating','source':'https://www.openstreetmap.org/way/299988326','sourceMode':'osm','retrievedAt':'2026-11-02T00:00:00+00:00'},{'type':'Point','coordinates':[24.1931129,41.9189174]})
  with tempfile.TemporaryDirectory() as directory:
   out=Path(directory)/'cache.json';health=Path(directory)/'health.json'
   out.write_text(json.dumps({'features':m.merge([registry,osm])}))
   with patch.multiple(m,OUT=out,HEALTH=health,TECHS={'test':'hydro'}),patch.object(m,'embedded',return_value=([],[])),patch.object(m,'registry_category',side_effect=lambda _:json.loads(json.dumps([registry]))),patch.object(m,'apply_kazanlak_official_parcels',side_effect=lambda rows:rows),patch.object(sys,'argv',['refresh']),patch('sys.stdout',new_callable=io.StringIO):
    for _ in range(2):
     with patch.object(m,'osm',side_effect=TimeoutError('timeout')):m.main()
     rows=json.loads(out.read_text())['features'];self.assertEqual(len(rows),1)
     self.assertEqual(rows[0]['geometry'],osm['geometry'])
     self.assertEqual(rows[0]['properties']['mw'],46)
     self.assertEqual(rows[0]['properties']['sourceFreshness']['osm']['status'],'stale')
    with patch.object(m,'osm',return_value=[osm]):m.main()
    rows=json.loads(out.read_text())['features'];self.assertEqual(len(rows),1)
    self.assertEqual(rows[0]['geometry'],osm['geometry'])
    self.assertEqual(rows[0]['properties']['sourceFreshness']['osm']['status'],'ok')
 def test_timeout_repeated_failure_and_recovery(self):
  old=m.feature({'id':'test-osm','name':'Test','mw':10,'status':'operating','source':'https://www.openstreetmap.org/way/999999999999','sourceMode':'osm','sourceModes':['osm'],'retrievedAt':'2026-11-02T10:00:00+00:00'}, {'type':'Point','coordinates':[25,42]})
  with tempfile.TemporaryDirectory() as directory:
   out=Path(directory)/'cache.json';health=Path(directory)/'health.json'
   out.write_text(json.dumps({'features':[old]}))
   with patch.multiple(m,OUT=out,HEALTH=health,TECHS={}),patch.object(m,'embedded',side_effect=lambda:([],[])),patch.object(m,'apply_kazanlak_official_parcels',side_effect=lambda rows:rows),patch.object(sys,'argv',['refresh']),patch('sys.stdout',new_callable=io.StringIO):
    for _ in range(2):
     with patch.object(m,'osm',side_effect=TimeoutError('timeout')):m.main()
     h=json.loads(health.read_text());f=json.loads(out.read_text())['features'][0]
     self.assertEqual(h['sources']['osm']['status'],'stale')
     self.assertEqual(h['sources']['osm']['retained'],1)
     self.assertEqual(h['sources']['osm']['lastSuccessAt'],old['properties']['retrievedAt'])
     self.assertEqual(f['geometry'],old['geometry']);self.assertEqual(f['properties']['status'],'operating')
     self.assertEqual(f['properties']['retrievedAt'],old['properties']['retrievedAt'])
     self.assertEqual(f['properties']['sourceFreshness']['osm']['status'],'stale')
    # Rebuilding geometry must preserve the last remote attempt and success.
    before=h['sources']
    with patch.object(sys,'argv',['refresh','--reconcile-only']):m.main()
    self.assertEqual(json.loads(health.read_text())['sources'],before)
    with patch.object(m,'osm',return_value=[old]):m.main()
    h=json.loads(health.read_text());f=json.loads(out.read_text())['features'][0]
    self.assertEqual(h['sources']['osm']['status'],'ok')
    self.assertEqual(h['sources']['osm']['lastSuccessAt'],h['sources']['osm']['lastAttemptAt'])
    self.assertEqual(f['properties']['retrievedAt'],h['sources']['osm']['lastSuccessAt'])
    self.assertEqual(f['properties']['sourceFreshness']['osm']['status'],'ok')
 def test_merged_status_and_geometry_have_separate_sources(self):
  fresh=m.feature({'id':'fresh','name':'Test','mw':10,'status':'operating','source':'https://example.org/test','secondarySource':'https://www.openstreetmap.org/way/999999999999','sourceMode':'veiregistar:test','retrievedAt':'2026-11-03T10:00:00+00:00'})
  old=m.feature({'id':'old','name':'Test','mw':10,'status':'planned','source':'https://www.openstreetmap.org/way/999999999999','sourceMode':'osm','retrievedAt':'2026-11-02T10:00:00+00:00'}, {'type':'Point','coordinates':[25,42]})
  rows=m.merge([fresh,old]);self.assertEqual(len(rows),1)
  p=rows[0]['properties'];self.assertEqual(p['statusSourceMode'],'veiregistar:test');self.assertEqual(p['geometrySourceMode'],'osm')
  h={'sources':{'osm':{'status':'stale','lastSuccessAt':old['properties']['retrievedAt']},'veiregistar:test':{'status':'ok','lastSuccessAt':fresh['properties']['retrievedAt']}}}
  m.apply_freshness(rows,h)
  self.assertEqual(p['sourceFreshness']['osm']['lastSuccessAt'],old['properties']['retrievedAt'])
  self.assertEqual(p['status'],'operating')
 def test_curated_threshold_and_missing_geometry(self):
  rows,_=m.embedded()
  self.assertTrue(rows)
  self.assertTrue(all(f['properties']['mw']>1 for f in rows))
  self.assertTrue(any(f['geometry'] is None for f in rows))
  self.assertTrue(any(f['properties']['status']=='planned' for f in rows))
 def test_osm_lifecycle_and_units(self):
  payload={'elements':[
   {'type':'way','id':1,'center':{'lon':25,'lat':42},'tags':{'plant:source':'solar','plant:output:electricity':'2000 kW','construction:power':'plant'}},
   {'type':'way','id':2,'tags':{'plant:source':'wind','plant:output:electricity':'1 MW','power':'plant'}},
   {'type':'way','id':3,'tags':{'plant:source':'solar','plant:output:electricity':'2000','power':'plant'}}]}
  with patch('urllib.request.urlopen',side_effect=lambda *a,**k:io.BytesIO(json.dumps(payload).encode())):
   rows=m.osm()
  self.assertEqual(len(rows),1)
  self.assertEqual(rows[0]['properties']['mw'],2)
  self.assertEqual(rows[0]['properties']['status'],'construction')
 def test_registry_pagination_and_historical_operating_status(self):
  def fake(url):
   slug='second' if '&page=2' in url else 'first'
   return f'<a class="card" href="https://www.veiregistar.bg/object/{slug}"><h3>ФЕЦ Test {slug}</h3>В експоатация от 1 януари 2019, с производствена мощност <strong>2.5 МВт</strong></a><a href="https://www.veiregistar.bg/objects&type=test&page=2">2</a>'
  with patch.object(m,'get',side_effect=fake):
   rows=m.registry_category(('test','solar'))
  self.assertEqual(len(rows),2)
  self.assertTrue(all(f['properties']['status']=='operating' for f in rows))
  self.assertTrue(all(f['geometry'] is None for f in rows))
 def test_registry_shrink_protection(self):
  mode='veiregistar:test'
  previous=[{'properties':{'sourceMode':mode}} for _ in range(20)]
  with self.assertRaisesRegex(ValueError,'shrink protection'):
   m.validate_source_batch(mode,[{}]*15,previous)
  m.validate_source_batch(mode,[{}]*16,previous)
  with self.assertRaisesRegex(ValueError,'Empty'):
   m.validate_source_batch(mode,[],previous)

if __name__=='__main__':unittest.main()
