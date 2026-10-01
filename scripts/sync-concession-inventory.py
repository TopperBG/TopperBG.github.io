#!/usr/bin/env python3
"""Build and preserve a repository-owned national concession inventory.

The online registries are update inputs, not runtime dependencies.

Outputs:
  map/data/concession-inventory-v1.json
  map/data/source-archive/concessions/koncesii_public.xls
  map/data/source-archive/concessions/nkr-concessions-export.tsv
  map/data/source-archive/concessions/me-abandoned-mining-waste.html

Rules:
- never replace a non-empty local inventory with an empty/failed download;
- archive every successfully downloaded official snapshot;
- normalize enough fields for matching/QA, while preserving every source cell;
- merge curated historical/source-register records already stored in the repo.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import pathlib
import re
import shutil
import unicodedata
import urllib.error
import urllib.request

try:
    import xlrd
except ImportError as exc:
    raise SystemExit("xlrd is required: pip install xlrd==2.0.1") from exc

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "map" / "data"
ARCHIVE = DATA / "source-archive" / "concessions"
INVENTORY_PATH = DATA / "concession-inventory-v1.json"
CURATED_SOURCE_PATH = DATA / "concession-boundaries-official-source-v2.json"
INDUSTRIAL_CACHE_PATH = DATA / "industrial-zones-cache-v1.json"

ME_XLS = "https://www.me.government.bg/uploads/manager/source/NGS/koncesii_public.xls"
ME_PAGE = "https://www.me.government.bg/bg/themes/koncesii-za-dobiv-735-1613.html"
ME_ABANDONED = "https://www.me.government.bg/bg/themes/spisak-na-zakritite-vklyuchitelno-i-na-izostavenite-saorajeniya-za-minni-otpadaci-2158-1615.html"
NKR_EXPORT = "https://nkr.government.bg/Concessions/Export?file=csv"
USER_AGENT = "EnergoKarta-Bulgaria-inventory/1.0 (+https://topperbg.github.io/map/)"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    s = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", " ", s).strip()


def slug_header(value, index: int) -> str:
    s = norm(value)
    if not s:
        return f"column_{index+1}"
    return s


def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "bg,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def text_key(s: str) -> str:
    return norm(s).lower().replace("№", "номер")


def find_field(row: dict, patterns: list[str]) -> str | None:
    for key, value in row.items():
        k = text_key(key)
        if all(token in k for token in patterns):
            v = norm(value)
            if v:
                return v
    return None


def find_any(row: dict, pattern_sets: list[list[str]]) -> str | None:
    for patterns in pattern_sets:
        value = find_field(row, patterns)
        if value:
            return value
    return None


def parse_number(value: str | None) -> float | None:
    if not value:
        return None
    m = re.search(r"-?\d[\d\s\u00a0.,]*", value)
    if not m:
        return None
    s = m.group(0).replace("\u00a0", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def normalize_area_dka(row: dict) -> float | None:
    for key, value in row.items():
        k = text_key(key)
        if "площ" not in k:
            continue
        n = parse_number(norm(value))
        if n is None or n <= 0:
            continue
        if re.search(r"\bha\b|хектар", k):
            return n * 10.0
        if "кв." in k and "м" in k:
            return n / 1000.0
        return n
    return None


def stable_id(source: str, row: dict) -> str:
    cid = find_any(row, [
        ["партид"],
        ["идентификац"],
        ["номер", "концес"],
        ["№", "концес"],
    ])
    if cid:
        return cid
    deposit = find_any(row, [["находище"], ["обект"]]) or ""
    operator = find_any(row, [["концесионер"], ["оператор"]]) or ""
    digest = hashlib.sha1(f"{source}|{deposit}|{operator}|{json.dumps(row, ensure_ascii=False, sort_keys=True)}".encode("utf-8")).hexdigest()[:14]
    return f"{source}-{digest}"


def normalized_record(source: str, row: dict, *, default_status: str | None = None) -> dict:
    cid = find_any(row, [["партид"], ["идентификац"], ["номер", "концес"], ["№", "концес"]])
    deposit = find_any(row, [["находище"], ["обект", "концес"], ["име", "находище"]])
    operator = find_any(row, [["концесионер"], ["оператор"]])
    mineral = find_any(row, [["подземн", "богат"], ["полезн", "изкоп"], ["суровин"], ["ресурс"]])
    municipality = find_any(row, [["община"]])
    province = find_any(row, [["област"]])
    status = find_any(row, [["статус"], ["състояние"]]) or default_status
    contract_date = find_any(row, [["дата", "договор"], ["сключ", "договор"]])
    end_date = find_any(row, [["край"], ["изтич"], ["срок", "до"]])
    area = normalize_area_dka(row)
    return {
        "id": stable_id(source, row),
        "concessionId": cid,
        "name": deposit,
        "concessionaire": operator,
        "resource": mineral,
        "municipality": municipality,
        "province": province,
        "status": status,
        "contractDate": contract_date,
        "endDate": end_date,
        "areaDka": area,
        "source": source,
        "raw": row,
    }


HEADER_HINTS = (
    "находище", "концесионер", "партид", "идентификац", "подземни", "площ",
    "община", "област", "договор", "срок"
)


def header_score(values: list[str]) -> int:
    blob = " | ".join(text_key(v) for v in values)
    return sum(1 for hint in HEADER_HINTS if hint in blob)


def parse_me_xls(raw: bytes) -> tuple[list[dict], dict]:
    book = xlrd.open_workbook(file_contents=raw)
    all_records: list[dict] = []
    sheet_meta = []
    for sheet in book.sheets():
        rows = [[norm(sheet.cell_value(r, c)) for c in range(sheet.ncols)] for r in range(sheet.nrows)]
        if not rows:
            continue
        candidates = [(header_score(row), i, row) for i, row in enumerate(rows[:40])]
        score, header_i, header = max(candidates, default=(0, 0, []))
        if score < 2:
            sheet_meta.append({"name": sheet.name, "rows": sheet.nrows, "headerDetected": False})
            continue
        seen: dict[str, int] = {}
        headers = []
        for i, value in enumerate(header):
            base = slug_header(value, i)
            count = seen.get(base, 0) + 1
            seen[base] = count
            headers.append(base if count == 1 else f"{base} [{count}]")
        count = 0
        for values in rows[header_i + 1:]:
            if not any(values):
                continue
            row = {headers[i]: values[i] for i in range(min(len(headers), len(values))) if values[i]}
            if len(row) < 2:
                continue
            rec = normalized_record("ME-CONCESSIONS-XLS", row, default_status="active")
            # Reject headings/notes accidentally parsed as records.
            if not (rec["concessionId"] or rec["name"] or rec["concessionaire"]):
                continue
            all_records.append(rec)
            count += 1
        sheet_meta.append({
            "name": sheet.name,
            "rows": sheet.nrows,
            "headerRow": header_i + 1,
            "headerScore": score,
            "records": count,
            "headers": headers,
        })
    return all_records, {"sheets": sheet_meta}


def parse_delimited(text: str, source: str) -> list[dict]:
    sample = text[:10000]
    delimiter = "\t"
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="\t;,|")
        delimiter = dialect.delimiter
    except csv.Error:
        pass
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if len(rows) < 2:
        return []
    header_candidates = [(header_score([norm(v) for v in row]), i, row) for i, row in enumerate(rows[:30])]
    score, header_i, header = max(header_candidates, default=(0, 0, []))
    if score < 1:
        header_i, header = 0, rows[0]
    headers = [slug_header(v, i) for i, v in enumerate(header)]
    records = []
    for values in rows[header_i + 1:]:
        clean = [norm(v) for v in values]
        if not any(clean):
            continue
        row = {headers[i]: clean[i] for i in range(min(len(headers), len(clean))) if clean[i]}
        rec = normalized_record(source, row)
        blob = " ".join(text_key(v) for v in row.values())
        if source == "NKR" and not ("подзем" in blob or "добив" in blob or "находище" in blob):
            # NKR export may contain other concession types. Keep only likely mining rows.
            continue
        records.append(rec)
    return records


def curated_records() -> list[dict]:
    if not CURATED_SOURCE_PATH.exists():
        return []
    data = json.loads(CURATED_SOURCE_PATH.read_text(encoding="utf-8"))
    result = []
    for r in data.get("records") or []:
        result.append({
            "id": r.get("concession_registry") or r.get("id"),
            "concessionId": r.get("concession_registry"),
            "name": r.get("name"),
            "concessionaire": None,
            "resource": None,
            "municipality": None,
            "province": None,
            "status": "curated-official-source-register",
            "contractDate": None,
            "endDate": None,
            "areaDka": r.get("official_area_dka"),
            "source": "REPOSITORY-CURATED-OFFICIAL",
            "geometrySourceStatus": r.get("status"),
            "officialSource": r.get("official_source") or {},
            "raw": None,
        })
    return result


def merge_records(base: list[dict], additions: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    order: list[str] = []

    def key_for(rec: dict) -> str:
        cid = norm(rec.get("concessionId"))
        return f"cid:{cid}" if cid else f"id:{rec.get('id')}"

    for rec in base + additions:
        key = key_for(rec)
        if key not in by_key:
            by_key[key] = dict(rec)
            by_key[key]["sources"] = [rec.get("source")]
            order.append(key)
            continue
        old = by_key[key]
        for field in ("name", "concessionaire", "resource", "municipality", "province", "status",
                      "contractDate", "endDate", "areaDka", "geometrySourceStatus", "officialSource"):
            if (old.get(field) is None or old.get(field) == "") and rec.get(field) not in (None, ""):
                old[field] = rec.get(field)
        source_name = rec.get("source")
        if source_name and source_name not in old["sources"]:
            old["sources"].append(source_name)
        if rec.get("raw"):
            old.setdefault("sourceRows", {})[source_name] = rec["raw"]
    return [by_key[k] for k in order]


def existing_inventory() -> dict:
    if not INVENTORY_PATH.exists():
        return {}
    try:
        return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    existing = existing_inventory()
    existing_records = existing.get("records") or []
    source_runs = []
    candidate_records: list[dict] = []
    official_refresh_records: list[dict] = []

    # 1) Ministry of Energy XLS: most reliable bootstrap source from GitHub-hosted runners.
    try:
        raw = fetch(ME_XLS)
        if len(raw) < 1000:
            raise RuntimeError(f"unexpectedly small XLS ({len(raw)} bytes)")
        records, meta = parse_me_xls(raw)
        if len(records) < 50:
            raise RuntimeError(f"XLS parse produced only {len(records)} records")
        atomic_write(ARCHIVE / "koncesii_public.xls", raw)
        candidate_records = records
        official_refresh_records = records
        source_runs.append({
            "id": "ME-CONCESSIONS-XLS", "ok": True, "url": ME_XLS,
            "bytes": len(raw), "sha256": sha256(raw), "records": len(records), **meta,
        })
    except Exception as exc:
        source_runs.append({"id": "ME-CONCESSIONS-XLS", "ok": False, "url": ME_XLS, "error": str(exc)})

    # 2) NKR export: richer fallback/verification when available. Archive raw export.
    try:
        raw = fetch(NKR_EXPORT)
        text = raw.decode("cp1251", errors="replace")
        nkr_records = parse_delimited(text, "NKR")
        if len(text.splitlines()) < 50:
            raise RuntimeError("NKR export unexpectedly small")
        atomic_write(ARCHIVE / "nkr-concessions-export.tsv", raw)
        source_runs.append({
            "id": "NKR", "ok": True, "url": NKR_EXPORT,
            "bytes": len(raw), "sha256": sha256(raw), "records": len(nkr_records),
        })
        if nkr_records:
            official_refresh_records = merge_records(official_refresh_records, nkr_records)
            candidate_records = merge_records(candidate_records, nkr_records)
    except Exception as exc:
        source_runs.append({"id": "NKR", "ok": False, "url": NKR_EXPORT, "error": str(exc)})

    # 3) Archive Ministry pages used for provenance and historical disturbed-land work.
    for sid, url, filename in [
        ("ME-CONCESSIONS-PAGE", ME_PAGE, "me-concessions-page.html"),
        ("ME-ABANDONED-MINING-WASTE", ME_ABANDONED, "me-abandoned-mining-waste.html"),
    ]:
        try:
            raw = fetch(url)
            atomic_write(ARCHIVE / filename, raw)
            source_runs.append({
                "id": sid, "ok": True, "url": url, "bytes": len(raw), "sha256": sha256(raw),
            })
        except Exception as exc:
            source_runs.append({"id": sid, "ok": False, "url": url, "error": str(exc)})

    # Curated official-source records are always merged, including historical/closed cases,
    # but they do not count as proof that the national online inventory refreshed successfully.
    curated = curated_records()
    candidate_records = merge_records(candidate_records, curated)

    if len(official_refresh_records) < 50 and len(existing_records) >= 50:
        # Network/parser regression: preserve last known good inventory, while still
        # ensuring newly curated historical records are not lost.
        records = merge_records(existing_records, curated)
        mode = "last-known-good-preserved"
    elif len(official_refresh_records) >= 50:
        records = candidate_records
        mode = "refreshed"
    elif candidate_records:
        records = candidate_records
        mode = "bootstrap-partial"
    else:
        records = existing_records
        mode = "last-known-good-preserved" if existing_records else "empty-bootstrap"

    records.sort(key=lambda r: (
        norm(r.get("province")),
        norm(r.get("municipality")),
        norm(r.get("name")),
        norm(r.get("concessionId")),
    ))

    active = sum(1 for r in records if "active" in text_key(r.get("status") or ""))
    with_id = sum(1 for r in records if r.get("concessionId"))
    with_area = sum(1 for r in records if isinstance(r.get("areaDka"), (int, float)) and r["areaDka"] > 0)

    payload = {
        "schema": "bgwf-concession-inventory-v1",
        "generatedAt": now_iso(),
        "mode": mode,
        "scope": "Bulgaria; mining/extraction concessions plus curated historical official records",
        "recordCount": len(records),
        "stats": {
            "activeStatusRecords": active,
            "withConcessionId": with_id,
            "withAreaDka": with_area,
        },
        "runtimeDependency": False,
        "updatePolicy": {
            "onlineSourcesAreRefreshInputsOnly": True,
            "neverReplaceNonEmptyInventoryWithFailedOrEmptyFetch": True,
            "rawOfficialSnapshotsArchivedInRepository": True,
        },
        "sourceRuns": source_runs,
        "records": records,
    }
    INVENTORY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Inventory {mode}: {len(records)} records; IDs={with_id}; area={with_area}.")
    for run in source_runs:
        print(("OK  " if run.get("ok") else "FAIL"), run["id"], run.get("records", ""), run.get("error", ""))


if __name__ == "__main__":
    main()
