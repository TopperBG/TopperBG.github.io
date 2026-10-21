#!/usr/bin/env python3
"""Resolve actual listed solar parcels through AGKK, never village/town centres.
A representative interior point is saved for one verified parcel, not a park boundary.
"""
import argparse
import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'map/data/bg-renewables-cache-v1.geojson'
LOCATIONS=ROOT/'map/data/bg-renewables-locations-v1.json'
ENDPOINT='https://inspire.cadastre.bg/arcgis/rest/services/Cadastral_Parcel/MapServer/0/query'

def interior_point(rings):
 """Even-odd scanline: handles disjoint rings and holes, independent of winding."""
 ys=sorted({float(p[1]) for ring in rings for p in ring})
 if len(ys)<2:raise ValueError('Degenerate parcel')
 y=(ys[0]+ys[-1])/2
 for ordinate in [y]+[(a+b)/2 for a,b in zip(ys,ys[1:])]:
  xs=[]
  for ring in rings:
   for a,b in zip(ring,ring[1:]+ring[:1]):
    if (a[1]>ordinate)!=(b[1]>ordinate):xs.append(a[0]+(ordinate-a[1])*(b[0]-a[0])/(b[1]-a[1]))
  xs.sort();spans=[(xs[i+1]-xs[i],(xs[i]+xs[i+1])/2) for i in range(0,len(xs)-1,2) if xs[i+1]>xs[i]]
  if spans:
   _,x=max(spans);return [round(x,7),round(ordinate,7)]
 raise ValueError('No interior point')

def query(refs):
 where='nationalcadastralref IN ('+','.join("'"+r+"'" for r in refs)+')'
 params={'where':where,'outFields':'nationalcadastralref','returnGeometry':'true','outSR':'4326','f':'json'}
 url=ENDPOINT+'?'+urllib.parse.urlencode(params)
 last=None
 for attempt in range(2):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'EnergoKarta-BG-location-enrichment/1.0 (+https://topperbg.github.io/map/)'})
   with urllib.request.urlopen(req,timeout=40) as response:data=json.load(response)
   if data.get('error'):raise ValueError(str(data['error']))
   if 'features' not in data:raise ValueError('Invalid AGKK response')
   return {f['attributes']['nationalcadastralref']:(f['geometry']['rings'],url) for f in data['features'] if f.get('geometry',{}).get('rings')}
  except Exception as exc:
   last=exc
   if attempt==0:time.sleep(1)
 raise RuntimeError(str(last))

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--rounds',type=int,default=3);args=parser.parse_args()
 data=json.loads(CACHE.read_text());saved=json.loads(LOCATIONS.read_text()) if LOCATIONS.exists() else {'schema':'bgwf-renewable-locations-v1','locations':{}}
 locations=saved['locations'];now=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
 pending=[f for f in data['features'] if f['properties']['technology']=='solar' and not f['geometry'] and f['properties'].get('parcels') and f['id'] not in locations]
 found=0;errors=[]
 for index in range(max(0,args.rounds)):
  refs=sorted({f['properties']['parcels'][index] for f in pending if len(f['properties']['parcels'])>index})
  if not refs:break
  batches=[refs[i:i+12] for i in range(0,len(refs),12)];resolved={}
  with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
   futures={pool.submit(query,b):b for b in batches}
   for future in concurrent.futures.as_completed(futures):
    try:resolved.update(future.result())
    except Exception as exc:errors.append({'parcels':futures[future],'error':str(exc)})
  for f in pending:
   p=f['properties'];ref=next((r for r in p['parcels'] if r in resolved),None)
   if not ref:continue
   rings,url=resolved[ref];coordinate=interior_point(rings)
   if not (22<coordinate[0]<29 and 41<coordinate[1]<45):raise ValueError('Out-of-Bulgaria coordinates')
   locations[f['id']]={'geometry':{'type':'Point','coordinates':coordinate},'geometryQuality':'parcel-location','geometrySource':url,'locationParcelRef':ref,'locationMethod':'representative interior point of one listed AGKK parcel; partial site location','locationCheckedAt':now}
   found+=1;print(p['id'],p['name'],coordinate,ref,flush=True)
  pending=[f for f in pending if f['id'] not in locations]
  saved['lastAttempt']={'checkedAt':now,'added':found,'unresolvedIds':[f['id'] for f in pending],'errors':errors}
  LOCATIONS.write_text(json.dumps(saved,ensure_ascii=False,indent=2)+'\n')
 print('Added:',found,'Unresolved:',len(pending),'Errors:',len(errors),flush=True)

if __name__=='__main__':main()
