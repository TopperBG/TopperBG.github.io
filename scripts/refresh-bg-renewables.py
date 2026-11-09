#!/usr/bin/env python3
"""Central BG renewable inventory. Unknown locations remain valid null GeoJSON geometry.
Only explicitly published capacities >1 MW; no estimates from land area.
"""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import html
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'map/data/bg-renewables-cache-v1.geojson'
HEALTH = ROOT / 'map/data/bg-renewables-health-v1.json'
KAZANLAK_PARCELS = ROOT / 'map/data/kazanlak-solar-official-parcels-v1.geojson'
TECHS = {
 'photovoltaic-power-plants-with-power-over-1-mw': 'solar',
 'wind-power-plants-with-power-over-1-mw': 'wind',
 'hydropower-plants-with-power-over-1-mw': 'hydro',
 'micro-hydropower-plants-with-power-over-1-mw': 'hydro',
 'pumped-accumulating-hydropower-plants-with-power-over-1-mw': 'pumped_hydro',
 'biomass-power-plants-with-power-over-4-mw': 'biomass',
 'renewable-gas-power-plants-sources-with-power-over-1-mw': 'biogas',
}
# Explicit user correction: do not reintroduce the removed object automatically.
EXCLUDED = {'https://www.veiregistar.bg/object/fets-zlaten-lev-solar'}

def text(s):
 return ' '.join(html.unescape(re.sub('<[^>]+>', ' ', s)).split())

def feature(p, geometry=None):
 return {'type':'Feature', 'id':p['id'], 'properties':p, 'geometry':geometry}

def embedded():
 js = r'''const fs=require('fs'),vm=require('vm');const h=fs.readFileSync(process.argv[1],'utf8');let out={};for(const name of ['operatingSolarProjects','operatingWindProjects','cadastralProjects','CURATED_SOLAR_FOOTPRINTS']){const m=h.match(new RegExp('(?:const|let)\\s+'+name+'\\s*=\\s*(\\[[\\s\\S]*?\\n\\s*\\]);'));if(!m)throw Error(name);out[name]=vm.runInNewContext('('+m[1]+')',{}, {timeout:1000});}const transitioned=h.match(/const transitionedToOperatingProjectIds = new Set\((\[[^;]*?\])\)/);out.transitionedIds=transitioned?JSON.parse(transitioned[1]):[];console.log(JSON.stringify(out));'''
 data=json.loads(subprocess.check_output(['node','-e',js,str(ROOT/'map/index.html')]))
 footprints={p['id']:p for p in data['CURATED_SOLAR_FOOTPRINTS']}
 result=[]; skipped=[]
 for group, tech, status in [('operatingSolarProjects','solar','operating'),('operatingWindProjects','wind','operating'),('cadastralProjects',None,'planned'),('CURATED_SOLAR_FOOTPRINTS','solar','operating')]:
  for row in data[group]:
   if row.get('assetType')=='substation' or row['id'] in data.get('transitionedIds',[]): continue
   mw=next((row[k] for k in ('mwAc','mwpDc','mw','mwMin') if isinstance(row.get(k),(int,float))),None)
   if mw is None:
    # Capacity text is accepted only with an explicit unit, never from parcel areas.
    m=re.search(r'(\d+(?:[.,]\d+)?)\s*(MWp?|МВт)\b',row.get('statusLabel',''),re.I)
    if m: mw=float(m[1].replace(',','.'))
   if mw is None or mw<=1:
    skipped.append({'id':row['id'],'name':row['name'],'reason':'capacity_not_published_or_not_above_1_MW'});continue
   source=row.get('source','')
   if source in EXCLUDED: continue
   geom=footprints.get(row['id'],{}).get('geometry')
   quality='footprint' if geom else 'unknown'
   if not geom and all(isinstance(row.get(k),(int,float)) for k in ('lon','lat')):
    geom={'type':'Point','coordinates':[row['lon'],row['lat']]};quality='location-only'
   p=dict(row,technology=row.get('technology') or tech or ('wind' if re.search('вят|ВяЕЦ|ВяЕИ|wind',row['name'],re.I) else 'solar'),status=row.get('status',status),mw=mw,countryCode='BG',geometryQuality=quality,sourceMode='curated',capacityBasis='AC' if 'mwAc' in row else 'DC' if 'mwpDc' in row else 'unspecified')
   if geom and row['id'] in footprints:
    footprint=footprints[row['id']];p['geometrySource']=footprint.get('source',source);p['geometryRef']=footprint.get('parcelRef')
   if row['id']=='RES-008':
    parcel_cache=json.loads((ROOT/'map/data/agkk-built-vei-cache.json').read_text())['features']
    parcels=[parcel_cache[ref]['feature'] for ref in row['parcels']]
    geom={'type':'MultiPolygon','coordinates':[f['geometry']['coordinates'] for f in parcels]}
    p.update(geometryQuality='cadastral-parcels',geometrySourceMode='agkk',geometryRefs=row['parcels'],geometrySource='https://inspire.cadastre.bg/arcgis/rest/services/Cadastral_Parcel/MapServer/0',geometryEvidence=row['capacitySource'],geometryNote='Граници на имоти по ПУП; проект, не изградена централа.')
   p['sourceStatus']=p['status'];p['status']='planned' if p['status']=='approved' else p['status']
   p.pop('geometry',None);result.append(feature(p,geom))
 return result,skipped

def get(url):
 req=urllib.request.Request(url,headers={'User-Agent':'EnergoKarta-BG-inventory/1.0 (+https://topperbg.github.io/map/)'})
 with urllib.request.urlopen(req,timeout=30) as response:return response.read().decode('utf-8')

def registry_category(item):
 category,tech=item; base='https://www.veiregistar.bg/objects&type='+category
 first=get(base)
 pages={1}|{int(n) for n in re.findall(r'&(?:amp;)?page=(\d+)',first)}
 result=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  bodies=[first]+list(pool.map(get,[base+'&page='+str(page) for page in range(2,max(pages)+1)]))
 for page,body in enumerate(bodies,1):
  cards=re.findall(r'<a\b[^>]*href="(https://www\.veiregistar\.bg/object/[^"]+)"[^>]*>(.*?)</a>',body,re.S)
  if not cards: raise ValueError('No registry cards: '+base+' page '+str(page))
  for url,card in cards:
   if url in EXCLUDED:continue
   title=re.search(r'<h3\b[^>]*>(.*?)</h3>',card,re.S)
   power=re.search(r'([\d.,]+)\s*МВт',text(card))
   if not title or not power:raise ValueError('Unrecognized registry card: '+url)
   mw=float(power[1].replace(',','.'))
   if mw<=1:continue
   result.append(feature({'id':'VEIREG-'+url.rsplit('/',1)[1],'name':text(title[1]),'mw':mw,'capacityBasis':'unspecified','technology':tech,'status':'operating','statusLabel':text(card),'source':url,'countryCode':'BG','sourceMode':'veiregistar','geometryQuality':'unknown'}))
 return result

def osm():
 spec=importlib.util.spec_from_file_location('foreign',ROOT/'scripts/refresh-foreign-renewables.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 query='[out:json][timeout:150];area["ISO3166-1"="BG"][admin_level=2]->.a;('
 for key in ('power','construction:power','proposed:power','planned:power'):
  query+=f'nwr(area.a)["{key}"="plant"];'
 query+=');out tags center;'
 result=[]
 for el in m.request_overpass(query).get('elements',[]):
  tags=el.get('tags',{});raw=' '.join(str(tags.get(k,'')) for k in ('plant:source','generator:source')).lower()
  tech=next((t for token,t in [('solar','solar'),('wind','wind'),('hydro','hydro'),('biomass','biomass'),('biogas','biogas'),('geothermal','geothermal')] if token in raw),None)
  if not tech or any(k.startswith(('disused:','abandoned:','demolished:')) and v=='plant' for k,v in tags.items()):continue
  mw=None
  for key in m.CAPACITY_KEYS:
   power=re.fullmatch(r'\s*(\d+(?:[.,]\d+)?)\s*(GW|MW|kW|W)\s*',str(tags.get(key,'')),re.I)
   if power:
    mw=float(power[1].replace(',','.'))*{'gw':1000,'mw':1,'kw':0.001,'w':0.000001}[power[2].lower()];break
  if mw is None or mw<=1:continue
  if tags.get('status') in ('decommissioned','abandoned','disused','demolished'):continue
  if tech=='hydro' and 'pumped' in str(tags.get('plant:method','')):tech='pumped_hydro'
  status,label=m.lifecycle_status(tags);point=m.element_point(el)
  result.append(feature({'id':'OSM-BG-'+m.osm_id(el),'name':tags.get('name') or tags.get('operator') or 'OSM '+m.osm_id(el),'mw':mw,'capacityBasis':'unspecified','technology':tech,'status':status,'statusLabel':label+' · OpenStreetMap','source':f"https://www.openstreetmap.org/{el['type']}/{el['id']}",'countryCode':'BG','sourceMode':'osm','geometryQuality':'location-only' if point else 'unknown'}, {'type':'Point','coordinates':list(point)} if point else None))
 return result

def transitioned_ids():
 match=re.search(r'const transitionedToOperatingProjectIds = new Set\((\[[^;]*?\])\)',(ROOT/'map/index.html').read_text())
 return set(json.loads(match[1])) if match else set()

def apply_locations(rows):
 path=ROOT/'map/data/bg-renewables-locations-v1.json'
 locations=json.loads(path.read_text()).get('locations',{}) if path.exists() else {}
 for f in rows:
  location=locations.get(f['properties']['id'])
  if location and not f.get('geometry'):
   f['geometry']=location['geometry']
   f['properties'].update({k:v for k,v in location.items() if k!='geometry'})
 return rows

def last_success(mode, previous_health, previous):
 """A rebuild/attempt timestamp must never become a source observation date."""
 known=previous_health.get('sources',{}).get(mode,{})
 if known.get('lastSuccessAt'):return known['lastSuccessAt']
 dates=[f['properties'].get('retrievedAt') for f in previous
        if f['properties'].get('sourceMode')==mode and f['properties'].get('retrievedAt')]
 return max(dates,default=previous_health.get('checkedAt') if known.get('status')=='ok' else None)

def apply_freshness(rows, health):
 for f in rows:
  p=f['properties']
  p['sourceFreshness']={mode:{k:health['sources'][mode].get(k) for k in ('status','lastAttemptAt','lastSuccessAt')} for mode in p.get('sourceModes',[p.get('sourceMode')]) if mode in health.get('sources',{})}
 return rows

def merge(rows):
 path=ROOT/'map/data/bg-renewables-identities-v1.json'
 reviewed=json.loads(path.read_text()) if path.exists() else {}
 entities=reviewed.get('entities',[])
 aliases={member:e['canonicalId'] for e in entities for member in e['memberIds']}
 distinct={frozenset(pair['memberIds']) for pair in reviewed.get('distinctPairs',[])}
 preferred_geometry={e['canonicalId']:e.get('geometryMemberId') for e in entities}
 def geometry_rank(f):
  if not f.get('geometry'):return 0
  p=f['properties']
  if f['geometry']['type'] in ('Polygon','MultiPolygon'):return 100 if p.get('geometryQuality')=='cadastral-parcels' else 80
  if p.get('geometryQuality')=='parcel-location':return 50
  if preferred_geometry.get(p['id'])==p.get('geometryRecordId') and p.get('geometryRecordId'):return 40
  return 10
 def norm(value):return re.sub(r'[^\w]','',value.lower())
 def sources(p):return {str(u) for u in [p.get('source'),p.get('secondarySource'),p.get('geometrySource'),*(p.get('sources') or [])] if u}
 def keys(p):
  found={}
  for url in sources(p):
   osm=re.search(r'openstreetmap\.org/(node|way|relation)/(\d+)',url)
   if osm:found['osm:'+osm[1]+':'+osm[2]]=True
   elif 'veiregistar.bg/object/' in url:found['url:'+url.rstrip('/')]=True
   else:found['url:'+url+'|name:'+norm(p['name'])]=True
  for ref in (p.get('geometryRef'),p.get('parcelRef'),p.get('osm_id')):
   osm=re.fullmatch(r'(?:OSM-)?([NWR])(\d+)',str(ref or ''),re.I)
   if osm:found['osm:'+{'n':'node','w':'way','r':'relation'}[osm[1].lower()]+':'+osm[2]]=True
  return set(found)
 result=[];by_key={};by_id={};retired_planning_ids=transitioned_ids()
 # Confirmed canonical entries retain their displayed name/capacity.
 prepared=apply_locations(json.loads(json.dumps(rows)))
 for original in sorted(prepared,key=lambda f:0 if aliases.get(f['properties']['id'])==f['properties']['id'] else 1):
  if original['properties']['id'] in retired_planning_ids:continue
  f=original;p=f['properties'];raw_id=p['id'];ident=aliases.get(raw_id,raw_id);p['id']=ident;f['id']=ident
  p.setdefault('statusSourceMode',p.get('sourceMode','unknown'))
  p.setdefault('capacitySourceMode',p.get('sourceMode','unknown'))
  if f.get('geometry'):
   p.setdefault('geometryRecordId',raw_id)
   p.setdefault('geometrySourceMode','osm' if 'openstreetmap.org/' in str(p.get('geometrySource','')) else p.get('sourceMode','unknown'))
  p.pop('possibleDuplicateIds',None)
  p['sourceModes']=sorted(set(p.get('sourceModes',[])+[p.get('sourceMode','unknown')]))
  members=set(p.get('mergedIds',[])+[raw_id,ident])
  match=by_id.get(ident)
  if match is None:match=next((by_key[k] for k in sorted(keys(p)) if k in by_key),None)
  if match is not None:
   old=result[match]['properties'];members.update(old.get('mergedIds',[]));members.add(old['id'])
   old['sources']=sorted(sources(old)|sources(p))
   old['sourceModes']=sorted(set(old.get('sourceModes',[])+p['sourceModes']))
   old['mergedIds']=sorted(members)
   observations=[{'source':q['source'],'mw':q['mw'],'capacityBasis':q.get('capacityBasis','unspecified')} for q in (old,p)]
   observations+=old.get('capacityObservations',[])+p.get('capacityObservations',[])
   unique={json.dumps(o,sort_keys=True):o for o in observations}
   if len({(o['mw'],o['capacityBasis']) for o in unique.values()})>1:old['capacityObservations']=list(unique.values())
   if f.get('geometry') and geometry_rank(f)>geometry_rank(result[match]):
    result[match]['geometry']=f['geometry']
    for k in list(old):
     if k.startswith(('geometry','location')):old.pop(k)
    old.update({k:v for k,v in p.items() if k.startswith(('geometry','location'))})
    old.setdefault('geometrySource',p.get('geometrySource',p['source']))
   for k in keys(p):by_key[k]=match
   for member in members:by_id[member]=match
   continue
  index=len(result);by_id[ident]=index
  for member in members:by_id[member]=index
  for key in keys(p):by_key[key]=index
  if len(members)>1:p['mergedIds']=sorted(members)
  result.append(f)
 groups={}
 for f in result:groups.setdefault(norm(f['properties']['name']),[]).append(f)
 for group in groups.values():
  if len(group)>1:
   for f in group:
    possible=[other['id'] for other in group if other is not f and frozenset((f['id'],other['id'])) not in distinct]
    if possible:f['properties']['possibleDuplicateIds']=possible
 return sorted(apply_locations(result),key=lambda f:f['id'])

def apply_inventory_relationships(rows):
 """Separate plant identity from constituent units; never sum a park with its units."""
 config=json.loads((ROOT/'map/data/bg-renewables-identities-v1.json').read_text())
 by_id={f['id']:f for f in rows}
 for f in rows:
  for key in ('componentOf','componentRecords','identityReviewNote','displayName','inventoryReviewStatus'):f['properties'].pop(key,None)
 for pair in config.get('distinctPairs',[]):
  for ident in pair['memberIds']:
   if ident in by_id:by_id[ident]['properties']['identityReviewNote']=pair['note']
 for ident,name in config.get('displayNames',{}).items():
  if ident in by_id:by_id[ident]['properties']['displayName']=name
 for item in config.get('pendingLocationReviews',[]):
  target=by_id.get(item['id'])
  if target is None:continue
  target['properties']['identityReviewNote']=item['note']
  if not target.get('geometry'):target['properties']['inventoryReviewStatus']='pending-location'
 for group in config.get('componentGroups',[]):
  parent=by_id.get(group['parentId'])
  if parent is None or not parent.get('geometry'):continue
  records=[]
  for ident in group['memberIds']:
   child=by_id.get(ident)
   if child is None:continue
   child['properties']['componentOf']=parent['id']
   records.append({'id':ident,**{k:child['properties'][k] for k in ('name','mw','capacityBasis','source','sourceMode','sourceModes','statusSourceMode','capacitySourceMode','sourceFreshness','retrievedAt') if k in child['properties']}})
  if records:parent['properties']['componentRecords']=records
 return rows

def validate_source_batch(mode,batch,previous):
 if not batch:raise ValueError('Empty source response')
 # Reject partial registry responses before replacing the last valid records.
 if mode.startswith('veiregistar:'):
  before=sum(mode in f['properties'].get('sourceModes',[f['properties'].get('sourceMode')]) for f in previous)
  if before>=10 and len(batch)<before*0.8:
   raise ValueError(f'Registry shrink protection: {len(batch)} records, previously {before}')

def apply_kazanlak_official_parcels(rows):
 """Keep the published AGKK parcel boundaries through automated OSM refreshes."""
 parcel_data=json.loads(KAZANLAK_PARCELS.read_text())
 expected={f'15864.10.{n}' for n in range(1,10)}|{'15864.10.47','87641.69.155','87641.69.190','87641.69.252','87641.69.253','87641.69.334'}
 parcels=parcel_data['features']
 refs={f['properties']['nationalcadastralref'] for f in parcels}
 if refs!=expected or len(parcels)!=len(expected):raise ValueError('Kazanlak AGKK parcel set changed')
 for parcel in parcels:
  geometry=parcel['geometry']
  if geometry['type']!='Polygon' or not geometry['coordinates'] or any(ring[0]!=ring[-1] for ring in geometry['coordinates']):
   raise ValueError('Invalid official Kazanlak parcel geometry')
 target=next((f for f in rows if f['id']=='OSM-BG-R16941504'),None)
 if target is None:raise ValueError('Kazanlak solar farm is missing from renewable inventory')
 target['geometry']={'type':'MultiPolygon','coordinates':[parcel['geometry']['coordinates'] for parcel in parcels]}
 p=target['properties']
 p['geometryQuality']='cadastral-parcels'
 p['geometrySourceMode']='agkk'
 p['geometrySource']=parcel_data['geometrySource']
 p['geometryRefs']=sorted(refs)
 p['geometryEvidence']=parcel_data['projectEvidence']
 p['geometryNote']='Граници на имоти на комплекса; не са контур само на фотоволтаичните панели.'
 return rows

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--offline',action='store_true');ap.add_argument('--reconcile-only',action='store_true');args=ap.parse_args()
 previous=json.loads(OUT.read_text()) if OUT.exists() else {'features':[]}
 previous_health=json.loads(HEALTH.read_text()) if HEALTH.exists() else {}
 rows,skipped=embedded();health={'checkedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'sources':{},'excludedCapacityUnknown':skipped}
 modes=[*[(f'veiregistar:{category}',lambda c=category,t=tech:registry_category((c,t))) for category,tech in TECHS.items()],('osm',osm)]
 if args.reconcile_only:
  rows+=previous['features']
  checked_at=health['checkedAt']
  health=json.loads(HEALTH.read_text()) if HEALTH.exists() else health
  health['reconciledAt']=checked_at;health['excludedCapacityUnknown']=skipped;modes=[]
 for mode,fn in modes:
  try:
   if args.offline:raise RuntimeError('offline: remote source not checked')
   batch=fn();validate_source_batch(mode,batch,previous['features'])
   for f in batch:
    f['properties']['sourceMode']=mode
    f['properties']['retrievedAt']=health['checkedAt']
   print(mode+': '+str(len(batch))+' records',flush=True)
   rows+=batch;health['sources'][mode]={'status':'ok','records':len(batch),'lastAttemptAt':health['checkedAt'],'lastSuccessAt':health['checkedAt']}
  except Exception as exc:
   retained=[f for f in previous['features'] if mode in f['properties'].get('sourceModes',[f['properties'].get('sourceMode')])];rows+=retained
   health['sources'][mode]={'status':'stale' if retained else 'unavailable','error':str(exc),'retained':len(retained),'lastAttemptAt':health['checkedAt'],'lastSuccessAt':last_success(mode,previous_health,previous['features'])}
 rows=apply_kazanlak_official_parcels(merge(rows))
 # Reconciliation may enrich geometry, but does not recheck remote sources.
 for mode,source in health.get('sources',{}).items():
  source.setdefault('lastAttemptAt',health.get('checkedAt'))
  source.setdefault('lastSuccessAt',last_success(mode,previous_health,previous['features']))
 rows=apply_inventory_relationships(apply_freshness(rows,health))
 for f in rows:
  p=f['properties'];assert math.isfinite(p['mw']) and p['mw']>1 and p['source'].startswith('https://')
  assert p['status'] in ('operating','construction','planned')
  if f['geometry'] and f['geometry']['type']=='Point':
   lon,lat=f['geometry']['coordinates'];assert 22<lon<29 and 41<lat<45
 payload={'type':'FeatureCollection','schema':'bgwf-bg-renewables-cache-v1','generatedAt':health.get('reconciledAt',health['checkedAt']),'scope':'Bulgaria; explicitly published capacity >1 MW','coverage':'partial; discovery sources are not an exhaustive national register','aggregation':'Do not sum AC/DC, pumped storage or unresolved cross-source duplicates together.','features':rows}
 OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
 health['counts']={s:sum(f['properties']['status']==s for f in rows) for s in ('operating','construction','planned')};health['withoutGeometry']=sum(f['geometry'] is None for f in rows)
 HEALTH.write_text(json.dumps(health,ensure_ascii=False,indent=2)+'\n');print(json.dumps(health,ensure_ascii=False))

if __name__=='__main__':main()
