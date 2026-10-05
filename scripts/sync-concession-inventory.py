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
ARCHIVE_INDEX_PATH = ARCHIVE / "index-v1.json"
INVENTORY_PATH = DATA / "concession-inventory-v1.json"
ABANDONED_INVENTORY_PATH = DATA / "abandoned-mining-waste-inventory-v1.json"
CURATED_SOURCE_PATH = DATA / "concession-boundaries-official-source-v2.json"
INDUSTRIAL_CACHE_PATH = DATA / "industrial-zones-cache-v1.json"

ME_XLS = "https://www.me.government.bg/uploads/manager/source/NGS/koncesii_public.xls"
ME_PAGE = "https://www.me.government.bg/bg/themes/koncesii-za-dobiv-735-1613.html"
ME_ABANDONED = "https://www.me.government.bg/bg/themes/spisak-na-zakritite-vklyuchitelno-i-na-izostavenite-saorajeniya-za-minni-otpadaci-2158-1615.html"
ME_ABANDONED_XLS = "https://www.me.government.bg/files/useruploads/files/prk/old_mining_sites_2020.xls"
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


def load_archive_index() -> dict:
    if not ARCHIVE_INDEX_PATH.exists():
        return {"schema": "bgwf-concession-source-archive-v1", "sources": {}}
    try:
        data = json.loads(ARCHIVE_INDEX_PATH.read_text(encoding="utf-8"))
        if data.get("schema") == "bgwf-concession-source-archive-v1":
            return data
    except Exception:
        pass
    return {"schema": "bgwf-concession-source-archive-v1", "sources": {}}


def archive_snapshot(source_id: str, url: str, raw: bytes, extension: str, current_name: str) -> dict:
    """Keep both a stable current copy and an immutable content-addressed copy."""
    digest = sha256(raw)
    checked = now_iso()
    atomic_write(ARCHIVE / current_name, raw)

    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", source_id).strip("-").lower()
    snapshot_dir = ARCHIVE / "snapshots" / safe_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_rel = pathlib.Path("snapshots") / safe_id / f"{digest}.{extension.lstrip('.')}"
    snapshot_abs = ARCHIVE / snapshot_rel
    if not snapshot_abs.exists():
        atomic_write(snapshot_abs, raw)

    index = load_archive_index()
    sources = index.setdefault("sources", {})
    entry = sources.setdefault(source_id, {
        "id": source_id,
        "url": url,
        "current": current_name,
        "snapshots": [],
    })
    entry["url"] = url
    entry["current"] = current_name
    entry["latestSha256"] = digest
    entry["latestBytes"] = len(raw)
    entry["lastCheckedAt"] = checked
    known = {item.get("sha256") for item in entry.get("snapshots") or []}
    if digest not in known:
        entry.setdefault("snapshots", []).append({
            "sha256": digest,
            "bytes": len(raw),
            "firstSeenAt": checked,
            "path": str(snapshot_rel).replace("\\", "/"),
        })
    index["generatedAt"] = checked
    ARCHIVE_INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "sha256": digest,
        "bytes": len(raw),
        "archiveCurrent": f"source-archive/concessions/{current_name}",
        "archiveSnapshot": f"source-archive/concessions/{str(snapshot_rel).replace(chr(92), '/')}",
    }


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
        "sourceRowNo": find_any(row, [["no по ред"], ["номер по ред"], ["пореден"]]),
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
    counts = {}
    for rec in all_records:
        cid = norm(rec.get("concessionId"))
        if cid:
            counts[cid] = counts.get(cid, 0) + 1
    collisions = {cid: count for cid, count in counts.items() if count > 1}
    for rec in all_records:
        cid = norm(rec.get("concessionId"))
        if cid and cid in collisions:
            row_no = norm(rec.get("sourceRowNo")) or hashlib.sha1(json.dumps(rec.get("raw") or {}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:8]
            rec["id"] = f"{cid}#row-{row_no}"
            rec["concessionIdCollision"] = True
            rec["concessionIdCollisionCount"] = collisions[cid]
    return all_records, {"sheets": sheet_meta, "duplicateConcessionIds": collisions}


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


def curated_records() -> tuple[list[dict], list[dict]]:
    if not CURATED_SOURCE_PATH.exists():
        return [], []
    data = json.loads(CURATED_SOURCE_PATH.read_text(encoding="utf-8"))
    records = []
    groups = []
    for r in data.get("records") or []:
        item = {
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
        }
        if item["concessionId"]:
            records.append(item)
        else:
            groups.append(item)
    return records, groups


def enrich_preserve_rows(base: list[dict], additions: list[dict]) -> list[dict]:
    """Enrich official rows without collapsing duplicate concession IDs."""
    result = [dict(r) for r in base]
    by_cid: dict[str, list[int]] = {}
    for i, rec in enumerate(result):
        cid = norm(rec.get("concessionId"))
        if cid:
            by_cid.setdefault(cid, []).append(i)

    for add in additions:
        cid = norm(add.get("concessionId"))
        matches = by_cid.get(cid, []) if cid else []
        if matches:
            for idx in matches:
                old = result[idx]
                old.setdefault("sources", [old.get("source")])
                if add.get("source") and add["source"] not in old["sources"]:
                    old["sources"].append(add["source"])
                for field in ("geometrySourceStatus", "officialSource", "areaDka"):
                    if old.get(field) in (None, "") and add.get(field) not in (None, ""):
                        old[field] = add[field]
        else:
            result.append(dict(add))
            if cid:
                by_cid.setdefault(cid, []).append(len(result)-1)
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


def parse_abandoned_xls(raw: bytes) -> tuple[list[dict], dict]:
    """Parse the ME closed/abandoned mining-waste workbook.

    The published workbook uses a multi-row visual heading rather than one
    conventional machine-readable header row. When semantic header detection
    is weak, use the stable eight-column layout visible in the official file:
    operator/owner, facility name, facility type, start year, closure year,
    area, volume, location.
    """
    book = xlrd.open_workbook(file_contents=raw)
    result = []
    sheet_meta = []
    hints = ("съоръж", "обект", "наимен", "община", "област", "местонах", "отпад", "оператор", "собствен", "рудник", "мина")

    def looks_like_data_row(values: list[str]) -> bool:
        if len(values) < 8:
            return False
        if not (values[0] and values[1] and values[2]):
            return False
        return bool(re.fullmatch(r"(?:18|19|20)\d{2}", values[3] or "")) and bool(
            re.fullmatch(r"(?:18|19|20)\d{2}", values[4] or "")
        )

    positional_headers = [
        "operator_or_owner",
        "facility_name",
        "facility_type",
        "operation_start_year",
        "closure_year",
        "area_m2",
        "volume_m3",
        "location",
    ]

    for sheet in book.sheets():
        rows = [[norm(sheet.cell_value(r, col)) for col in range(sheet.ncols)] for r in range(sheet.nrows)]
        if not rows:
            continue

        def score(row):
            blob = " | ".join(text_key(v) for v in row)
            return sum(1 for h in hints if h in blob)

        candidates = [(score(row), i, row) for i, row in enumerate(rows[:60])]
        sc, header_i, header = max(candidates, default=(0, 0, []))
        positional_start = next((i for i, row in enumerate(rows[:100]) if looks_like_data_row(row)), None)
        use_positional = positional_start is not None and sc < 2

        if use_positional:
            headers = positional_headers + [f"column_{i+1}" for i in range(len(positional_headers), sheet.ncols)]
            data_start = positional_start
            header_row_report = None
        else:
            seen = {}
            headers = []
            for i, value in enumerate(header):
                base = slug_header(value, i)
                seen[base] = seen.get(base, 0) + 1
                headers.append(base if seen[base] == 1 else f"{base} [{seen[base]}]")
            data_start = header_i + 1
            header_row_report = header_i + 1

        count = 0
        for zero_index, values in enumerate(rows[data_start:], start=data_start):
            if not any(values):
                continue
            row_index = zero_index + 1
            row = {headers[i]: values[i] for i in range(min(len(headers), len(values))) if values[i]}
            if not row:
                continue

            if use_positional:
                name = norm(row.get("facility_name"))
                location = norm(row.get("location")) or None
                operator = norm(row.get("operator_or_owner")) or None
                facility_type = norm(row.get("facility_type")) or None
                operation_start = norm(row.get("operation_start_year")) or None
                closure_year = norm(row.get("closure_year")) or None
                area_m2 = parse_number(norm(row.get("area_m2")))
                volume_m3 = parse_number(norm(row.get("volume_m3")))
                municipality = None
                province = None
            else:
                name = find_any(row, [["наимен"], ["съоръж"], ["обект"], ["рудник"], ["мина"]])
                municipality = find_any(row, [["община"]])
                province = find_any(row, [["област"]])
                location = find_any(row, [["местонах"], ["населен"]])
                operator = find_any(row, [["оператор"], ["собствен"]])
                facility_type = find_any(row, [["вид"], ["тип"], ["съоръж"]])
                operation_start = find_any(row, [["начало"], ["въвежд"]])
                closure_year = find_any(row, [["закрив"], ["прекрат"]])
                area_m2 = None
                volume_m3 = None

            blob = " ".join(row.values()).strip()
            if not (name or municipality or province or location) and len(blob) < 20:
                continue

            stable_basis = "|".join([
                norm(name), norm(location), norm(facility_type), norm(operator),
                norm(operation_start), norm(closure_year),
            ])
            if not stable_basis.strip("|"):
                stable_basis = f"{sheet.name}|{row_index}|{json.dumps(row, ensure_ascii=False, sort_keys=True)}"
            rid = hashlib.sha1(stable_basis.encode("utf-8")).hexdigest()[:16]

            result.append({
                "id": f"ME-ABANDONED-{rid}",
                "name": name or None,
                "facilityType": facility_type,
                "municipality": municipality,
                "province": province,
                "location": location,
                "operatorOrOwner": operator,
                "operationStartYear": operation_start,
                "closureYear": closure_year,
                "areaM2": area_m2,
                "volumeM3": volume_m3,
                "status": "official-closed-or-abandoned-mining-waste",
                "sourceSheet": sheet.name,
                "sourceRowNo": row_index,
                "source": "ME-ABANDONED-MINING-WASTE-XLS",
                "raw": row,
            })
            count += 1

        sheet_meta.append({
            "name": sheet.name,
            "rows": sheet.nrows,
            "headerRow": header_row_report,
            "headerScore": sc,
            "parserMode": "official-positional-8-column" if use_positional else "semantic-header",
            "dataStartRow": data_start + 1,
            "records": count,
            "headers": headers,
        })
    return result, {"sheets": sheet_meta}



def existing_abandoned_inventory() -> dict:
    if not ABANDONED_INVENTORY_PATH.exists():
        return {}
    try:
        return json.loads(ABANDONED_INVENTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


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
        archive_meta = archive_snapshot("ME-CONCESSIONS-XLS", ME_XLS, raw, "xls", "koncesii_public.xls")
        candidate_records = records
        official_refresh_records = records
        source_runs.append({
            "id": "ME-CONCESSIONS-XLS", "ok": True, "url": ME_XLS,
            "bytes": len(raw), "sha256": sha256(raw), "records": len(records), **archive_meta, **meta,
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
        archive_meta = archive_snapshot("NKR-EXPORT", NKR_EXPORT, raw, "tsv", "nkr-concessions-export.tsv")
        source_runs.append({
            "id": "NKR", "ok": True, "url": NKR_EXPORT,
            "bytes": len(raw), "sha256": sha256(raw), "records": len(nkr_records), **archive_meta,
        })
        if nkr_records:
            official_refresh_records = enrich_preserve_rows(official_refresh_records, nkr_records)
            candidate_records = enrich_preserve_rows(candidate_records, nkr_records)
    except Exception as exc:
        source_runs.append({"id": "NKR", "ok": False, "url": NKR_EXPORT, "error": str(exc)})

    # 3) Archive Ministry pages used for provenance and historical disturbed-land work.
    for sid, url, filename in [
        ("ME-CONCESSIONS-PAGE", ME_PAGE, "me-concessions-page.html"),
        ("ME-ABANDONED-MINING-WASTE", ME_ABANDONED, "me-abandoned-mining-waste.html"),
    ]:
        try:
            raw = fetch(url)
            archive_meta = archive_snapshot(sid, url, raw, "html", filename)
            source_runs.append({
                "id": sid, "ok": True, "url": url, "bytes": len(raw), "sha256": sha256(raw), **archive_meta,
            })
        except Exception as exc:
            source_runs.append({"id": sid, "ok": False, "url": url, "error": str(exc)})

    # 4) Archive and normalize the official closed/abandoned mining-waste XLS.
    abandoned_existing = existing_abandoned_inventory()
    abandoned_records = []
    abandoned_mode = "empty-bootstrap"
    abandoned_source = {"id": "ME-ABANDONED-MINING-WASTE-XLS", "ok": False, "url": ME_ABANDONED_XLS}
    try:
        raw = fetch(ME_ABANDONED_XLS)
        if len(raw) < 500:
            raise RuntimeError(f"unexpectedly small abandoned-sites XLS ({len(raw)} bytes)")
        parsed, meta = parse_abandoned_xls(raw)
        if not parsed:
            raise RuntimeError("abandoned-sites XLS produced no records")
        archive_meta = archive_snapshot("ME-ABANDONED-MINING-WASTE-XLS", ME_ABANDONED_XLS, raw, "xls", "old_mining_sites_2020.xls")
        abandoned_records = parsed
        abandoned_mode = "refreshed"
        abandoned_source = {
            "id": "ME-ABANDONED-MINING-WASTE-XLS", "ok": True, "url": ME_ABANDONED_XLS,
            "bytes": len(raw), "sha256": sha256(raw), "records": len(parsed), **archive_meta, **meta,
        }
    except Exception as exc:
        abandoned_records = abandoned_existing.get("records") or []
        abandoned_mode = "last-known-good-preserved" if abandoned_records else "empty-bootstrap"
        abandoned_source["error"] = str(exc)

    abandoned_payload = {
        "schema": "bgwf-abandoned-mining-waste-inventory-v1",
        "generatedAt": now_iso(),
        "mode": abandoned_mode,
        "scope": "Official Ministry of Energy list of closed including abandoned mining-waste facilities",
        "recordCount": len(abandoned_records),
        "runtimeDependency": False,
        "source": abandoned_source,
        "records": abandoned_records,
    }
    ABANDONED_INVENTORY_PATH.write_text(json.dumps(abandoned_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source_runs.append(abandoned_source)

    # Curated official-source records are always merged, including historical/closed cases,
    # but they do not count as proof that the national online inventory refreshed successfully.
    curated, curated_groups = curated_records()
    candidate_records = enrich_preserve_rows(candidate_records, curated)

    if len(official_refresh_records) < 50 and len(existing_records) >= 50:
        # Network/parser regression: preserve last known good inventory, while still
        # ensuring newly curated historical records are not lost.
        records = enrich_preserve_rows(existing_records, curated)
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
    collision_rows = [r for r in records if r.get("concessionIdCollision")]
    collision_ids = sorted({r.get("concessionId") for r in collision_rows if r.get("concessionId")})

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
            "duplicateConcessionIdCount": len(collision_ids),
            "duplicateConcessionRowCount": len(collision_rows),
        },
        "duplicateConcessionIds": collision_ids,
        "curatedGroups": curated_groups,
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
    print(f"Abandoned/mining-waste inventory {abandoned_mode}: {len(abandoned_records)} records.")
    for run in source_runs:
        print(("OK  " if run.get("ok") else "FAIL"), run["id"], run.get("records", ""), run.get("error", ""))


if __name__ == "__main__":
    main()
