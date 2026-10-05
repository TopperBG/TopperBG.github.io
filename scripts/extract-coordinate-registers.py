#!/usr/bin/env python3
"""Build a repository-owned staging area of coordinate registers extracted from NKR attachments.

This stage never publishes map geometry by itself.

Publication-ready requires ALL:
- official attachment archived with sha256;
- numbered coordinate register extracted without conflicting duplicate point numbers;
- verified CRS family;
- expected point count known and exactly matched;
- official concession area known;
- for BGS1970: verified zone and coordinate order from curated metadata.

The JS baseline builder consumes only entries explicitly marked publicationReady.
"""

from __future__ import annotations

import json
import pathlib
import re
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "map" / "data"
ATTACHMENTS = DATA / "nkr-attachment-index-v1.json"
CANDIDATES = DATA / "coordinate-document-candidates-v1.json"
CURATED = DATA / "concession-boundaries-official-source-v2.json"
OUT = DATA / "coordinate-registers-staging-v1.json"


def load(path: pathlib.Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def safe_number(token: str) -> float | None:
    try:
        return float(token.replace(",", "."))
    except Exception:
        return None


def classify_pair(a: float, b: float) -> str | None:
    aa, bb = abs(a), abs(b)
    if (4.3e6 <= aa <= 5.0e6 and 8.0e6 <= bb <= 10.0e6) or (
        4.3e6 <= bb <= 5.0e6 and 8.0e6 <= aa <= 10.0e6
    ):
        return "BGS1970"
    if (4.3e6 <= aa <= 5.0e6 and 1.0e5 <= bb <= 1.2e6) or (
        4.3e6 <= bb <= 5.0e6 and 1.0e5 <= aa <= 1.2e6
    ):
        return "BGS2005"
    if (41.0 <= aa <= 44.5 and 22.0 <= bb <= 29.5) or (
        41.0 <= bb <= 44.5 and 22.0 <= aa <= 29.5
    ):
        return "WGS84"
    return None


def parse_numbered_triples(text: str) -> list[dict]:
    normalized = re.sub(r"[\x00-\x1f]+", " ", text)
    tokens = []
    for m in re.finditer(r"[-+]?\d+(?:[.,]\d+)?", normalized):
        value = safe_number(m.group(0))
        if value is not None:
            tokens.append((value, m.start()))

    rows = []
    i = 0
    while i + 2 < len(tokens):
        n = tokens[i][0]
        a = tokens[i + 1][0]
        b = tokens[i + 2][0]
        crs = classify_pair(a, b)
        if float(n).is_integer() and 1 <= n <= 10000 and crs:
            rows.append({
                "pointNo": int(n),
                "a": a,
                "b": b,
                "crsClass": crs,
            })
            i += 3
        else:
            i += 1
    return rows


def dedupe(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    kept = {}
    conflicts = []
    order = []
    for row in rows:
        key = (row["pointNo"], row["crsClass"])
        old = kept.get(key)
        if old is None:
            kept[key] = row
            order.append(key)
            continue
        if abs(old["a"] - row["a"]) > 0.01 or abs(old["b"] - row["b"]) > 0.01:
            conflicts.append({"pointNo": row["pointNo"], "first": old, "other": row})
    return [kept[k] for k in order], conflicts


def contiguous_ranges(numbers: list[int]) -> list[str]:
    nums = sorted(set(numbers))
    if not nums:
        return []
    ranges = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    ranges.append(str(start) if start == prev else f"{start}-{prev}")
    return ranges


def curated_by_cid(payload: dict) -> dict[str, dict]:
    out = {}
    for rec in payload.get("records") or []:
        cid = rec.get("concession_registry")
        if cid:
            out[cid] = rec
    return out


def expected_point_count(rec: dict | None) -> int | None:
    if not rec:
        return None
    if rec.get("point_count"):
        return int(rec["point_count"])
    # Do not add deposit and additional-area registers here: those may represent
    # separate geometries rather than one polygon.
    return None


def coordinate_order(rec: dict | None, crs: str) -> str | None:
    if not rec:
        return None
    explicit = rec.get("normalized_coordinate_order")
    if explicit:
        return explicit
    # BGS2005 cadastral registers conventionally expose X/N then Y/E in our
    # official source record; require the curated record to say BGS2005.
    source_crs = str(rec.get("source_coordinate_system") or "").upper()
    if crs == "BGS2005" and "2005" in source_crs:
        return "X(N), Y(E)"
    return None


def parse_bg_number(value: str) -> float | None:
    s = value.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def document_metadata(text: str) -> dict:
    """Extract only explicit concession-geometry metadata from the same official document."""
    compact = re.sub(r"\s+", " ", text)
    declared_crs = None
    if re.search(r"БГС\s*2005", compact, re.I):
        declared_crs = "BGS2005"
    elif re.search(r"Координатна\s+система[^.\n]{0,50}1970|КС\s*1970", compact, re.I):
        declared_crs = "BGS1970"

    axis_order = None
    if re.search(r"X\s*\(\s*север\s*\).*?Y\s*\(\s*изток\s*\)", compact, re.I):
        axis_order = "X(N), Y(E)"
    elif re.search(r"Y\s*\(\s*изток\s*\).*?X\s*\(\s*север\s*\)", compact, re.I):
        axis_order = "Y(E), X(N)"

    area = None
    area_patterns = [
        r"Определя\s+концесионна\s+площ(?:\s+с\s+(?:общ\s+)?размер|\s+с\s+площ|\s+в\s+размер)?\s*[:\-]?\s*([0-9][0-9\s\u00a0.,]*)\s*дка",
        r"концесионна\s+площ\s+(?:с\s+)?(?:общ\s+)?размер\s*([0-9][0-9\s\u00a0.,]*)\s*дка",
    ]
    for pattern in area_patterns:
        m = re.search(pattern, compact, re.I)
        if m:
            area = parse_bg_number(m.group(1))
            if area and area > 0:
                break

    ranges = []
    for m in re.finditer(r"от\s*№?\s*1\s*до\s*№?\s*(\d{1,4})", compact, re.I):
        n = int(m.group(1))
        if n >= 3:
            ranges.append(n)

    # Prefer the range explicitly tied to "Определя концесионна площ". Later
    # paragraphs may contain sub-deposit ranges that are not the concession
    # boundary and must not make an otherwise unambiguous main ring ambiguous.
    expected = None
    main_clause = re.search(r"Определя\s+концесионна\s+площ.{0,700}", compact, re.I)
    if main_clause:
        m = re.search(r"от\s*№?\s*1\s*до\s*№?\s*(\d{1,4})", main_clause.group(0), re.I)
        if m and int(m.group(1)) >= 3:
            expected = int(m.group(1))
    if expected is None and len(set(ranges)) == 1:
        expected = ranges[0]

    return {
        "declaredCrs": declared_crs,
        "axisOrder": axis_order,
        "officialAreaDka": area,
        "singleRangeExpectedPointCount": expected,
        "rangeEndsFound": sorted(set(ranges)),
    }


def main() -> None:
    attachments = load(ATTACHMENTS, {"files": {}})
    candidates = load(CANDIDATES, {"candidates": []})
    curated_payload = load(CURATED, {"records": []})
    curated = curated_by_cid(curated_payload)

    candidate_file_ids = {c.get("fileId") for c in candidates.get("candidates") or []}
    registers = []

    for file_id, meta in (attachments.get("files") or {}).items():
        if meta.get("status") != "ok" or file_id not in candidate_file_ids:
            continue
        text_path = meta.get("textPath")
        if not text_path:
            continue
        path = DATA / text_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        doc_meta = document_metadata(text)
        raw_rows = parse_numbered_triples(text)
        rows, conflicts = dedupe(raw_rows)
        if not rows:
            continue

        by_class = Counter(r["crsClass"] for r in rows)
        numeric_dominant = by_class.most_common(1)[0][0]
        dominant = doc_meta.get("declaredCrs") or numeric_dominant
        if doc_meta.get("declaredCrs") in ("BGS1970", "BGS2005"):
            dominant_rows = [r for r in rows if r["crsClass"] in ("BGS1970", "BGS2005")]
        else:
            dominant_rows = [r for r in rows if r["crsClass"] == dominant]
        point_numbers = [r["pointNo"] for r in dominant_rows]

        for cid in meta.get("concessionIds") or []:
            rec = curated.get(cid)
            expected = expected_point_count(rec) or doc_meta.get("singleRangeExpectedPointCount")
            area = (rec.get("official_area_dka") if rec else None) or doc_meta.get("officialAreaDka")
            zone = rec.get("zone_inference") if rec else None
            order = coordinate_order(rec, dominant) or doc_meta.get("axisOrder")
            unique_count = len({r["pointNo"] for r in dominant_rows})
            exact = expected is not None and unique_count == expected
            full_range = expected is not None and set(point_numbers) == set(range(1, expected + 1))
            source_crs = str(rec.get("source_coordinate_system") or "") if rec else ""

            reasons = []
            if conflicts:
                reasons.append("conflicting_duplicate_point_numbers")
            if expected is None:
                reasons.append("expected_point_count_unknown")
            elif not exact:
                reasons.append(f"expected_{expected}_got_{unique_count}")
            elif not full_range:
                reasons.append("point_numbers_not_complete_1_to_N")
            if area in (None, ""):
                reasons.append("official_area_missing")
            if dominant == "BGS1970":
                if not zone:
                    reasons.append("BGS1970_zone_unverified")
                if not order:
                    reasons.append("coordinate_order_unverified")
            elif dominant == "BGS2005":
                if not order:
                    reasons.append("coordinate_order_unverified")
            elif dominant == "WGS84":
                if not order:
                    order = "lat/lon-or-lon/lat_needs_bounds_resolution"
                    reasons.append("WGS84_axis_order_unverified")
            else:
                reasons.append("unsupported_crs")

            publication_ready = not reasons and dominant in ("BGS1970", "BGS2005")

            registers.append({
                "concessionId": cid,
                "curatedId": rec.get("id") if rec else None,
                "name": rec.get("name") if rec else None,
                "fileId": file_id,
                "sha256": meta.get("sha256"),
                "archivePath": meta.get("archivePath"),
                "textPath": text_path,
                "sourceUrl": meta.get("url"),
                "filename": meta.get("filename"),
                "extractor": meta.get("extractor"),
                "coordinateParserVersion": meta.get("coordinateParserVersion"),
                "dominantCrsClass": dominant,
                "numericDominantCrsClass": numeric_dominant,
                "declaredCrsFromDocument": doc_meta.get("declaredCrs"),
                "axisOrderFromDocument": doc_meta.get("axisOrder"),
                "officialAreaDkaFromDocument": doc_meta.get("officialAreaDka"),
                "rangeEndsFoundInDocument": doc_meta.get("rangeEndsFound"),
                "sourceCoordinateSystem": source_crs or doc_meta.get("declaredCrs") or dominant,
                "sourceCoordinateOrder": order,
                "sourceZone": zone,
                "officialAreaDka": area,
                "expectedPointCount": expected,
                "extractedPointCount": unique_count,
                "pointNumberRanges": contiguous_ranges(point_numbers),
                "conflictCount": len(conflicts),
                "conflicts": conflicts[:20],
                "publicationReady": publication_ready,
                "publicationBlockers": reasons,
                "coordinatesRaw": [[r["a"], r["b"]] for r in sorted(dominant_rows, key=lambda x: x["pointNo"])],
                "points": [
                    {"pointNo": r["pointNo"], "a": r["a"], "b": r["b"]}
                    for r in sorted(dominant_rows, key=lambda x: x["pointNo"])
                ],
            })

    registers.sort(key=lambda r: (
        0 if r["publicationReady"] else 1,
        r["concessionId"],
        -(r["extractedPointCount"] or 0),
        r["fileId"],
    ))

    payload = {
        "schema": "bgwf-coordinate-registers-staging-v1",
        "generatedFrom": {
            "attachments": "./nkr-attachment-index-v1.json",
            "candidates": "./coordinate-document-candidates-v1.json",
            "curated": "./concession-boundaries-official-source-v2.json",
        },
        "runtimeDependency": False,
        "registerCount": len(registers),
        "publicationReadyCount": sum(1 for r in registers if r["publicationReady"]),
        "rules": [
            "Extraction is evidence staging, not legal geometry publication.",
            "Exact expected numbered register and official area are mandatory.",
            "BGS1970 also requires verified zone and coordinate order.",
            "Baseline builder independently checks transformed area and Bulgaria bounds.",
        ],
        "registers": registers,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"Coordinate-register staging: {len(registers)} register(s), "
        f"publication-ready={payload['publicationReadyCount']}."
    )
    for r in registers[:15]:
        print(
            r["concessionId"], r["dominantCrsClass"], r["extractedPointCount"],
            r["pointNumberRanges"], "READY" if r["publicationReady"] else ",".join(r["publicationBlockers"][:3])
        )


if __name__ == "__main__":
    main()
