import runpy
import unittest
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
  a=m['feature']({'id':'A','source':'https://example.org/a','name':'A'})
  b=m['feature']({'id':'B','source':'https://example.org/a','name':'A'},{'type':'Point','coordinates':[25,42]})
  merged=m['merge']([a,b]);self.assertEqual(len(merged),1);self.assertIsNotNone(merged[0]['geometry'])
 def test_registry_pagination_and_threshold(self):
  old=m['registry_category'].__globals__['get'];seen=[]
  def fake(url):
   seen.append(url)
   return '<a href="https://www.veiregistar.bg/objects&type=test&page=2">2</a><a href="https://www.veiregistar.bg/object/'+('a' if 'page=2' not in url else 'b')+'"><h3>Тест</h3>В експоатация от 2012 с мощност <strong>'+('1' if 'page=2' not in url else '2.5')+' МВт</strong></a>'
  m['registry_category'].__globals__['get']=fake
  try:
   rows=m['registry_category'](('test','hydro'));self.assertEqual(len(seen),2);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['properties']['mw'],2.5);self.assertIsNone(rows[0]['geometry'])
  finally:m['registry_category'].__globals__['get']=old
if __name__=='__main__':unittest.main()
