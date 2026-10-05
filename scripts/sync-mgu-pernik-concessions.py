#!/usr/bin/env python3
"""Snapshot MGU Pernik concession polygons into the repository.

MGU is a geometry cross-check/source for the Pernik concession layer. Runtime
map rendering never depends on MGU availability: a failed refresh preserves the
last-known-good repository snapshot.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, pathlib, urllib.parse, urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/"map"/"data"/"mgu-pernik-concessions-v1.geojson"
SERVICE="https://maps.mgu.bg/arcgis/rest/services/Hosted/Concessions_Pernik/FeatureServer/0"
QUERY=SERVICE+"/query"
UA="EnergoKarta-Bulgaria-MGU-cache/1.0 (+https://topperbg.github.io/map/)"

def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")

def fetch_json(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json, application/geo+json"})
    with urllib.request.urlopen(req,timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    params={
        "where":"1=1","outFields":"*","returnGeometry":"true",
        "outSR":"4326","f":"geojson"
    }
    url=QUERY+"?"+urllib.parse.urlencode(params)
    try:
        payload=fetch_json(url)
        features=payload.get("features") or []
        if payload.get("type")!="FeatureCollection" or not features:
            raise RuntimeError("MGU returned no GeoJSON features")
        for f in features:
            g=f.get("geometry") or {}
            if g.get("type") not in ("Polygon","MultiPolygon"):
                raise RuntimeError("MGU returned non-polygon geometry")
            p=f.setdefault("properties",{})
            p["source_kind"]="MGU-concession-contract-geometry"
            p["source_url"]=SERVICE
            p["geometry_status"]="repository-cache-mgu-pernik"
        canonical=json.dumps(features,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
        out={
            "type":"FeatureCollection",
            "schema":"bgwf-mgu-pernik-concessions-v1",
            "generatedAt":now_iso(),
            "source":"MGU-PERNIK-CONCESSIONS",
            "sourceUrl":SERVICE,
            "geometryCrs":"EPSG:4326",
            "featureCount":len(features),
            "digest":hashlib.sha256(canonical).hexdigest(),
            "policy":{"runtimeRemoteDependency":False,"preserveLastKnownGoodOnFailure":True},
            "features":features,
        }
        OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(f"MGU Pernik polygons cached: {len(features)}; digest={out['digest']}")
    except Exception as exc:
        if OUT.exists():
            old=json.loads(OUT.read_text(encoding="utf-8"))
            if old.get("features"):
                print(f"::warning title=MGU unavailable::Preserving {len(old['features'])} cached polygons: {exc}")
                return
        raise

if __name__=="__main__":
    main()
