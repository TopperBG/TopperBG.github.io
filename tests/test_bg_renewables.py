"""National renewable inventory regression coverage.
No settlement-centre coordinates are accepted as a solar installation location.
"""
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('bg_cache',Path(__file__).parents[1]/'scripts/refresh-bg-renewables.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class InventoryTest(unittest.TestCase):
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
