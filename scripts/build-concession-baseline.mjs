#!/usr/bin/env node
/**
 * Build repository-owned concession baseline geometry from official coordinate
 * registers already curated in concession-boundaries-official-source-v2.json.
 *
 * Publication gate:
 * - complete numeric register;
 * - known BGS1970 zone;
 * - reproducible BGS1970 -> BGS2005 transformation;
 * - transformed planar area within 2% of the official concession area;
 * - resulting WGS84 ring falls inside Bulgaria.
 *
 * This is map-grade geometry, not a substitute for BGSTrans/legal cadastral work.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  BGSCoordinates,
  projections,
  transformLambertToGeographic,
} from "transformations/src/main.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const SOURCE_PATH = path.join(ROOT, "map", "data", "concession-boundaries-official-source-v2.json");
const CACHE_PATH = path.join(ROOT, "map", "data", "industrial-zones-cache-v1.json");
const INVENTORY_PATH = path.join(ROOT, "map", "data", "concession-inventory-v1.json");
const BASELINE_PATH = path.join(ROOT, "map", "data", "official-concessions-baseline.geojson");
const PENDING_PATH = path.join(ROOT, "map", "data", "pending-concessions-v1.json");
const NKR_PARTY_INDEX_PATH = path.join(ROOT, "map", "data", "nkr-party-index-v1.json");
const EXTRACTED_REGISTERS_PATH = path.join(ROOT, "map", "data", "coordinate-registers-staging-v1.json");

const source = JSON.parse(fs.readFileSync(SOURCE_PATH, "utf8"));
const cache = JSON.parse(fs.readFileSync(CACHE_PATH, "utf8"));
const inventory = fs.existsSync(INVENTORY_PATH)
  ? JSON.parse(fs.readFileSync(INVENTORY_PATH, "utf8"))
  : { records: [] };
const nkrPartyIndex = fs.existsSync(NKR_PARTY_INDEX_PATH)
  ? JSON.parse(fs.readFileSync(NKR_PARTY_INDEX_PATH, "utf8"))
  : { inventoryLookup: {} };
const nkrInventoryLookup = nkrPartyIndex.inventoryLookup || {};
const inventoryByConcession = new Map(
  (inventory.records || []).map(r => [String(r.concessionId || r.id || ""), r])
);
const extractedRegisters = fs.existsSync(EXTRACTED_REGISTERS_PATH)
  ? JSON.parse(fs.readFileSync(EXTRACTED_REGISTERS_PATH, "utf8"))
  : { registers: [] };

// transformations@2.0.0 resolves its binary grids from process.cwd() rather
// than from the package directory. Run the transformation phase from the
// package root while keeping all project file paths absolute.
const TRANSFORM_PACKAGE_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.resolve("transformations/src/main.js"))),
  ".."
);
process.chdir(TRANSFORM_PACKAGE_ROOT);
const bgs = new BGSCoordinates();

function projectionFor(record) {
  const zone = String(record.zone_inference || "").toUpperCase();
  if (!/^K[3579]$/.test(zone)) return null;
  return projections[`BGS_1970_${zone}`] || null;
}

function coordinateMode(record) {
  const sourceCrs = String(record.source_coordinate_system || record.sourceCoordinateSystem || "").toUpperCase();
  if (sourceCrs.includes("2005")) return "BGS2005";
  if (sourceCrs.includes("1970")) return "BGS1970";
  return null;
}

function normalizeCoordinatePairs(pairs, orderValue) {
  if (!Array.isArray(pairs)) return null;
  const order = String(orderValue || "");
  if (/X\s*\(N\).*Y\s*\(E\)/i.test(order) || /X.*Y/i.test(order)) {
    return pairs.map(([a,b])=>[Number(a),Number(b)]);
  }
  if (/Y\s*\(E\).*X\s*\(N\)/i.test(order) || /Y.*X/i.test(order)) {
    return pairs.map(([a,b])=>[Number(b),Number(a)]);
  }
  return null;
}

function normalizedPointsFromRecord(record) {
  if (Array.isArray(record.coordinates_normalized_xy)) return record.coordinates_normalized_xy;
  return normalizeCoordinatePairs(
    record.coordinatesRaw,
    record.sourceCoordinateOrder || record.normalized_coordinate_order
  );
}

function normalizedContoursFromRecord(record) {
  if (!Array.isArray(record.contoursRaw) || record.contoursRaw.length < 2) return null;
  const order = record.sourceCoordinateOrder || record.normalized_coordinate_order;
  const rings = record.contoursRaw
    .map(c=>normalizeCoordinatePairs(c.coordinatesRaw, order))
    .filter(r=>Array.isArray(r)&&r.length>=3);
  return rings.length === record.contoursRaw.length ? rings : null;
}

function polygonAreaSqM(points) {
  let twice = 0;
  for (let i = 0; i < points.length; i++) {
    const [n1, e1] = points[i];
    const [n2, e2] = points[(i + 1) % points.length];
    // Cartesian shoelace; N acts as y, E as x.
    twice += e1 * n2 - e2 * n1;
  }
  return Math.abs(twice) / 2;
}

function sameFeatureSet(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function sourceUrl(record) {
  const s = record.official_source || {};
  return s.current_info_url || s.concession_url || s.url || s.decision_url || "";
}

function shortPending(record, reason) {
  return {
    id: record.id,
    concessionId: record.concession_registry || null,
    name: record.name,
    officialAreaDka: record.official_area_dka ?? null,
    sourceCrs: record.source_coordinate_system || null,
    sourcePoints: record.point_count ?? record.source_point_count ?? record.sourcePointsExpected ?? null,
    status: reason || record.status || "pending",
    sourceUrl: sourceUrl(record) || null,
  };
}

const features = [];
const pending = [];

const sourceRecords = [...(source.records || [])];
const curatedIds = new Set(sourceRecords.map(r=>String(r.concession_registry||"")).filter(Boolean));
for (const reg of extractedRegisters.registers || []) {
  if (!reg?.publicationReady) continue;
  const cid=String(reg.concessionId||"");
  const existing=sourceRecords.find(r=>String(r.concession_registry||"")===cid && Array.isArray(r.coordinates_normalized_xy) && r.coordinates_normalized_xy.length>=3);
  if (existing) continue;
  const inv = inventoryByConcession.get(cid);
  sourceRecords.push({
    id: reg.curatedId || `NKR-${cid}`,
    concession_registry: cid,
    name: reg.name || inv?.name || cid,
    resource: inv?.resource || null,
    municipality: inv?.municipality || null,
    province: inv?.province || null,
    source_coordinate_system: reg.sourceCoordinateSystem || reg.dominantCrsClass,
    zone_inference: reg.sourceZone || null,
    sourceCoordinateOrder: reg.sourceCoordinateOrder || null,
    coordinatesRaw: reg.coordinatesRaw,
    contoursRaw: Array.isArray(reg.contoursRaw) ? reg.contoursRaw : null,
    geometryStructure: reg.geometryStructure || "Polygon",
    point_count: reg.extractedPointCount,
    official_area_dka: reg.officialAreaDka,
    official_source: {
      publisher: "Национален концесионен регистър",
      url: reg.sourceUrl,
      attachment_sha256: reg.sha256,
      archive_path: reg.archivePath,
    },
    status: "extracted_official_attachment__publication_gate_passed",
  });
}

for (const record of sourceRecords) {
  const singlePoints = normalizedPointsFromRecord(record);
  const contourPoints = normalizedContoursFromRecord(record);
  const sourceRings = contourPoints || (Array.isArray(singlePoints) && singlePoints.length >= 3 ? [singlePoints] : []);
  const mode = coordinateMode(record);
  const projection = mode==="BGS1970" ? projectionFor(record) : null;

  if (!sourceRings.length) {
    pending.push(shortPending(record, record.status || "coordinate_register_not_extracted"));
    continue;
  }
  if (!mode) {
    pending.push(shortPending(record, "coordinate_system_not_verified"));
    continue;
  }
  if (mode==="BGS1970" && !projection) {
    pending.push(shortPending(record, "coordinate_zone_not_verified"));
    continue;
  }
  if (!Number.isFinite(Number(record.official_area_dka)) || Number(record.official_area_dka) <= 0) {
    pending.push(shortPending(record, "official_area_missing"));
    continue;
  }

  let bgs2005Rings;
  try {
    bgs2005Rings = sourceRings.map(points => {
      if (mode==="BGS1970") {
        // TPS is preferred by the library for the BGS1970 grid transformation.
        return bgs.transformArray(points, projection, projections.BGS_2005_KK, true);
      }
      // Official BGS2005 cadastral coordinates are already in CCS2005.
      return points.map(([x,y])=>[Number(x),Number(y)]);
    });
  } catch (error) {
    pending.push(shortPending(record, `transformation_failed: ${error.message}`));
    continue;
  }

  const transformedAreaDka = bgs2005Rings.reduce((sum,ring)=>sum+polygonAreaSqM(ring),0) / 1000;
  const officialAreaDka = Number(record.official_area_dka);
  const areaErrorPct = Math.abs(transformedAreaDka - officialAreaDka) / officialAreaDka * 100;
  if (!Number.isFinite(areaErrorPct) || areaErrorPct > 2.0) {
    pending.push(shortPending(record, `area_QA_failed_${areaErrorPct.toFixed(3)}pct`));
    continue;
  }

  const wgsRings = [];
  let badPoint = false;
  for (const sourceRing of bgs2005Rings) {
    const ring = [];
    for (const point of sourceRing) {
      const geo = transformLambertToGeographic(point);
      const lat = Number(geo?.[0]);
      const lon = Number(geo?.[1]);
      if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < 41.0 || lat > 44.5 || lon < 22.0 || lon > 29.5) {
        badPoint = true;
        break;
      }
      ring.push([Number(lon.toFixed(8)), Number(lat.toFixed(8))]);
    }
    if (badPoint || ring.length < 3) break;
    if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) {
      ring.push([...ring[0]]);
    }
    wgsRings.push(ring);
  }
  if (badPoint || wgsRings.length !== bgs2005Rings.length) {
    pending.push(shortPending(record, "WGS84_Bulgaria_bounds_QA_failed"));
    continue;
  }

  features.push({
    type: "Feature",
    properties: {
      concession_id: record.concession_registry || record.id,
      name: record.name,
      official_area_dka: officialAreaDka,
      transformed_area_dka: Number(transformedAreaDka.toFixed(3)),
      area_qa_error_pct: Number(areaErrorPct.toFixed(4)),
      source_coordinate_system: record.source_coordinate_system,
      source_zone: record.zone_inference || null,
      source_point_count: sourceRings.reduce((n,r)=>n+r.length,0),
      source_contour_count: sourceRings.length,
      resource: record.resource || null,
      municipality: record.municipality || null,
      province: record.province || null,
      source_url: sourceUrl(record),
      source_attachment_sha256: record.official_source?.attachment_sha256 || null,
      source_archive_path: record.official_source?.archive_path || null,
      source_kind: "official-coordinate-register",
      geometry_status: "repository-baseline-official-register-transformed",
      transformation: mode==="BGS1970"
        ? "bojko108/transformations@2.0.0 BGS1970 grid -> BGS2005/CCS2005 -> WGS84"
        : "official BGS2005/CCS2005 cadastral coordinates -> WGS84",
      transformation_note: mode==="BGS1970"
        ? "Grid model derived from AGCC official-engine control points; informational map geometry. Verify with official BGSTrans for legal/cadastral use."
        : "Official BGS2005 source coordinates; map conversion to WGS84 is informational and does not replace the legal coordinate register.",
    },
    geometry: wgsRings.length > 1 ? {
      type: "MultiPolygon",
      coordinates: wgsRings.map(ring=>[ring]),
    } : {
      type: "Polygon",
      coordinates: [wgsRings[0]],
    },
  });
}

features.sort((a, b) =>
  String(a.properties.concession_id).localeCompare(String(b.properties.concession_id), "bg")
);

const publishedIds = new Set(features.map(f => String(f.properties.concession_id || "")));
const pendingById = new Map();
const curatedGroupsPending = [];
const curatedPendingByCid = new Map();

for (const item of pending) {
  const cid = String(item.concessionId || "");
  if (!cid) {
    curatedGroupsPending.push({...item, queueSource: "curated-group"});
    continue;
  }
  const key = `curated:${cid}`;
  pendingById.set(key, {...item, queueSource: "curated-official-register"});
  curatedPendingByCid.set(cid, key);
}

for (const rec of inventory.records || []) {
  const cid = String(rec.concessionId || "");
  if (!cid) continue;
  // A duplicated source ID cannot safely inherit geometry by ID alone.
  if (publishedIds.has(cid) && !rec.concessionIdCollision) continue;

  const curatedKey = !rec.concessionIdCollision ? curatedPendingByCid.get(cid) : null;
  if (curatedKey && pendingById.has(curatedKey)) {
    const current = pendingById.get(curatedKey);
    pendingById.set(curatedKey, {
      ...current,
      inventoryId: rec.id,
      inventoryStatus: rec.status ?? null,
      concessionaire: rec.concessionaire ?? null,
      resource: rec.resource ?? null,
      municipality: rec.municipality ?? null,
      province: rec.province ?? null,
      inventoryAreaDka: rec.areaDka ?? null,
      concessionIdCollision: !!rec.concessionIdCollision,
      nkrParties: nkrInventoryLookup[rec.id] || [],
    });
    continue;
  }

  const area = Number(rec.areaDka);
  const key = `inventory:${rec.id || cid}`;
  pendingById.set(key, {
    id: rec.id,
    concessionId: rec.concessionId || null,
    name: rec.name || "Концесия без нормализирано име",
    officialAreaDka: Number.isFinite(area) && area > 0 ? area : null,
    sourceCrs: null,
    sourcePoints: null,
    status: rec.concessionIdCollision
      ? "source_concession_id_collision_requires_NKR_verification"
      : "official_coordinate_register_not_archived",
    sourceUrl: null,
    queueSource: "national-inventory",
    sourceRowNo: rec.sourceRowNo ?? null,
    inventoryStatus: rec.status ?? null,
    concessionaire: rec.concessionaire ?? null,
    resource: rec.resource ?? null,
    municipality: rec.municipality ?? null,
    province: rec.province ?? null,
    concessionIdCollision: !!rec.concessionIdCollision,
    nkrParties: nkrInventoryLookup[rec.id] || [],
  });
}

const pendingQueue = [...pendingById.values()];
function queuePriority(item){
  const area=Number(item.officialAreaDka ?? item.inventoryAreaDka);
  if(Number.isFinite(area)&&area>=10000)return 1;
  if(Number.isFinite(area)&&area>=3000)return 2;
  if(Number.isFinite(area)&&area>=1000)return 3;
  if(item.queueSource==="curated-official-register")return 2;
  return 4;
}
pendingQueue.forEach(item=>item.priority=queuePriority(item));
pendingQueue.sort((a,b)=>a.priority-b.priority
  || (Number(b.officialAreaDka??b.inventoryAreaDka)||0)-(Number(a.officialAreaDka??a.inventoryAreaDka)||0)
  || String(a.name||"").localeCompare(String(b.name||""),"bg"));

const now = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
const baselinePayload = {
  type: "FeatureCollection",
  schema: "bgwf-official-concessions-baseline-v1",
  generatedAt: now,
  geometryCrs: "EPSG:4326",
  runtimeDependency: false,
  featureCount: features.length,
  inventoryRecordCount: (inventory.records||[]).length,
  extractedRegisterCount: (extractedRegisters.registers||[]).length,
  extractedPublicationReadyCount: (extractedRegisters.registers||[]).filter(x=>x.publicationReady).length,
  publicationGate: {
    officialCoordinateRegisterRequired: true,
    areaTolerancePct: 2.0,
    approximateGeometryAllowed: false,
  },
  features,
};
const pendingPayload = {
  schema: "bgwf-pending-concessions-v1",
  generatedAt: now,
  inventoryRecordCount: (inventory.records||[]).length,
  publishedGeometryCount: features.length,
  pendingCount: pendingQueue.length,
  withNkrPartyCount: pendingQueue.filter(x=>Array.isArray(x.nkrParties)&&x.nkrParties.length).length,
  curatedGroupPendingCount: curatedGroupsPending.length,
  curatedGroupsPending,
  priorityMeaning: {
    "1": "very large area (>= 10 000 dka)",
    "2": "large/curated official source",
    "3": "medium area (>= 1 000 dka)",
    "4": "remaining national inventory",
  },
  pending: pendingQueue,
};
fs.writeFileSync(BASELINE_PATH, JSON.stringify(baselinePayload, null, 2) + "\n", "utf8");
fs.writeFileSync(PENDING_PATH, JSON.stringify(pendingPayload, null, 2) + "\n", "utf8");

const section = cache.concessions ||= {};
const previousFeatures = Array.isArray(section.features) ? section.features : [];
const changed = !sameFeatureSet(previousFeatures, features)
  || !sameFeatureSet(section.pending || [], pendingQueue)
  || Number(section.coverage?.inventoryRecordCount || 0) !== Number((inventory.records||[]).length);

section.schema = "bgwf-industry-concessions-cache-v1";
section.geometryCrs = "EPSG:4326";
section.featureCount = features.length;
section.features = features;
section.pending = pendingQueue;
section.sourceDataset = "./concession-boundaries-official-source-v2.json";
section.baselineBuilder = {
  id: "official-coordinate-registers-v1",
  transformLibrary: "transformations@2.0.0",
  publicationAreaTolerancePct: 2.0,
  legalUse: false,
};
section.coverage = {
  ...(section.coverage || {}),
  scope: "national",
  baselineStatus: features.length ? "partial" : "bootstrapping",
  publishedOfficialRegisterPolygons: features.length,
  inventoryRecordCount: (inventory.records||[]).length,
  pendingOfficialRecords: pendingQueue.length,
  pendingWithNkrParty: pendingQueue.filter(x=>Array.isArray(x.nkrParties)&&x.nkrParties.length).length,
  note: "Legal concession boundary and developed/disturbed footprint are separate geometries.",
};

if (changed) {
  section.generatedAt = now;
  cache.lastUpdatedSections ||= {};
  cache.lastUpdatedSections.concessionsBaseline = now;
  fs.writeFileSync(CACHE_PATH, JSON.stringify(cache, null, 2) + "\n", "utf8");
  console.log(`Updated baseline: ${features.length} published polygon(s), ${pendingQueue.length} pending record(s), inventory ${(inventory.records||[]).length}.`);
} else {
  console.log(`Baseline unchanged: ${features.length} published polygon(s), ${pendingQueue.length} pending record(s), inventory ${(inventory.records||[]).length}.`);
}
