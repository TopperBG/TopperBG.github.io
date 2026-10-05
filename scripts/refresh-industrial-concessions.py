#!/usr/bin/env python3
"""Weekly national concession source check.

Primary inventory/status source: data.egov.bg.
Secondary fallback/check: National Concession Register (NKR).
Tertiary official audit/fallback: Ministry of Energy register pages.

The geometry baseline is repository-owned and last-known-good. This job NEVER
empties concession geometry when a remote source is unavailable.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "map" / "data" / "industrial-zones-cache-v1.json"
HEALTH_PATH = ROOT / "map" / "data" / "gis-source-health-v1.json"
INVENTORY_PATH = ROOT / "map" / "data" / "concession-inventory-v1.json"
BASELINE_PATH = ROOT / "map" / "data" / "official-concessions-baseline.geojson"
PENDING_PATH = ROOT / "map" / "data" / "pending-concessions-v1.json"
DISTURBED_PATH = ROOT / "map" / "data" / "disturbed-mining-sites-v1.geojson"
ABANDONED_INVENTORY_PATH = ROOT / "map" / "data" / "abandoned-mining-waste-inventory-v1.json"
MGU_CACHE_PATH = ROOT / "map" / "data" / "mgu-pernik-concessions-v1.geojson"

EGOV_API = "https://data.egov.bg/api"
NKR_EXPORT = "https://nkr.government.bg/Concessions/Export?file=csv"
NKR_PAGE = "https://nkr.government.bg/Concessions"
ME_CONCESSIONS = "https://www.me.government.bg/bg/themes/koncesii-za-dobiv-735-1613.html"
ME_ABANDONED = "https://www.me.government.bg/bg/themes/spisak-na-zakritite-vklyuchitelno-i-na-izostavenite-saorajeniya-za-minni-otpadaci-2158-1615.html"
MGU_SERVICE = "https://maps.mgu.bg/arcgis/rest/services/Hosted/Concessions_Pernik/FeatureServer/0"
USER_AGENT = "EnergoKarta-Bulgaria-concessions/2.0 (+https://topperbg.github.io/map/)"

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def request_bytes(url: str, *, data: bytes | None = None, content_type: str | None = None, timeout: int = 45) -> bytes:
    last: Exception | None = None
    for attempt in range(1, 4):
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < 3:
                time.sleep(attempt * 3)
    raise RuntimeError(f"{url}: {last}")

def check_egov() -> dict:
    checked = now_iso()
    payload = {
        "records_per_page": 100,
        "page_number": 1,
        "criteria": {"keywords": "подземни богатства", "locale": "bg"},
    }
    try:
        raw = request_bytes(
            f"{EGOV_API}/listDatasets",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )
        data = json.loads(raw.decode("utf-8"))
        datasets = data.get("datasets") or []
        relevant = []
        for ds in datasets:
            blob = " ".join(str(ds.get(k) or "") for k in ("name", "descript")).lower()
            if "концес" in blob or "подземни богатства" in blob:
                relevant.append({
                    "uri": ds.get("uri"),
                    "name": ds.get("name"),
                    "updated_at": ds.get("updated_at"),
                    "resourceCount": len(ds.get("resource") or {}),
                })
        digest = hashlib.sha256(json.dumps(relevant, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        return {
            "id": "DATA-EGOV-BG", "role": "primary", "ok": True, "checkedAt": checked,
            "url": EGOV_API, "datasetMatches": len(relevant),
            "totalRecords": data.get("total_records"), "digest": digest,
            "datasets": relevant[:20],
        }
    except Exception as exc:
        return {"id": "DATA-EGOV-BG", "role": "primary", "ok": False, "checkedAt": checked, "url": EGOV_API, "error": str(exc)}

def check_nkr() -> dict:
    checked = now_iso()
    export_error = None
    try:
        raw = request_bytes(NKR_EXPORT)
        text = raw.decode("cp1251", errors="replace")
        rows = [line for line in text.splitlines() if line.strip()]
        if len(rows) < 50:
            raise RuntimeError(f"unexpectedly small export: {len(rows)} rows")
        return {
            "id": "NKR", "role": "secondary", "ok": True, "checkedAt": checked,
            "url": NKR_EXPORT, "mode": "export", "rows": len(rows),
            "digest": hashlib.sha256(raw).hexdigest(),
        }
    except Exception as exc:
        export_error = str(exc)

    # The export endpoint has historically returned 5xx while the public
    # registry itself remains healthy. Treat the HTML registry as a valid
    # availability/change-check fallback, without pretending it is a full dump.
    try:
        raw = request_bytes(NKR_PAGE)
        text = raw.decode("utf-8", errors="replace")
        low = text.lower()
        if "концес" not in low or ("подзем" not in low and "добив" not in low):
            raise RuntimeError("registry HTML does not contain expected concession markers")
        return {
            "id": "NKR", "role": "secondary", "ok": True, "checkedAt": checked,
            "url": NKR_PAGE, "mode": "html-registry-fallback",
            "bytes": len(raw), "digest": hashlib.sha256(raw).hexdigest(),
            "exportError": export_error,
        }
    except Exception as html_exc:
        return {
            "id": "NKR", "role": "secondary", "ok": False, "checkedAt": checked,
            "url": NKR_PAGE,
            "error": f"export: {export_error}; html: {html_exc}",
        }

def check_mgu() -> dict:
    checked = now_iso()
    url = MGU_SERVICE + "/query?" + urllib.parse.urlencode({
        "where": "1=1", "outFields": "*", "returnGeometry": "false", "f": "json"
    })
    try:
        raw = request_bytes(url)
        data = json.loads(raw.decode("utf-8"))
        features = data.get("features") or []
        if not features:
            raise RuntimeError("MGU query returned no concession records")
        digest = hashlib.sha256(json.dumps(features, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        return {"id":"MGU-PERNIK-CONCESSIONS","role":"geometry-cross-check","ok":True,
                "checkedAt":checked,"url":MGU_SERVICE,"records":len(features),"digest":digest}
    except Exception as exc:
        return {"id":"MGU-PERNIK-CONCESSIONS","role":"geometry-cross-check","ok":False,
                "checkedAt":checked,"url":MGU_SERVICE,"error":str(exc)}

def check_page(source_id: str, role: str, url: str, marker: str) -> dict:
    checked = now_iso()
    try:
        raw = request_bytes(url)
        text = raw.decode("utf-8", errors="replace")
        if marker.lower() not in text.lower():
            raise RuntimeError(f"expected marker not found: {marker}")
        return {
            "id": source_id, "role": role, "ok": True, "checkedAt": checked,
            "url": url, "bytes": len(raw), "digest": hashlib.sha256(raw).hexdigest(),
        }
    except Exception as exc:
        return {"id": source_id, "role": role, "ok": False, "checkedAt": checked, "url": url, "error": str(exc)}

def main() -> None:
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    if cache.get("schema") != "bgwf-industrial-zones-cache-v1":
        raise RuntimeError("Unexpected industrial cache schema")

    sources = [
        check_egov(),
        check_nkr(),
        check_mgu(),
        check_page("ME-CONCESSIONS", "tertiary", ME_CONCESSIONS, "Концесии за добив"),
        check_page("ME-ABANDONED-MINING-WASTE", "historical-disturbed", ME_ABANDONED, "изоставените"),
    ]
    primary = next(s for s in sources if s["id"] == "DATA-EGOV-BG")
    secondary = next(s for s in sources if s["id"] == "NKR")
    tertiary = next(s for s in sources if s["id"] == "ME-CONCESSIONS")

    if primary["ok"]:
        active = "DATA-EGOV-BG"
    elif secondary["ok"]:
        active = "NKR"
    elif tertiary["ok"]:
        active = "ME-CONCESSIONS"
    else:
        active = "REPOSITORY-CACHE"

    section = cache.setdefault("concessions", {})
    features = section.get("features") or []
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8")) if INVENTORY_PATH.exists() else {"records": []}
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8")) if BASELINE_PATH.exists() else {"features": features}
    pending = json.loads(PENDING_PATH.read_text(encoding="utf-8")) if PENDING_PATH.exists() else {"pending": section.get("pending") or []}
    disturbed = json.loads(DISTURBED_PATH.read_text(encoding="utf-8")) if DISTURBED_PATH.exists() else {"features": []}
    abandoned = json.loads(ABANDONED_INVENTORY_PATH.read_text(encoding="utf-8")) if ABANDONED_INVENTORY_PATH.exists() else {"records": []}
    mgu_cache = json.loads(MGU_CACHE_PATH.read_text(encoding="utf-8")) if MGU_CACHE_PATH.exists() else {"features": []}
    inventory_count = len(inventory.get("records") or [])
    baseline_count = len(baseline.get("features") or [])
    pending_count = len(pending.get("pending") or [])
    disturbed_count = len(disturbed.get("features") or [])
    abandoned_count = len(abandoned.get("records") or [])
    section["schema"] = section.get("schema") or "bgwf-industry-concessions-cache-v1"
    section["geometryCrs"] = "EPSG:4326"
    section["featureCount"] = len(features)
    section["sourcePolicy"] = {
        "primary": "DATA-EGOV-BG",
        "secondary": "NKR",
        "tertiary": "ME-CONCESSIONS",
        "geometry": "repository baseline from official coordinate registers/acts",
        "runtimeRemoteDependency": False,
        "lastKnownGood": True,
        "activeRegistrySource": active,
    }
    section["sourceHealthCheckedAt"] = now_iso()
    section["sourceHealth"] = sources

    historical = cache.setdefault("historicalDisturbedMining", {})
    historical["policy"] = "retain closed/abandoned mining and mining-waste footprints independently of current concession status"
    historical["officialRegister"] = "ME-ABANDONED-MINING-WASTE"
    historical["sourceHealth"] = next(s for s in sources if s["id"] == "ME-ABANDONED-MINING-WASTE")

    health = {
        "schema": "bgwf-gis-source-health-v1",
        "checkedAt": now_iso(),
        "concessions": {
            "activeRegistrySource": active,
            "cacheFeatureCount": len(features),
            "inventoryRecordCount": inventory_count,
            "baselineFeatureCount": baseline_count,
            "mguPernikFeatureCount": len(mgu_cache.get("features") or []),
            "pendingGeometryCount": pending_count,
            "disturbedMiningFeatureCount": disturbed_count,
            "abandonedMiningWasteInventoryCount": abandoned_count,
            "cacheMode": "normal" if features else "metadata-only",
            "sources": sources,
        },
        "policy": {
            "primary": "data.egov.bg",
            "secondary": "National Concession Register",
            "geometryCrossCheck": "MGU Pernik",
            "tertiary": "Ministry of Energy",
            "browserUsesRepositoryBaseline": True,
            "preserveLastKnownGoodOnSourceFailure": True,
        },
    }

    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    HEALTH_PATH.write_text(json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for s in sources:
        status = "OK" if s["ok"] else "FAIL"
        print(f"{status:4} {s['id']}: {s.get('error','')}")
    print(f"Active registry source: {active}")
    print(f"Repository concession inventory: {inventory_count}")
    print(f"Repository concession polygons preserved: {baseline_count}")
    print(f"Pending concession geometries: {pending_count}")
    print(f"Archived disturbed/mining polygons: {disturbed_count}")
    print(f"Official abandoned/mining-waste inventory: {abandoned_count}")

if __name__ == "__main__":
    main()
