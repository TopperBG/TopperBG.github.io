#!/usr/bin/env python3
"""Increment the atlas patch version and synchronize its active display locations."""
import argparse
import json
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
VERSION_FILE=ROOT/'map/data/map-version.json'

def render(version):
 page=ROOT/'map/index.html';text=page.read_text()
 replacements=[
  (r'(map-interface\.(?:css|js)\?v=)[\d.]+',rf'\g<1>{version}'),
  (r'(<meta name="bgwf-build" content=")[^"]+(">)',rf'\g<1>v{version}\2'),
  (r'(<title>[^<]*? · )v[\w.]+(</title>)',rf'\g<1>v{version}\2'),
  (r'(<span class="bgwf-filter-version">)v[^<]+(</span>)',rf'\g<1>v{version}\2'),
  (r"(version:')[^']+(', engine:'OpenLayers)",rf'\g<1>{version}\2'),
  (r"(a.download=')bgwf-v[\w.]+-debug-report.json(';)",rf'\g<1>bgwf-v{version}-debug-report.json\2')]
 for pattern,replacement in replacements:
  text,count=re.subn(pattern,replacement,text)
  expected=2 if 'map-interface' in pattern else 1
  if count!=expected:raise ValueError(f'Expected {expected} active version locations: {pattern}; found {count}')
 listing=ROOT/'map/renewables.html';list_text=listing.read_text()
 list_text=re.sub(r' · v[\d.]+(?=</title>)','',list_text)
 list_text,count=re.subn(r'(<title>[^<]+)(</title>)',rf'\g<1> · v{version}\2',list_text)
 if count!=1:raise ValueError('Missing inventory title')
 if 'data-atlas-version' in list_text:
  list_text,count=re.subn(r'(<span data-atlas-version[^>]*>)[^<]+(</span>)',rf'\g<1>v{version}\2',list_text)
  if count!=1:raise ValueError('Missing inventory version label')
 else:
  list_text,count=re.subn(r'(</h1>)',rf'\1<p><span data-atlas-version style="font-size:12px;color:#64748b">v{version}</span></p>',list_text,count=1)
  if count!=1:raise ValueError('Missing inventory heading')
 return {page:text,listing:list_text}

def main():
 parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group();mode.add_argument('--check',action='store_true');mode.add_argument('--set-version');args=parser.parse_args()
 stored=json.loads(VERSION_FILE.read_text())['version']
 if not re.fullmatch(r'\d+\.\d+\.\d+',stored):raise ValueError('Expected major.minor.patch')
 if args.check:
  for path,expected in render(stored).items():
   if path.read_text()!=expected:raise SystemExit(f'Version mismatch: {path.relative_to(ROOT)}')
  print('Version synchronized: v'+stored);return
 major,minor,patch=map(int,stored.split('.'));version=args.set_version or f'{major}.{minor}.{patch+1}'
 if not re.fullmatch(r'\d+\.\d+\.\d+',version):parser.error('Expected major.minor.patch for --set-version')
 if tuple(map(int,version.split('.')))<=tuple(map(int,stored.split('.'))):parser.error('New version must be greater than the stored version')
 output=render(version)
 for path,content in output.items():path.write_text(content)
 VERSION_FILE.write_text(json.dumps({'version':version},indent=2)+'\n')
 print('Atlas version: v'+version)

if __name__=='__main__':main()
