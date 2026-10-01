#!/usr/bin/env python3
"""Snapshot verified industrial/mining OSM polygons into repository GeoJSON.

This removes browser-runtime dependence on Nominatim/Overpass for known sites.
Remote OSM is used only by the weekly updater to refresh a last-known-good copy.

Outputs:
  map/data/industry-footprints-baseline.geojson
  map/data/disturbed-mining-sites-v1.geojson
  map/data/disturbed-mining-sites-pending-v1.json
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "map" / "data"
CACHE_PATH = DATA / "industrial-zones-cache-v1.json"
ALL_PATH = DATA / "industry-footprints-baseline.geojson"
DISTURBED_PATH = DATA / "disturbed-mining-sites-v1.geojson"
PENDING_PATH = DATA / "disturbed-mining-sites-pending-v1.json"

NOMINATIM = "https://nominatim.openstreetmap.org/lookup"
USER_AGENT = "EnergoKarta-Bulgaria-footprint-snapshot/1.0 (+https://topperbg.github.io/map/)"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_geojson(path: pathlib.Path) -> dict:
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("type") == "FeatureCollection":
            return data
    except Exception:
        pass
    return {"type": "FeatureCollection", "features": []}


def osm_key_from_feature(feature: dict) -> str | None:
    p = feature.get("properties") or {}
    key = p.get("osm_key") or p.get("osmKey")
    if key:
        return str(key)
    osm_type = str(p.get("osm_type") or p.get("osmType") or "").lower()
    osm_id = p.get("osm_id") or p.get("osmId")
    if osm_id is None:
        return None
    prefix = "R" if osm_type in ("relation", "r") else "W"
    return f"{prefix}{osm_id}"


def query_batch(keys: list[str]) -> list[dict]:
    params = urllib.parse.urlencode({
        "osm_ids": ",".join(keys),
        "format": "geojson",
        "polygon_geojson": "1",
        "addressdetails": "0",
        "extratags": "1",
    })
    req = urllib.request.Request(
        f"{NOMINATIM}?{params}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json, application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("features") or []


def is_polygon(feature: dict) -> bool:
    return (feature.get("geometry") or {}).get("type") in ("Polygon", "MultiPolygon")


def disturbed_item(item: dict) -> bool:
    parent = str(item.get("parentId") or "").upper()
    component = str(item.get("component") or "").lower()
    name = str(item.get("name") or "").lower()
    if parent.startswith("MINE-"):
        return True
    blob = f"{component} {name}"
    return bool(re.search(
        r"рудник|мина|mine|quarry|карие|хвост|tailing|насип|spoil|отвал|сгур|шлако|пепел|ash|"
        r"утай|slurry|settling|езеро|acid|кисел|mining|landfill",
        blob,
        re.I,
    ))


def main() -> None:
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    items = cache.get("footprints") or []
    verified = [
        i for i in items
        if i.get("geometryStatus") == "verified-osm" and i.get("osmType") in ("W", "R") and i.get("osmId")
    ]
    by_key = {f"{i['osmType']}{i['osmId']}": i for i in verified}

    existing_all = load_geojson(ALL_PATH)
    existing_by_key = {
        key: f for f in existing_all.get("features") or []
        if (key := osm_key_from_feature(f)) and is_polygon(f)
    }

    fetched_by_key: dict[str, dict] = {}
    errors = []
    keys = sorted(by_key)
    for start in range(0, len(keys), 20):
        batch = keys[start:start + 20]
        try:
            for raw in query_batch(batch):
                if not is_polygon(raw):
                    continue
                p = raw.get("properties") or {}
                osm_type = str(p.get("osm_type") or "").lower()
                prefix = "R" if osm_type == "relation" else "W"
                osm_id = p.get("osm_id")
                if osm_id is not None:
                    fetched_by_key[f"{prefix}{osm_id}"] = raw
        except Exception as exc:
            errors.append({"batch": batch, "error": str(exc)})
        if start + 20 < len(keys):
            time.sleep(1.1)

    generated = now_iso()
    all_features = []
    missing = []
    for key in keys:
        item = by_key[key]
        raw = fetched_by_key.get(key) or existing_by_key.get(key)
        if not raw:
            missing.append({
                "parentId": item.get("parentId"),
                "name": item.get("name"),
                "component": item.get("component"),
                "osmKey": key,
                "reason": "remote_geometry_unavailable_and_no_repository_snapshot",
            })
            continue
        f = {
            "type": "Feature",
            "properties": {
                "parent_id": item.get("parentId"),
                "name": item.get("name"),
                "component": item.get("component"),
                "osm_key": key,
                "osm_type": item.get("osmType"),
                "osm_id": item.get("osmId"),
                "geometry_status": "repository-snapshot-verified-osm",
                "source_kind": "OpenStreetMap snapshot",
                "source_url": f"https://www.openstreetmap.org/{'relation' if item.get('osmType') == 'R' else 'way'}/{item.get('osmId')}",
                "inventory_revision": item.get("revision") or cache.get("revision"),
                "snapshot_at": generated,
                "legacy_or_historical": bool(item.get("legacy") or item.get("historical")),
            },
            "geometry": raw["geometry"],
        }
        all_features.append(f)

    # Never shrink a repository baseline because a remote lookup temporarily failed.
    current_keys = {osm_key_from_feature(f) for f in all_features}
    for key, old in existing_by_key.items():
        if key not in current_keys and key in by_key:
            all_features.append(old)

    all_features.sort(key=lambda f: str((f.get("properties") or {}).get("osm_key") or ""))
    all_fc = {
        "type": "FeatureCollection",
        "schema": "bgwf-industry-footprints-baseline-v1",
        "generatedAt": generated,
        "runtimeDependency": False,
        "featureCount": len(all_features),
        "source": "repository snapshot of verified OSM polygons listed in industrial-zones-cache-v1.json",
        "features": all_features,
    }

    disturbed_keys = {key for key, item in by_key.items() if disturbed_item(item)}
    disturbed_features = [
        f for f in all_features
        if (f.get("properties") or {}).get("osm_key") in disturbed_keys
    ]
    disturbed_fc = {
        "type": "FeatureCollection",
        "schema": "bgwf-disturbed-mining-sites-v1",
        "generatedAt": generated,
        "runtimeDependency": False,
        "featureCount": len(disturbed_features),
        "semantics": (
            "Physical developed/disturbed mining, quarry, tailings, spoil/waste or related footprints. "
            "Not legal concession boundaries. Retained independently of current concession status."
        ),
        "features": disturbed_features,
    }

    pending = []
    for item in items:
        if not disturbed_item(item):
            continue
        key = f"{item.get('osmType','')}{item.get('osmId','')}" if item.get("osmId") else None
        if key and any((f.get("properties") or {}).get("osm_key") == key for f in disturbed_features):
            continue
        pending.append({
            "parentId": item.get("parentId"),
            "name": item.get("name"),
            "component": item.get("component"),
            "geometryStatus": item.get("geometryStatus"),
            "osmKey": key,
            "areaDka": item.get("areaDka"),
            "lon": item.get("lon"),
            "lat": item.get("lat"),
            "reason": "exact_polygon_not_archived" if item.get("geometryStatus") != "verified-osm" else "OSM_snapshot_unavailable",
        })

    ALL_PATH.write_text(json.dumps(all_fc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    DISTURBED_PATH.write_text(json.dumps(disturbed_fc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PENDING_PATH.write_text(json.dumps({
        "schema": "bgwf-disturbed-mining-pending-v1",
        "generatedAt": generated,
        "pendingCount": len(pending),
        "remoteErrors": errors,
        "pending": pending,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Industry footprint baseline: {len(all_features)} polygon(s); disturbed subset: {len(disturbed_features)}; pending disturbed: {len(pending)}.")
    if errors:
        print(f"Remote batch errors: {len(errors)}; last-known-good geometry preserved.")


if __name__ == "__main__":
    main()
