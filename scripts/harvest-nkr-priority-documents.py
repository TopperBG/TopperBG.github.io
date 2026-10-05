#!/usr/bin/env python3
"""Incrementally archive NKR party pages for pending concession geometries.

The repository-owned NKR index maps inventory records to NKR GUIDs. This stage
archives the actual party HTML and extracts Preview/File links, so coordinate
registers can be harvested/extracted later without repeating registry search.

Bootstrap: up to 150 previously unarchived parties.
Steady state: refresh up to 40 oldest archived parties per run.
Browser runtime never depends on these requests.
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
PENDING = DATA / "pending-concessions-v1.json"
INDEX = DATA / "nkr-party-index-v1.json"
OUT = DATA / "nkr-party-documents-v1.json"
ARCHIVE = DATA / "source-archive" / "concessions" / "nkr-parties"

BASE = "https://nkr.government.bg"
LANDING = "/Concessions"
BOOTSTRAP_BATCH = 150
REFRESH_BATCH = 40
SLEEP = 1.0
UA = "EnergoKarta-Bulgaria-NKR-parties/1.0 (+https://topperbg.github.io/map/)"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str | None) -> str:
    return value or "1970-01-01T00:00:00Z"


def existing() -> dict:
    if not OUT.exists():
        return {}
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.7",
    })
    r = s.get(BASE + LANDING, timeout=60)
    r.raise_for_status()
    time.sleep(SLEEP)
    return s


def extract_links(html: str) -> tuple[list[dict], list[dict]]:
    soup = BeautifulSoup(html, "lxml")
    files = {}
    previews = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        title = re.sub(r"\s+", " ", a.get_text(" ")).strip() or None
        absolute = urljoin(BASE, href)
        if "/File/Download" in href or "/Content/Download" in href:
            files[href] = {"href": href, "url": absolute, "title": title}
        elif re.search(r"/Preview/[A-Za-z]+/[0-9a-f-]{36}", href, re.I):
            previews[href] = {"href": href, "url": absolute, "title": title}
    return list(files.values()), list(previews.values())


def main() -> None:
    pending = json.loads(PENDING.read_text(encoding="utf-8")) if PENDING.exists() else {"pending": []}
    index = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {"records": []}
    old = existing()
    old_parties = old.get("parties") or {}

    index_by_guid = {r.get("guid"): r for r in index.get("records") or [] if r.get("guid")}
    wanted = {}
    for item in pending.get("pending") or []:
        for party in item.get("nkrParties") or []:
            guid = party.get("guid")
            if not guid:
                continue
            rec = wanted.setdefault(guid, {
                "guid": guid,
                "partyUrl": party.get("partyUrl") or f"{BASE}/ConcessionaireProcedures/ConcessionaireProcedureInfo/{guid}",
                "inventoryIds": [],
                "concessionIds": [],
                "names": [],
                "priority": int(item.get("priority") or 4),
            })
            rec["priority"] = min(rec["priority"], int(item.get("priority") or 4))
            if item.get("inventoryId") and item["inventoryId"] not in rec["inventoryIds"]:
                rec["inventoryIds"].append(item["inventoryId"])
            cid = item.get("concessionId")
            if cid and cid not in rec["concessionIds"]:
                rec["concessionIds"].append(cid)
            if item.get("name") and item["name"] not in rec["names"]:
                rec["names"].append(item["name"])

    new_guids = [g for g in wanted if g not in old_parties or old_parties[g].get("status") != "ok"]
    new_guids.sort(key=lambda g: (wanted[g]["priority"], wanted[g]["names"][0] if wanted[g]["names"] else g))

    if new_guids:
        selected = new_guids[:BOOTSTRAP_BATCH]
        mode = "bootstrap-new"
    else:
        selected = sorted(
            wanted,
            key=lambda g: parse_time((old_parties.get(g) or {}).get("checkedAt"))
        )[:REFRESH_BATCH]
        mode = "refresh-oldest"

    ARCHIVE.mkdir(parents=True, exist_ok=True)
    parties = dict(old_parties)
    errors = []
    checked = now_iso()

    try:
        session = make_session()
    except Exception as exc:
        session = None
        errors.append({"stage": "session", "error": str(exc)})

    for pos, guid in enumerate(selected, 1):
        meta = wanted[guid]
        previous = parties.get(guid) or {}
        if session is None:
            break
        try:
            r = session.get(meta["partyUrl"], timeout=90)
            r.raise_for_status()
            html = r.text
            file_links, preview_links = extract_links(html)
            gdir = ARCHIVE / guid
            gdir.mkdir(parents=True, exist_ok=True)
            party_path = gdir / "partida.html"
            party_path.write_text(html, encoding="utf-8")
            digest = hashlib.sha256(r.content).hexdigest()
            parties[guid] = {
                **meta,
                "status": "ok",
                "checkedAt": now_iso(),
                "sha256": digest,
                "bytes": len(r.content),
                "archivePath": str(party_path.relative_to(DATA)).replace("\\", "/"),
                "fileLinkCount": len(file_links),
                "previewLinkCount": len(preview_links),
                "fileLinks": file_links,
                "previewLinks": preview_links,
                "indexRecord": index_by_guid.get(guid),
            }
        except Exception as exc:
            errors.append({"guid": guid, "url": meta["partyUrl"], "error": str(exc)})
            parties[guid] = {
                **previous,
                **meta,
                "status": previous.get("status") or "error",
                "lastErrorAt": now_iso(),
                "lastError": str(exc),
            }
        if pos < len(selected):
            time.sleep(SLEEP)

    ok_count = sum(1 for x in parties.values() if x.get("status") == "ok")
    linked_files = sum(int(x.get("fileLinkCount") or 0) for x in parties.values() if x.get("status") == "ok")
    coordinate_candidates = []
    keyword = re.compile(r"координ|регист|границ|скиц|площ|прилож", re.I)
    for party in parties.values():
        for link in party.get("fileLinks") or []:
            if keyword.search(link.get("title") or ""):
                coordinate_candidates.append({
                    "guid": party.get("guid"),
                    "inventoryIds": party.get("inventoryIds") or [],
                    **link,
                })

    payload = {
        "schema": "bgwf-nkr-party-documents-v1",
        "generatedAt": checked,
        "mode": mode,
        "runtimeDependency": False,
        "pendingWithNkrParty": len(wanted),
        "partyCount": len(parties),
        "archivedOkCount": ok_count,
        "totalFileLinks": linked_files,
        "coordinateCandidateLinkCount": len(coordinate_candidates),
        "batchSelected": len(selected),
        "errors": errors,
        "coordinateCandidateLinks": coordinate_candidates,
        "parties": parties,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"NKR party documents {mode}: selected={len(selected)}; archived={ok_count}/{len(wanted)}; "
        f"fileLinks={linked_files}; coordinateCandidates={len(coordinate_candidates)}; errors={len(errors)}"
    )


if __name__ == "__main__":
    main()
