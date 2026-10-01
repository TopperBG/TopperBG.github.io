#!/usr/bin/env python3
"""Refresh official Pernik concession polygons in the consolidated industrial cache."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import urllib.parse
import urllib.request
import urllib.error
import time

from pyproj import Transformer

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "map" / "data" / "industrial-zones-cache-v1.json"
SERVICE = "https://maps.mgu.bg/arcgis/rest/services/Hosted/Concessions_Pernik/FeatureServer/0/query"
SOURCE_URL = "https://maps.mgu.bg/arcgis/rest/services/Hosted/Concessions_Pernik/FeatureServer"
OUT_FIELDS = "objectid,concession_id,name,находище,концесионер,ncr_url,status,lastupdate,SHAPE__Area"

WGS84 = Transformer.from_crs("EPSG:7801", "EPSG:4326", always_xy=True)


def post_json(params: dict[str, str]) -> dict:
    """Fetch ArcGIS JSON with retries and GET fallback.

    maps.mgu.bg occasionally returns HTTP 500 from its Web Adaptor while the
    repository cache is still perfectly usable. Treat 5xx/network failures as
    transient; never destroy the last-known-good cache because of them.
    """
    encoded = urllib.parse.urlencode(params)
    last_error: Exception | None = None
    for attempt in range(1, 5):
        for method in ("POST", "GET"):
            if method == "POST":
                request = urllib.request.Request(
                    SERVICE,
                    data=encoded.encode("utf-8"),
                    headers={
                        "User-Agent": "EnergoKarta-Bulgaria-cache-refresh/1.2",
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    method="POST",
                )
            else:
                request = urllib.request.Request(
                    f"{SERVICE}?{encoded}",
                    headers={
                        "User-Agent": "EnergoKarta-Bulgaria-cache-refresh/1.2",
                        "Accept": "application/json",
                    },
                    method="GET",
                )
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    payload = json.load(response)
                if payload.get("error"):
                    raise RuntimeError(payload["error"].get("message", "ArcGIS error"))
                return payload
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", "replace")
                last_error = RuntimeError(
                    f"ArcGIS {method} HTTP {error.code}: {body[:600]}"
                )
                if error.code < 500:
                    raise last_error from error
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = RuntimeError(f"ArcGIS {method} network/JSON error: {error}")
        if attempt < 4:
            time.sleep(4 * attempt)
    raise RuntimeError(f"MGU ArcGIS unavailable after retries: {last_error}")


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
            "outFields": "*",
            "returnGeometry": "true",
            "f": "json",
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

    try:
        features = fetch_features()
    except Exception as error:
        section = cache.get("concessions") or {}
        cached = section.get("features") or []
        cached_count = len(cached)
        print(
            "::warning title=MGU concession refresh skipped::"
            f"{error}. Preserving last-known-good cache ({cached_count} polygons)."
        )
        if cached_count == 0:
            print(
                "::warning title=Concession cache currently empty::"
                "The official MGU service is unavailable and there is no previously "
                "cached polygon set yet. The workflow remains green so a temporary "
                "external outage does not look like a repository/build failure."
            )
        return

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
