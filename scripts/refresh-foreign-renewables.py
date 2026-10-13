#!/usr/bin/env python3
"""Refresh the repository-owned Foreign renewable cache.

Scope:
- Bulgaria's five neighbouring countries: RO, RS, MK, GR, TR
- operating wind/solar installations > 1 MW
- construction/planned wind/solar installations > 10 MW
- OSM power=plant plus area-mapped power=generator objects
- preserve curated seed entries and the previous valid cache on remote failure

The browser never needs Overpass for this layer; it reads the committed GeoJSON.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "map" / "data" / "foreign-renewables-cache-v1.geojson"
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
COUNTRIES = {
    "RO": "Румъния",
    "RS": "Сърбия",
    "MK": "Северна Македония",
    "GR": "Гърция",
    "TR": "Турция",
}
USER_AGENT = "EnergoKarta-Bulgaria-foreign-renewables/1.1 (+https://topperbg.github.io/map/)"

CAPACITY_KEYS = (
    "plant:output:electricity",
    "generator:output:electricity",
    "output:electricity",
    "capacity",
    "plant:output",
    "generator:output",
)

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def parse_capacity_mw(tags: dict) -> float | None:
    for key in CAPACITY_KEYS:
        raw = str(tags.get(key) or "").strip().lower().replace(",", ".")
        if not raw or raw in {"yes", "no", "unknown"}:
            continue
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(gw|mw|kw|w)?", raw)
        if not m:
            continue
        value = float(m.group(1))
        unit = m.group(2)
        if unit == "gw":
            value *= 1000
        elif unit == "kw":
            value /= 1000
        elif unit == "w":
            value /= 1_000_000
        elif unit is None and value > 100_000:
            value /= 1_000_000
        elif unit is None and value > 10_000:
            value /= 1000
        if math.isfinite(value) and value > 0:
            return value
    return None

def technology(tags: dict) -> str | None:
    source = " ".join(
        str(tags.get(k) or "").lower()
        for k in ("plant:source", "generator:source", "source", "generator:method")
    )
    if "solar" in source or "photovoltaic" in source:
        return "solar"
    if "wind" in source:
        return "wind"
    return None

def request_overpass(query: str) -> dict:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last = None
    for endpoint in ENDPOINTS:
        for attempt in range(1, 3):
            req = urllib.request.Request(
                endpoint,
                data=body,
                headers={
                    "User-Agent": USER_AGENT,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=180) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                time.sleep(attempt * 3)
    raise RuntimeError(f"All Overpass endpoints failed: {last}")

def element_point(el: dict) -> tuple[float, float] | None:
    if el.get("type") == "node":
        lat, lon = el.get("lat"), el.get("lon")
    else:
        center = el.get("center") or {}
        lat, lon = center.get("lat"), center.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return float(lon), float(lat)
    return None

def osm_id(el: dict) -> str:
    prefix = {"node": "N", "way": "W", "relation": "R"}.get(el.get("type"), "?")
    return f"{prefix}{el.get('id')}"

def normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())

def lifecycle_status(tags: dict) -> tuple[str, str]:
    lifecycle = str(tags.get("lifecycle") or "").lower()
    construction = str(tags.get("construction") or "").lower()
    proposed = str(tags.get("proposed") or "").lower()
    status = str(tags.get("status") or "").lower()
    if construction or lifecycle == "construction" or status in {"construction", "under_construction"}:
        return "construction", "в строеж"
    if proposed or lifecycle in {"proposed", "planned"} or status in {"proposed", "planned"}:
        return "planned", "планиран"
    return "operating", "действащ"

def query_country(code: str) -> list[dict]:
    # Operating plants/generator areas plus lifecycle-tagged planned/construction
    # objects. Generator nodes are deliberately excluded to avoid counting each
    # individual wind turbine as a separate wind farm.
    query = f"""
[out:json][timeout:150];
area["ISO3166-1"="{code}"][admin_level=2]->.a;
(
  nwr(area.a)["power"="plant"];
  way(area.a)["power"="generator"];
  relation(area.a)["power"="generator"];
  nwr(area.a)["construction"="power"]["power"!="generator"];
  nwr(area.a)["proposed"="power"]["power"!="generator"];
  nwr(area.a)["lifecycle"~"^(construction|proposed|planned)$"];
);
out tags center;
"""
    payload = request_overpass(query)
    result = []
    for el in payload.get("elements") or []:
        tags = el.get("tags") or {}
        tech = technology(tags)
        if tech not in {"solar", "wind"}:
            continue
        mw = parse_capacity_mw(tags)
        if mw is None:
            continue
        status, status_label = lifecycle_status(tags)
        threshold = 1 if status == "operating" else 10
        if mw <= threshold:
            continue
        point = element_point(el)
        if not point:
            continue
        name = str(tags.get("name") or tags.get("operator") or f"OSM {osm_id(el)}").strip()
        result.append({
            "type": "Feature",
            "properties": {
                "id": f"OSM-{code}-{osm_id(el)}",
                "name": name,
                "country": COUNTRIES[code],
                "countryCode": code,
                "technology": tech,
                "status": status,
                "statusLabel": status_label,
                "mw": round(mw, 4),
                "major": mw > 50,
                "source": f"https://www.openstreetmap.org/{'node' if el.get('type')=='node' else 'way' if el.get('type')=='way' else 'relation'}/{el.get('id')}",
                "osm_id": osm_id(el),
                "operator": tags.get("operator"),
                "start_date": tags.get("start_date"),
                "sourceMode": "osm-auto",
            },
            "geometry": {"type": "Point", "coordinates": [point[0], point[1]]},
        })
    return result

def dedupe(features: list[dict]) -> list[dict]:
    by_osm: dict[str, dict] = {}
    no_osm: list[dict] = []
    for f in features:
        p = f.get("properties") or {}
        oid = p.get("osm_id")
        if oid:
            previous = by_osm.get(oid)
            if previous is None or float(p.get("mw") or 0) > float((previous.get("properties") or {}).get("mw") or 0):
                by_osm[oid] = f
        else:
            no_osm.append(f)

    combined = list(by_osm.values()) + no_osm
    kept: list[dict] = []
    for f in sorted(combined, key=lambda x: float((x.get("properties") or {}).get("mw") or 0), reverse=True):
        p = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
        key_name = normalized_name(str(p.get("name") or ""))
        duplicate = False
        for k in kept:
            kp = k.get("properties") or {}
            kc = (k.get("geometry") or {}).get("coordinates") or [None, None]
            if p.get("countryCode") != kp.get("countryCode") or p.get("technology") != kp.get("technology"):
                continue
            same_name = key_name and key_name == normalized_name(str(kp.get("name") or ""))
            close = all(isinstance(v, (int, float)) for v in (*coords, *kc)) and abs(coords[0]-kc[0]) < 0.025 and abs(coords[1]-kc[1]) < 0.025
            similar_power = abs(float(p.get("mw") or 0)-float(kp.get("mw") or 0)) <= max(0.2, 0.03*float(kp.get("mw") or 0))
            if (same_name and close) or (close and similar_power):
                duplicate = True
                break
        if not duplicate:
            kept.append(f)
    return kept

def main() -> None:
    existing = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {"features": []}
    curated = []
    for f in existing.get("features") or []:
        p = f.get("properties") or {}
        if p.get("sourceMode") != "curated-seed":
            continue
        mw = float(p.get("mw") or 0)
        status = p.get("status")
        if (status == "operating" and mw > 1) or (status in {"construction","planned"} and mw > 10):
            curated.append(f)

    discovered: list[dict] = []
    errors: dict[str, str] = {}
    for code in COUNTRIES:
        try:
            rows = query_country(code)
            discovered.extend(rows)
            print(f"{code}: {len(rows)} operating wind/solar objects >1 MW")
        except Exception as exc:
            errors[code] = str(exc)
            print(f"WARNING {code}: {exc}")

    if not discovered:
        # Last-known-good rule: do not overwrite a valid cache if every remote
        # query failed or produced no capacity-bearing operating objects.
        if existing.get("features"):
            print("No fresh OSM data; preserving existing repository cache.")
            return
        raise RuntimeError("No fresh data and no previous Foreign cache")

    merged = dedupe(curated + discovered)
    filtered = []
    for f in merged:
        p = f.get("properties") or {}
        mw = float(p.get("mw") or 0)
        status = p.get("status")
        if p.get("technology") not in {"solar","wind"}:
            continue
        if status == "operating" and mw > 1:
            filtered.append(f)
        elif status in {"construction","planned"} and mw > 10:
            filtered.append(f)
    merged = filtered
    merged.sort(key=lambda f: (
        (f.get("properties") or {}).get("countryCode") or "",
        -float((f.get("properties") or {}).get("mw") or 0),
        (f.get("properties") or {}).get("name") or "",
    ))

    output = {
        "type": "FeatureCollection",
        "schema": "bgwf-foreign-renewables-cache-v1",
        "generatedAt": now_iso(),
        "scope": {
            "countries": list(COUNTRIES),
            "technologies": ["solar", "wind"],
            "statusPolicy": {
                "operatingMinimumMwExclusive": 1,
                "constructionPlannedMinimumMwExclusive": 10,
            },
            "majorThresholdMwExclusive": 50,
        },
        "refresh": {
            "source": "OpenStreetMap / Overpass plus curated seed",
            "lastKnownGoodPreservedOnFailure": True,
            "countryErrors": errors,
        },
        "featureCount": len(merged),
        "majorCount": sum(1 for f in merged if float((f.get("properties") or {}).get("mw") or 0) > 50),
        "features": merged,
    }
    CACHE.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status_counts = {}
    for f in merged:
        s=(f.get("properties") or {}).get("status","unknown")
        status_counts[s]=status_counts.get(s,0)+1
    print(f"Published {len(merged)} Foreign wind/solar objects; >50 MW: {output['majorCount']}; statuses: {status_counts}")

if __name__ == "__main__":
    main()
