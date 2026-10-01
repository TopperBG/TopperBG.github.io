#!/usr/bin/env python3
"""Refresh official Pernik concession polygons in the consolidated industrial cache."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import urllib.parse
import urllib.request

from pyproj import Transformer

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "map" / "data" / "industrial-zones-cache-v1.json"
SERVICE = "https://maps.mgu.bg/arcgis/rest/services/Hosted/Concessions_Pernik/FeatureServer/0/query"
SOURCE_URL = "https://maps.mgu.bg/arcgis/rest/services/Hosted/Concessions_Pernik/FeatureServer"
OUT_FIELDS = "objectid,concession_id,name,находище,концесионер,ncr_url,status,lastupdate,SHAPE__Area"

WGS84 = Transformer.from_crs("EPSG:7801", "EPSG:4326", always_xy=True)


def post_json(params: dict[str, str]) -> dict:
    request = urllib.request.Request(
        SERVICE,
        data=urllib.parse.urlencode(params).encode("utf-8"),
        headers={
            "User-Agent": "EnergoKarta-Bulgaria-cache-refresh/1.1",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.load(response)
    if payload.get("error"):
        raise RuntimeError(payload["error"].get("message", "ArcGIS error"))
    return payload


def transform_ring(ring: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for point in ring:
        if len(point) < 2:
            continue
        lon, lat = WGS84.transform(float(point[0]), float(point[1]))
        out.append([round(lon, 8), round(lat, 8)])
    if len(out) >= 3 and out[0] != out[-1]:
        out.append(out[0])
    return out


def fetch_features() -> list[dict]:
    payload = post_json(
        {
            "where": "1=1",
            "outFields": OUT_FIELDS,
            "returnGeometry": "true",
            "outSR": "7801",
            "f": "json",
            "resultRecordCount": "2000",
        }
    )

    features: list[dict] = []
    for item in payload.get("features", []):
        rings = (item.get("geometry") or {}).get("rings") or []
        polygons = []
        for ring in rings:
            transformed = transform_ring(ring)
            if len(transformed) >= 4:
                # Each ArcGIS ring is kept as a separate polygon part. The map
                # renders boundaries only, so this preserves all official rings
                # without inventing topology between multiple outer rings/holes.
                polygons.append([transformed])
        if not polygons:
            continue

        properties = dict(item.get("attributes") or {})
        properties["source_url"] = SOURCE_URL
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": {"type": "MultiPolygon", "coordinates": polygons},
            }
        )

    features.sort(
        key=lambda feature: (
            str(feature["properties"].get("concession_id") or ""),
            str(
                feature["properties"].get("name")
                or feature["properties"].get("находище")
                or ""
            ),
        )
    )
    if not features:
        raise RuntimeError("Official Pernik concession service returned zero polygon features")
    return features


def main() -> None:
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    if cache.get("schema") != "bgwf-industrial-zones-cache-v1":
        raise RuntimeError("Unexpected industrial cache schema")

    features = fetch_features()
    now = (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    section = cache.setdefault("concessions", {})
    section["schema"] = "bgwf-industry-concessions-cache-v1"
    section["generatedAt"] = now
    section["geometryCrs"] = "EPSG:4326"
    section["featureCount"] = len(features)
    section["features"] = features

    remote_sources = section.setdefault("remoteSources", [])
    source = next(
        (item for item in remote_sources if item.get("id") == "MGU-PERNIK"),
        None,
    )
    if source is None:
        source = {"id": "MGU-PERNIK"}
        remote_sources.append(source)
    source.update(
        {
            "type": "ArcGIS FeatureServer",
            "url": SERVICE,
            "sourceUrl": SOURCE_URL,
            "sourceCrs": "EPSG:7801",
            "geometry": "official contract-derived polygons; transformed in GitHub Actions to EPSG:4326",
            "lastFetchedAt": now,
            "featureCount": len(features),
        }
    )

    cache.setdefault("lastUpdatedSections", {})["concessions"] = now
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(features)} concession polygons to {CACHE_PATH}")


if __name__ == "__main__":
    main()
