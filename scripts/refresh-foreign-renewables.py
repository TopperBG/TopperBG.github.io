#!/usr/bin/env python3
"""Refresh the repository-owned Foreign renewable cache.

Scope:
- Bulgaria's five neighbouring countries: RO, RS, MK, GR, TR
- operating wind/solar installations > 1 MW
- construction/planned wind/solar installations > 1 MW
- OSM power=plant objects (generator members are intentionally excluded)
- preserve curated seed entries and the previous valid cache on remote failure

The browser never needs Overpass for this layer; it reads the committed GeoJSON.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import math
import pathlib
import re
import tempfile
import subprocess
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "map" / "data" / "foreign-renewables-cache-v1.geojson"
SEED = ROOT / "map" / "data" / "foreign-renewables-seed-v1.json"
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
USER_AGENT = "EnergoKarta-Bulgaria-foreign-renewables/1.2 (+https://topperbg.github.io/map/)"
GEOFABRIK = {
    "RO": "https://download.geofabrik.de/europe/romania-latest.osm.pbf",
    "RS": "https://download.geofabrik.de/europe/serbia-latest.osm.pbf",
    "MK": "https://download.geofabrik.de/europe/macedonia-latest.osm.pbf",
    "GR": "https://download.geofabrik.de/europe/greece-latest.osm.pbf",
    "TR": "https://download.geofabrik.de/europe/turkey-latest.osm.pbf",
}

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
        for attempt in range(1, 2):
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
                with urllib.request.urlopen(req, timeout=75) as response:
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
    if tags.get("construction:power") == "plant" or construction or lifecycle == "construction" or status in {"construction", "under_construction"}:
        return "construction", "в строеж"
    if tags.get("proposed:power") == "plant" or tags.get("planned:power") == "plant" or proposed or lifecycle in {"proposed", "planned"} or status in {"proposed", "planned"}:
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
  nwr(area.a)["power"="plant"]["plant:source"~"solar|wind",i];
  nwr(area.a)["power"="plant"]["source"~"solar|wind",i];
  nwr(area.a)["construction:power"="plant"]["plant:source"~"solar|wind",i];
  nwr(area.a)["construction:power"="plant"]["source"~"solar|wind",i];
  nwr(area.a)["proposed:power"="plant"]["plant:source"~"solar|wind",i];
  nwr(area.a)["proposed:power"="plant"]["source"~"solar|wind",i];
  nwr(area.a)["planned:power"="plant"]["plant:source"~"solar|wind",i];
  nwr(area.a)["planned:power"="plant"]["source"~"solar|wind",i];
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
        if mw <= 1:
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


def geometry_point(geometry: dict) -> tuple[float, float] | None:
    coords = geometry.get("coordinates")
    points: list[tuple[float, float]] = []

    def walk(value):
        if isinstance(value, list):
            if len(value) >= 2 and isinstance(value[0], (int, float)) and isinstance(value[1], (int, float)):
                points.append((float(value[0]), float(value[1])))
            else:
                for item in value:
                    walk(item)

    walk(coords)
    if not points:
        return None
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def download_file(url: str, path: pathlib.Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as response, path.open("wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)


def geofabrik_country(code: str) -> list[dict]:
    if shutil.which("osmium") is None:
        raise RuntimeError("osmium-tool is unavailable for Geofabrik fallback")
    url = GEOFABRIK[code]
    with tempfile.TemporaryDirectory(prefix=f"foreign-{code.lower()}-") as tmp:
        tmpdir = pathlib.Path(tmp)
        source = tmpdir / f"{code}.osm.pbf"
        filtered = tmpdir / f"{code}-plants.osm.pbf"
        exported = tmpdir / f"{code}-plants.geojsonseq"
        download_file(url, source)
        subprocess.run([
            "osmium", "tags-filter", str(source),
            "nwr/power=plant",
            "nwr/construction:power=plant",
            "nwr/proposed:power=plant",
            "nwr/planned:power=plant",
            "-o", str(filtered), "--overwrite",
        ], check=True, timeout=600)
        subprocess.run([
            "osmium", "export", str(filtered),
            "-f", "geojsonseq",
            "--add-unique-id=type_id",
            "-x", "print_record_separator=false",
            "-o", str(exported), "--overwrite",
        ], check=True, timeout=600)

        rows = []
        with exported.open(encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip().lstrip("\x1e")
                if not line:
                    continue
                try:
                    feature = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tags = feature.get("properties") or {}
                tech = technology(tags)
                mw = parse_capacity_mw(tags)
                xy = geometry_point(feature.get("geometry") or {})
                if tech not in {"solar", "wind"} or mw is None or mw <= 1 or not xy:
                    continue
                status, status_label = lifecycle_status(tags)
                unique_id = str(feature.get("id") or tags.get("@id") or f"{code}-{len(rows)+1}")
                name = str(tags.get("name") or tags.get("operator") or f"OSM {unique_id}").strip()
                rows.append({
                    "type": "Feature",
                    "properties": {
                        "id": f"GEOFABRIK-{code}-{unique_id}",
                        "name": name,
                        "country": COUNTRIES[code],
                        "countryCode": code,
                        "technology": tech,
                        "status": status,
                        "statusLabel": status_label,
                        "mw": round(mw, 4),
                        "major": mw > 50,
                        "source": url,
                        "osm_id": unique_id,
                        "operator": tags.get("operator"),
                        "start_date": tags.get("start_date"),
                        "sourceMode": "geofabrik-osm-auto",
                    },
                    "geometry": {"type": "Point", "coordinates": [xy[0], xy[1]]},
                })
        return rows


def discover_country(code: str) -> tuple[list[dict], str]:
    try:
        return geofabrik_country(code), "geofabrik"
    except Exception as geofabrik_error:
        print(f"WARNING {code}: Geofabrik failed ({geofabrik_error}); trying Overpass fallback.")
        return query_country(code), "overpass"

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

def seed_features() -> list[dict]:
    payload = json.loads(SEED.read_text(encoding="utf-8")) if SEED.exists() else {"projects": []}
    rows = []
    reverse_country = {v: k for k, v in COUNTRIES.items()}
    for project in payload.get("projects") or []:
        try:
            mw = float(project.get("mw") or 0)
            lon = float(project.get("lon"))
            lat = float(project.get("lat"))
        except (TypeError, ValueError):
            continue
        if mw <= 1 or project.get("technology") not in {"solar", "wind"}:
            continue
        status = project.get("status") or "planned"
        if status not in {"operating", "construction", "planned"}:
            continue
        props = dict(project)
        props.update({
            "countryCode": reverse_country.get(project.get("country")),
            "major": mw > 50,
            "sourceMode": "curated-seed",
        })
        osm_ids = project.get("osmIds") or []
        if osm_ids and not props.get("osm_id"):
            props["osm_id"] = osm_ids[0]
        rows.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        })
    return rows


def main() -> None:
    existing = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {"features": []}
    existing_by_country = {code: [] for code in COUNTRIES}
    for feature in existing.get("features") or []:
        code = (feature.get("properties") or {}).get("countryCode")
        if code in existing_by_country:
            existing_by_country[code].append(feature)

    curated = seed_features()
    curated_by_country = {code: [] for code in COUNTRIES}
    for feature in curated:
        code = (feature.get("properties") or {}).get("countryCode")
        if code in curated_by_country:
            curated_by_country[code].append(feature)

    merged_all: list[dict] = []
    errors: dict[str, str] = {}
    source_health: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(COUNTRIES)) as pool:
        futures = {pool.submit(discover_country, code): code for code in COUNTRIES}
        for future in concurrent.futures.as_completed(futures):
            code = futures[future]
            country = COUNTRIES[code]
            try:
                discovered, discovery_source = future.result()
                merged = dedupe(curated_by_country[code] + discovered)
                merged = [
                    f for f in merged
                    if (f.get("properties") or {}).get("technology") in {"solar", "wind"}
                    and (f.get("properties") or {}).get("status") in {"operating", "construction", "planned"}
                    and float((f.get("properties") or {}).get("mw") or 0) > 1
                ]
                merged_all.extend(merged)
                source_health[code] = {
                    "country": country, "ok": True, "source": discovery_source, "discovered": len(discovered),
                    "curated": len(curated_by_country[code]), "published": len(merged),
                }
                print(f"{code}: {len(discovered)} {discovery_source} >1 MW + {len(curated_by_country[code])} curated -> {len(merged)}")
            except Exception as exc:
                errors[code] = str(exc)
                preserved = existing_by_country.get(code) or curated_by_country[code]
                merged_all.extend(preserved)
                source_health[code] = {
                    "country": country, "ok": False, "error": str(exc),
                    "preserved": len(preserved), "curated": len(curated_by_country[code]),
                }
                print(f"WARNING {code}: {exc}; preserving {len(preserved)} last-known-good record(s)")

    merged = dedupe(merged_all)
    merged = [
        f for f in merged
        if (f.get("properties") or {}).get("technology") in {"solar", "wind"}
        and (f.get("properties") or {}).get("status") in {"operating", "construction", "planned"}
        and float((f.get("properties") or {}).get("mw") or 0) > 1
    ]
    merged.sort(key=lambda f: (
        (f.get("properties") or {}).get("countryCode") or "",
        -float((f.get("properties") or {}).get("mw") or 0),
        (f.get("properties") or {}).get("name") or "",
    ))
    if not merged:
        raise RuntimeError("Refusing to publish an empty Foreign renewable cache")

    output = {
        "type": "FeatureCollection",
        "schema": "bgwf-foreign-renewables-cache-v1",
        "generatedAt": now_iso(),
        "scope": {
            "countries": list(COUNTRIES),
            "technologies": ["solar", "wind"],
            "statusPolicy": {
                "operatingMinimumMwExclusive": 1,
                "constructionPlannedMinimumMwExclusive": 1,
            },
            "majorThresholdMwExclusive": 50,
        },
        "refresh": {
            "source": "OpenStreetMap / Overpass plus curated seed",
            "lastKnownGoodPreservedOnFailure": True,
            "perCountryLastKnownGood": True,
            "countryErrors": errors,
            "sourceHealth": source_health,
        },
        "featureCount": len(merged),
        "majorCount": sum(1 for f in merged if float((f.get("properties") or {}).get("mw") or 0) > 50),
        "features": merged,
    }
    CACHE.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status_counts = {}
    for feature in merged:
        status = (feature.get("properties") or {}).get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    print(f"Published {len(merged)} Foreign wind/solar objects >1 MW; >50 MW: {output['majorCount']}; statuses: {status_counts}")

if __name__ == "__main__":
    main()
