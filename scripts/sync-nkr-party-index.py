#!/usr/bin/env python3
"""Build a repository-owned NKR party index.

Purpose:
- map concession IDs/names to stable NKR GUIDs;
- archive the current HTML index pages in the repository;
- make later coordinate-document harvesting independent of NKR search;
- preserve last-known-good output when NKR is unavailable.

This job is a refresh input only. The browser never calls NKR.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "map" / "data"
OUT = DATA / "nkr-party-index-v1.json"
INVENTORY = DATA / "concession-inventory-v1.json"
ARCHIVE_DIR = DATA / "source-archive" / "concessions" / "nkr-index"

BASE = "https://nkr.government.bg"
LANDING = "/Concessions"
SEARCH = "/Concessions/Search"
SLEEP = 1.0
MAX_PAGES = 30
UA = "EnergoKarta-Bulgaria-NKR-index/1.0 (+https://topperbg.github.io/map/)"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(value) -> str:
    s = re.sub(r"\s+", " ", str(value or "")).strip()
    return s.replace("–", "-").replace("—", "-")


def norm_id(value) -> str:
    return re.sub(r"\s+", "", norm(value)).upper()


CID_PATTERNS = [
    re.compile(r"\bD-\s*\d{4,8}\b", re.I),
    re.compile(r"\bO-\s*\d{4,8}\b", re.I),
    re.compile(r"\b\d{3}-\d{2,6}\b"),
    re.compile(r"\bИМВБ-\s*\d{4}\b", re.I),
]


def concession_id_from_values(values: list[str]) -> str | None:
    blob = " | ".join(values)
    for pattern in CID_PATTERNS:
        m = pattern.search(blob)
        if m:
            return norm(m.group(0))
    return None


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.7",
    })
    r = s.get(BASE + LANDING, timeout=60)
    r.raise_for_status()
    time.sleep(SLEEP)
    s.headers.update({"X-Requested-With": "XMLHttpRequest"})
    return s


def parse_page(html: str) -> tuple[list[dict], int | None]:
    soup = BeautifulSoup(html, "lxml")
    total = None
    m = re.search(r"Общо:\s*(\d+)", soup.get_text(" "))
    if m:
        total = int(m.group(1))

    table = soup.find("table", class_="tableResults") or soup.find("table")
    if not table:
        return [], total

    headers = [norm(th.get_text(" ", strip=True)) for th in table.select("thead th")]
    records = []
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        guid = None
        values = []
        columns = {}
        for i, td in enumerate(tds):
            classes = td.get("class") or []
            value = norm(td.get_text(" ", strip=True))
            if "IdColumn" in classes and "hiddenColumn" in classes:
                guid = value
                continue
            if "hiddenColumn" in classes:
                continue
            key = headers[i] if i < len(headers) and headers[i] else f"col_{i}"
            columns[key] = value or None
            if value:
                values.append(value)
        if not guid or not re.fullmatch(r"[0-9a-f-]{36}", guid, re.I):
            continue
        records.append({
            "guid": guid.lower(),
            "concessionId": concession_id_from_values(values),
            "columns": columns,
            "searchText": " | ".join(values),
        })
    return records, total


def existing() -> dict:
    if not OUT.exists():
        return {}
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> None:
    old = existing()
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8")) if INVENTORY.exists() else {"records": []}
    inventory_by_cid = {}
    for rec in inventory.get("records") or []:
        cid = norm_id(rec.get("concessionId"))
        if cid:
            inventory_by_cid.setdefault(cid, []).append(rec)

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    page_hashes = []
    total = None
    error = None

    try:
        s = make_session()
        seen = set()
        for page in range(1, MAX_PAGES + 1):
            url = f"{BASE}{SEARCH}?page={page}&rowsPerPage=100"
            r = s.get(url, timeout=90)
            r.raise_for_status()
            html = r.text
            rows, reported_total = parse_page(html)
            if total is None and reported_total:
                total = reported_total
            if not rows:
                break

            page_path = ARCHIVE_DIR / f"page-{page:03d}.html"
            page_path.write_text(html, encoding="utf-8")
            page_hashes.append({
                "page": page,
                "sha256": hashlib.sha256(r.content).hexdigest(),
                "bytes": len(r.content),
                "path": str(page_path.relative_to(DATA)).replace("\\", "/"),
            })

            new_count = 0
            for rec in rows:
                if rec["guid"] in seen:
                    continue
                seen.add(rec["guid"])
                cid = norm_id(rec.get("concessionId"))
                matches = inventory_by_cid.get(cid, []) if cid else []
                rec["partyUrl"] = f"{BASE}/ConcessionaireProcedures/ConcessionaireProcedureInfo/{rec['guid']}"
                rec["inventoryMatches"] = [m.get("id") for m in matches]
                rec["inventoryMatchCount"] = len(matches)
                records.append(rec)
                new_count += 1

            if new_count == 0:
                break
            if total and len(seen) >= total:
                break
            time.sleep(SLEEP)

        if len(records) < 100:
            raise RuntimeError(f"NKR HTML index produced only {len(records)} records")

    except Exception as exc:
        error = str(exc)
        if (old.get("records") or []):
            records = old["records"]
            page_hashes = old.get("pageSnapshots") or []
            total = old.get("reportedTotal")
            mode = "last-known-good-preserved"
        else:
            records = []
            mode = "empty-bootstrap"
    else:
        mode = "refreshed"

    matched = sum(1 for r in records if r.get("inventoryMatchCount") == 1)
    ambiguous = sum(1 for r in records if (r.get("inventoryMatchCount") or 0) > 1)
    by_guid = {r["guid"]: r for r in records}

    # Persist an inventory-centric lookup so downstream builders do not need
    # to search the large NKR table again.
    inventory_lookup = {}
    for rec in records:
        for inventory_id in rec.get("inventoryMatches") or []:
            inventory_lookup.setdefault(inventory_id, []).append({
                "guid": rec["guid"],
                "concessionId": rec.get("concessionId"),
                "partyUrl": rec.get("partyUrl"),
                "searchText": rec.get("searchText"),
            })

    payload = {
        "schema": "bgwf-nkr-party-index-v1",
        "generatedAt": now_iso(),
        "mode": mode,
        "runtimeDependency": False,
        "source": {
            "url": BASE + LANDING,
            "reportedTotal": total,
            "error": error,
        },
        "recordCount": len(records),
        "inventoryRecordCount": len(inventory.get("records") or []),
        "stats": {
            "singleInventoryMatch": matched,
            "ambiguousInventoryMatch": ambiguous,
            "inventoryIdsWithNkrParty": len(inventory_lookup),
        },
        "pageSnapshots": page_hashes,
        "inventoryLookup": inventory_lookup,
        "records": records,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"NKR party index {mode}: {len(records)} records; inventory matches={len(inventory_lookup)}; error={error or '-'}")


if __name__ == "__main__":
    main()
