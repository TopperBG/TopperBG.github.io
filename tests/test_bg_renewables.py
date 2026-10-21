import importlib.util
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('bg_cache',Path(__file__).parents[1]/'scripts/refresh-bg-renewables.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class InventoryTest(unittest.TestCase):
 def test_curated_threshold_and_missing_geometry(self):
  rows=m.curated()
  self.assertTrue(rows)
  self.assertTrue(all(f['properties']['mw']>1 for f in rows))
  self.assertTrue(any(f['geometry'] is None for f in rows))
  self.assertTrue(any(f['properties']['status']=='planned' for f in rows))
 def test_osm_lifecycle_and_units(self):
  import json
  original=m.fetch
  m.fetch=lambda url:json.dumps({'elements':[{'type':'way','id':1,'center':{'lon':25,'lat':42},'tags':{'plant:source':'solar','plant:output:electricity':'2000 kW','power':'construction'}},{'type':'way','id':2,'tags':{'plant:source':'wind','plant:output:electricity':'1 MW','power':'plant'}}]})
  try:
   rows=m.osm_inventory()
   self.assertEqual(len(rows),1)
   self.assertEqual(rows[0]['properties']['mw'],2)
   self.assertEqual(rows[0]['properties']['status'],'construction')
  finally:m.fetch=original
 def test_registry_pagination_and_historical_operating_status(self):
  original=m.fetch
  categories=''.join(f'<a href="https://www.veiregistar.bg/objects&type=test-power-over-{i}-mw">type</a>' for i in range(6))
  def fake(url):
   if url==m.BASE+'objects':return categories
   if '/object/' in url:return '<div class="objects"><h3>ФЕЦ Test</h3><p>с местоположение София, общ. София, в експоатация от 1 януари 2019, с производствена мощност <strong>2.5 МВт</strong></p></div>'
   slug='second' if '&page=2' in url else 'first'
   return f'<a class="card" href="https://www.veiregistar.bg/object/{slug}">Test</a><a href="{url}&page=2">2</a>'
  m.fetch=fake
  try:
   rows=m.registry()
   self.assertEqual(len(rows),2)
   self.assertTrue(all(f['properties']['status']=='operating' for f in rows))
   self.assertTrue(all(f['properties']['locationQuality']=='settlement-approximate' for f in rows))
  finally:m.fetch=original
if __name__=='__main__':unittest.main()
