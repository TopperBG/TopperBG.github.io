#!/usr/bin/env python3
"""Refresh the local MOEW protected-territory snapshot; no drone rules."""
import datetime
import json
import pathlib
import urllib.parse
import urllib.request

SERVICE = 'https://natura2000.egov.bg/arcgis/rest/services/OpenData/ProtectedAreaOpenData_Feature/MapServer'
REGISTER = 'https://eea.government.bg/zpo/bg/'
CATEGORIES = {'BG01': 'Резерват', 'BG02': 'Национален парк', 'BG03': 'Природна забележителност', 'BG04': 'Поддържан резерват', 'BG05': 'Природен парк', 'BG06': 'Защитена местност'}
# Known discrepancies between the spatial service and the register identifiers.
# Source: https://github.com/MartinovEm/drone-zones-bg/blob/main/tools/nature_bans.py
REGISTER_FIX = {('BG06', 'Манастирска стълба'): '6/619', ('BG01', 'Вельов вир (Водните лилии)'): '4/22', ('BG03', 'Еленска глава'): '', ('BG06', 'Залив Корал'): ''}

def main():
    features = []
    for layer in (4, 5, 6, 7):
        params = {'where': '1=1', 'outFields': 'OBJECTID,NameBg,NameEn,SiteCode,DesigAbbr,DocumentArea', 'returnGeometry': 'true', 'outSR': 4326, 'geometryPrecision': 6, 'f': 'geojson'}
        url = f'{SERVICE}/{layer}/query?' + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=180) as response:
            data = json.load(response)
        if data.get('error') or data.get('properties', {}).get('exceededTransferLimit') or not data.get('features'):
            raise RuntimeError(f'Incomplete response for layer {layer}')
        for feature in data['features']:
            p = feature['properties']
            cat, name = p['DesigAbbr'].strip(), p['NameBg'].strip()
            if cat not in CATEGORIES or not feature.get('geometry'):
                raise RuntimeError(f'Invalid area: {p}')
            key = REGISTER_FIX.get((cat, name), f'{int(cat[2:])}/{int(p["SiteCode"])}')
            p['categoryLabel'] = CATEGORIES[cat]
            p['registerUrl'] = REGISTER + ('area.jsp?' + urllib.parse.urlencode({'NEM_Partition': 1, 'categoryID': key.split('/')[0], 'areaID': key.split('/')[1]}) if key else '')
            p['registerExact'] = bool(key)
            feature['id'] = f'{layer}-{p["OBJECTID"]}'
            features.append(feature)
    if len(features) < 1000:
        raise RuntimeError('Unexpectedly small snapshot')
    output = {'type': 'FeatureCollection', 'metadata': {'source': 'МОСВ — отворени данни за защитени територии', 'sourceUrl': SERVICE, 'registerUrl': REGISTER, 'retrievedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'featureCount': len(features), 'geometryCrs': 'EPSG:4326', 'geometryPrecision': 6, 'simplification': 'none', 'layers': [4,5,6,7]}, 'features': features}
    target = pathlib.Path(__file__).resolve().parents[1] / 'map/data/protected-areas-bg-v1.geojson'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(output, ensure_ascii=False, separators=(',', ':')) + '\n')
    temporary.replace(target)
    print(f'Cached {len(features)} territories ({target.stat().st_size:,} bytes)')

if __name__ == '__main__':
    main()
