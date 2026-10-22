import runpy
import unittest
import json
from pathlib import Path
m=runpy.run_path(__file__.replace('test-bg-renewables.py','refresh-bg-renewables.py'))
class InventoryTests(unittest.TestCase):
 def test_embedded_inventory(self):
  rows,skipped=m['embedded']()
  self.assertGreater(len(rows),90)
  self.assertTrue(any(f['properties']['status']=='planned' for f in rows))
  self.assertTrue(all(f['properties']['mw']>1 for f in rows))
  self.assertTrue(any(f['geometry'] is None for f in rows))
  self.assertTrue(skipped)
 def test_merge_first_record_and_null_geometry(self):
  a=m['feature']({'id':'A','source':'https://example.org/a','name':'A','mw':2})
  b=m['feature']({'id':'B','source':'https://example.org/a','name':'A','mw':2},{'type':'Point','coordinates':[25,42]})
  merged=m['merge']([a,b]);self.assertEqual(len(merged),1);self.assertIsNotNone(merged[0]['geometry'])
 def test_confirmed_hydro_identity(self):
  a=m['feature']({'id':'VEIREG-pavets-belmeken','source':'https://www.veiregistar.bg/object/pavets-belmeken','name':'ПАВЕЦ Белмекен','mw':375,'sourceMode':'veiregistar'})
  b=m['feature']({'id':'OSM-BG-W288644875','source':'https://www.openstreetmap.org/way/288644875','name':'ПАВЕЦ Белмекен','mw':375,'sourceMode':'osm','geometryQuality':'location-only'},{'type':'Point','coordinates':[23.8580822,42.199602]})
  merged=m['merge']([b,a]);self.assertEqual(len(merged),1);p=merged[0]['properties'];self.assertEqual(p['id'],'VEIREG-pavets-belmeken');self.assertEqual(len(p['sources']),2);self.assertEqual(p['sourceModes'],['osm','veiregistar']);self.assertIsNotNone(merged[0]['geometry']);self.assertNotIn('possibleDuplicateIds',p)
  again=m['merge'](merged+[b,a]);self.assertEqual(again,merged)
 def test_shared_document_is_not_shared_identity(self):
  a=m['feature']({'id':'one','name':'One','mw':2,'source':'https://example.org/register.pdf'})
  b=m['feature']({'id':'two','name':'Two','mw':2,'source':'https://example.org/register.pdf'})
  self.assertEqual(len(m['merge']([a,b])),2)
 def test_parcel_point_respects_holes(self):
  locator=runpy.run_path(__file__.replace('test-bg-renewables.py','enrich-bg-renewable-locations.py'))
  outer=[[0,0],[10,0],[10,10],[0,10],[0,0]];hole=[[4,4],[6,4],[6,6],[4,6],[4,4]]
  x,y=locator['interior_point']([outer,hole]);self.assertTrue(0<x<10 and 0<y<10);self.assertFalse(4<x<6 and 4<y<6)
 def test_degenerate_parcel_has_no_fabricated_point(self):
  locator=runpy.run_path(__file__.replace('test-bg-renewables.py','enrich-bg-renewable-locations.py'))
  with self.assertRaises(ValueError):locator['interior_point']([[[1,1],[2,1],[1,1]]])
 def test_registry_pagination_and_threshold(self):
  old=m['registry_category'].__globals__['get'];seen=[]
  def fake(url):
   seen.append(url)
   return '<a href="https://www.veiregistar.bg/objects&type=test&page=2">2</a><a href="https://www.veiregistar.bg/object/'+('a' if 'page=2' not in url else 'b')+'"><h3>Тест</h3>В експоатация от 2012 с мощност <strong>'+('1' if 'page=2' not in url else '2.5')+' МВт</strong></a>'
  m['registry_category'].__globals__['get']=fake
  try:
   rows=m['registry_category'](('test','hydro'));self.assertEqual(len(seen),2);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['properties']['mw'],2.5);self.assertIsNone(rows[0]['geometry'])
  finally:m['registry_category'].__globals__['get']=old
 def test_kazanlak_official_parcels_survive_refresh(self):
  source=json.loads(m['KAZANLAK_PARCELS'].read_text())
  cache=json.loads((Path(__file__).resolve().parents[1]/'map/data/bg-renewables-cache-v1.geojson').read_text())
  feature=next(f for f in cache['features'] if f['id']=='OSM-BG-R16941504')
  self.assertEqual(feature['geometry']['type'],'MultiPolygon')
  self.assertEqual(len(feature['geometry']['coordinates']),15)
  self.assertEqual(feature['properties']['geometryQuality'],'cadastral-parcels')
  self.assertEqual(feature['properties']['geometryRefs'],sorted(f['properties']['nationalcadastralref'] for f in source['features']))
  point=dict(feature,geometry={'type':'Point','coordinates':[25.2350311,42.6759614]},properties=dict(feature['properties'],geometryQuality='location-only'))
  refreshed=m['apply_kazanlak_official_parcels']([point])[0]
  self.assertEqual(refreshed['geometry'],feature['geometry'])
if __name__=='__main__':unittest.main()
