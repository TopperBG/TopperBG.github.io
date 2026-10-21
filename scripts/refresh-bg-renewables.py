#!/usr/bin/env python3
"""Build a national >1 MW inventory; never require a cadastral boundary."""
import argparse, concurrent.futures, datetime, hashlib, json, re, subprocess, time
from pathlib import Path
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'map/data/bg-renewables-cache-v1.geojson'
BASE='https://www.veiregistar.bg/'
EXCLUDED={'fets-zlaten-lev-solar'} # Previously reviewed and explicitly excluded from this atlas.
def fetch(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={'User-Agent':'EnergoKarta/1.0 public renewable inventory'}),timeout=40) as r:
                return r.read().decode('utf-8')
        except Exception:
            if attempt==2: raise
            time.sleep(attempt+1)
def norm(s): return re.sub(r'[^а-яa-z0-9]', '', s.lower())
def extract(name):
    html=(ROOT/'map/index.html').read_text()
    start=html.index('[',html.index('const '+name+' ='))
    end=html.index('];',start)+1
    return json.loads(subprocess.check_output(['node','-e','process.stdout.write(JSON.stringify(('+html[start:end]+')))']))
def feature(p,geometry=None):
    return {'type':'Feature','id':p['id'],'properties':p,'geometry':geometry}
def curated():
    rows=[]
    for name,tech,status in [('operatingSolarProjects','solar','operating'),('operatingWindProjects','wind','operating'),('cadastralProjects','solar','planned')]:
        for raw in extract(name):
            if raw.get('assetType') in ('bess','battery','storage'): continue
            mw=raw.get('mwpDc',raw.get('mwAc',raw.get('mw')))
            if mw is None:
                published=re.search(r'([\d]+(?:[.,]\d+)?)\s*MW(?:p)?\b',raw.get('statusLabel',''))
                if published: mw=float(published[1].replace(',','.'))
            if not isinstance(mw,(int,float)) or mw<=1: continue
            p=dict(raw,technology=('wind' if 'Вят' in raw['name'] or 'ВяЕ' in raw['name'] else tech),status=raw.get('status',status),mw=mw,capacityBasis=('MWp DC' if 'mwpDc' in raw else 'MW AC' if 'mwAc' in raw else 'MW'),inventorySource='atlas-curated')
            if p['status']=='approved': p['status']='planned';p['sourceStatus']='approved'
            g={'type':'Point','coordinates':[raw['lon'],raw['lat']]} if 'lon' in raw and 'lat' in raw else None
            p['locationQuality']='location-only' if g else 'unknown'
            rows.append(feature(p,g))
    return rows

def registry(list_only=False):
    home=BeautifulSoup(fetch(BASE+'objects'),'html.parser')
    categories=sorted({a['href'] for a in home.select('a[href]') if 'power-over-' in a['href']})
    if len(categories)<6: raise ValueError('Registry categories missing')
    cards={}
    for category in categories:
        first=BeautifulSoup(fetch(category),'html.parser')
        pages=max([1]+[int(x) for x in re.findall(r'&page=(\d+)',' '.join(a.get('href','') for a in first.select('a[href]')))])
        if pages>300: raise ValueError('Unexpected registry page count')
        print('Registry category',category,'pages',pages,flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            html_pages=[str(first)]+list(pool.map(fetch,[category+'&page='+str(page) for page in range(2,pages+1)]))
        for html_page in html_pages:
            soup=BeautifulSoup(html_page,'html.parser')
            batch=soup.select('a.card[href*="/object/"]')
            if not batch: raise ValueError('Empty registry page '+category)
            for a in batch: cards[a['href']]=str(a)
    places=json.loads((ROOT/'map/data/bg-place-labels-v0.85i.json').read_text())
    byname={}
    for place in places: byname.setdefault(norm(place['name']),[]).append(place)
    def detail(item):
        url,card=item
        slug=url.rsplit('/',1)[-1]
        if slug in EXCLUDED: return None
        enriched=not list_only
        try: html=card if list_only else fetch(url)
        except Exception: html=card;enriched=False
        soup=BeautifulSoup(html,'html.parser')
        box=soup.select_one('.objects' if enriched else '.card')
        text=box.get_text(' ',strip=True) if box else ''
        m=re.search(r'мощност\s*([\d., ]+)\s*МВт',text,re.I)
        if not m: raise ValueError('No capacity at '+url)
        mw=float(m[1].replace(' ','').replace(',','.'))
        if mw<=1: return None
        title=box.find('h3').get_text(' ',strip=True)
        loc=re.search(r'местоположение\s+(.+?),\s*общ\.',text)
        matches=byname.get(norm(loc[1]),[]) if loc else []
        g={'type':'Point','coordinates':[matches[0]['lon'],matches[0]['lat']]} if len(matches)==1 else None
        tech='solar' if 'ФЕЦ' in title else 'wind' if 'ВтЕЦ' in title else 'hydro' if 'ВЕЦ' in title else 'biogas' if 'БиоГ' in title else 'biomass'
        p={'id':'VEIREG-'+slug,'name':title,'mw':mw,'capacityBasis':'MW (as published)','technology':tech,'status':'operating' if re.search(r'в експ(?:ло|о)атация от',text,re.I) else 'unknown','source':url,'inventorySource':'veiregistar','location':loc[1] if loc else None,'locationQuality':'settlement-approximate' if g else 'unknown','statusLabel':'В експлоатация според ВЕИ регистъра · '+str(mw)+' MW · '+('приблизително местоположение по населено място' if g else 'без установено местоположение')}
        return feature(p,g)
    print('Registry objects',len(cards),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        return [f for f in pool.map(detail,cards.items()) if f]

def osm_inventory():
    query='[out:json][timeout:180];area["ISO3166-1"="BG"][admin_level=2]->.bg;nwr(area.bg)["plant:source"~"solar|wind|hydro|biomass|biogas|geothermal"];out center tags;'
    payload=json.loads(fetch('https://overpass-api.de/api/interpreter?data='+__import__('urllib.parse',fromlist=['quote']).quote(query)))
    rows=[]
    for el in payload['elements']:
        tags=el.get('tags',{}); power=tags.get('plant:output:electricity','')
        m=re.fullmatch(r'([\d.,]+)\s*(MW|kW|GW|W)',power)
        if not m: continue
        mw=float(m[1].replace(',','.'))*{'MW':1,'kW':.001,'GW':1000,'W':.000001}[m[2]]
        if mw<=1: continue
        status='planned' if tags.get('proposed')=='power' or tags.get('power')=='proposed' else 'construction' if tags.get('construction')=='power' or tags.get('power')=='construction' else 'operating' if tags.get('power')=='plant' else 'unknown'
        if any(k.startswith(('disused:','abandoned:','demolished:')) for k in tags): continue
        center=el.get('center',el);lon=center.get('lon');lat=center.get('lat')
        g={'type':'Point','coordinates':[lon,lat]} if lon is not None and lat is not None else None
        p={'id':f"OSM-{el['type']}-{el['id']}",'name':tags.get('name',f"ВЕИ {el['id']}"),'mw':mw,'capacityBasis':'MW (OSM)','technology':tags['plant:source'],'status':status,'source':f"https://www.openstreetmap.org/{el['type']}/{el['id']}",'inventorySource':'osm','locationQuality':'location-only' if g else 'unknown','statusLabel':'OSM · '+status+' · експлоатационният статус не е независимо потвърден'}
        rows.append(feature(p,g))
    return rows

def main():
    args=argparse.ArgumentParser();args.add_argument('--offline',action='store_true'); args.add_argument('--list-only',action='store_true',help='Import all listing pages; skip optional location enrichment'); opt=args.parse_args()
    old=json.loads(OUT.read_text()) if OUT.exists() else {'features':[]}
    rows=curated(); health={}
    if opt.offline:
        remote=[f for f in old['features'] if f['properties'].get('inventorySource')=='veiregistar']
        health={'status':'cached','mode':'offline','lastSuccess':old.get('sourceHealth',{}).get('lastSuccess')}
    else:
        try:
            remote=registry(list_only=opt.list_only);health={'status':'ok','lastSuccess':datetime.datetime.now(datetime.timezone.utc).isoformat()}
            previous=[f for f in old['features'] if f['properties'].get('inventorySource')=='veiregistar']
            if len(remote)<max(10,len(previous)*0.8): raise ValueError('Registry shrink protection')
        except Exception as e:
            remote=[f for f in old['features'] if f['properties'].get('inventorySource')=='veiregistar']
            health={'status':'stale','error':str(e),'lastSuccess':old.get('sourceHealth',{}).get('lastSuccess')}
    if not opt.offline:
        try:
            osm=osm_inventory();health['osmStatus']='ok'
        except Exception as e:
            osm=[f for f in old['features'] if f['properties'].get('inventorySource')=='osm']
            health['osmStatus']='stale';health['osmError']=str(e)
    else:
        osm=[f for f in old['features'] if f['properties'].get('inventorySource')=='osm']
    previous_by_url={f['properties'].get('source'):f for f in old['features']}
    for f in remote:
        previous=previous_by_url.get(f['properties'].get('source'))
        if f['geometry'] is None and previous and previous['geometry']:
            f['geometry']=previous['geometry'];f['properties']['locationQuality']=previous['properties']['locationQuality']
    known={norm(f['properties']['name']) for f in rows}
    urls={f['properties'].get(k) for f in rows for k in ('source','secondarySource')}
    rows += [f for f in remote if norm(f['properties']['name']) not in known and f['properties']['source'] not in urls]
    known={norm(f['properties']['name']) for f in rows}
    urls={f['properties'].get('source') for f in rows}
    rows += [f for f in osm if norm(f['properties']['name']) not in known and f['properties']['source'] not in urls]
    rows.sort(key=lambda f:f['id'])
    data={'type':'FeatureCollection','schema':'bgwf-bg-renewables-v1','generatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'thresholdMW':1,'coverage':'Partial national inventory; curated planned projects and public registry. Not an exhaustive official register.','sourceHealth':health,'counts':{'total':len(rows),'mapped':sum(f['geometry'] is not None for f in rows),'operating':sum(f['properties']['status']=='operating' for f in rows),'planned':sum(f['properties']['status']=='planned' for f in rows)},'features':rows}
    tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');tmp.replace(OUT)
    print(json.dumps(data['counts']),health)
    if health['status']=='stale': raise SystemExit(1)
if __name__=='__main__': main()
