#!/usr/bin/env python3
"""Refresh official Pernik concession polygons in the consolidated industrial cache."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "map" / "data" / "industrial-zones-cache-v1.json"
SERVICE = "https://maps.mgu.bg/arcgis/rest/services/Hosted/Concessions_Pernik/FeatureServer/0/query"
SOURCE_URL = "https://maps.mgu.bg/arcgis/rest/services/Hosted/Concessions_Pernik/FeatureServer"

PARAMS = {
    "where": "1=1",
    "outFields": "*",
    "returnGeometry": "true",
    "outSR": "4326",
    "f": "geojson",
}


def fetch_geojson() -> dict:
    url = SERVICE + "?" + urllib.parse.urlencode(PARAMS)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "EnergoKarta-Bulgaria-cache-refresh/1.0",
            "Accept": "application/geo+json, application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.load(response)
    if payload.get("error"):
        raise RuntimeError(payload["error"].get("message", "ArcGIS error"))
    if payload.get("type") != "FeatureCollection":
        raise RuntimeError("ArcGIS response is not a GeoJSON FeatureCollection")
    return payload


def stable_features(payload: dict) -> list[dict]:
    features: list[dict] = []
    for raw in payload.get("features", []):
        geometry = raw.get("geometry") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        if not geometry.get("coordinates"):
            continue
        properties = dict(raw.get("properties") or {})
        properties.setdefault("source_url", SOURCE_URL)
        features.append(
            {"type": "Feature", "properties": properties, "geometry": geometry}
        )

    features.sort(
        key=lambda feature: (
            str(
                feature["properties"].get("concession_id")
                or feature["properties"].get("идентификационен_____партиден__")
                or ""
            ),
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

    features = stable_features(fetch_geojson())
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
            "geometry": "official contract-derived polygons",
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
