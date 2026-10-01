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

const source = JSON.parse(fs.readFileSync(SOURCE_PATH, "utf8"));
const cache = JSON.parse(fs.readFileSync(CACHE_PATH, "utf8"));
const bgs = new BGSCoordinates();

function projectionFor(record) {
  const zone = String(record.zone_inference || "").toUpperCase();
  if (!/^K[3579]$/.test(zone)) return null;
  return projections[`BGS_1970_${zone}`] || null;
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

for (const record of source.records || []) {
  const points = record.coordinates_normalized_xy;
  const projection = projectionFor(record);

  if (!Array.isArray(points) || points.length < 3) {
    pending.push(shortPending(record, record.status || "coordinate_register_not_extracted"));
    continue;
  }
  if (!projection) {
    pending.push(shortPending(record, "coordinate_zone_not_verified"));
    continue;
  }
  if (!Number.isFinite(Number(record.official_area_dka)) || Number(record.official_area_dka) <= 0) {
    pending.push(shortPending(record, "official_area_missing"));
    continue;
  }

  let bgs2005;
  try {
    // TPS is preferred by the library for the BGS1970 grid transformation.
    bgs2005 = bgs.transformArray(points, projection, projections.BGS_2005_KK, true);
  } catch (error) {
    pending.push(shortPending(record, `transformation_failed: ${error.message}`));
    continue;
  }

  const transformedAreaDka = polygonAreaSqM(bgs2005) / 1000;
  const officialAreaDka = Number(record.official_area_dka);
  const areaErrorPct = Math.abs(transformedAreaDka - officialAreaDka) / officialAreaDka * 100;
  if (!Number.isFinite(areaErrorPct) || areaErrorPct > 2.0) {
    pending.push(shortPending(record, `area_QA_failed_${areaErrorPct.toFixed(3)}pct`));
    continue;
  }

  const ring = [];
  let badPoint = false;
  for (const point of bgs2005) {
    const geo = transformLambertToGeographic(point);
    const lat = Number(geo?.[0]);
    const lon = Number(geo?.[1]);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < 41.0 || lat > 44.5 || lon < 22.0 || lon > 29.5) {
      badPoint = true;
      break;
    }
    ring.push([Number(lon.toFixed(8)), Number(lat.toFixed(8))]);
  }
  if (badPoint || ring.length < 3) {
    pending.push(shortPending(record, "WGS84_Bulgaria_bounds_QA_failed"));
    continue;
  }
  if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) {
    ring.push([...ring[0]]);
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
      source_zone: record.zone_inference,
      source_point_count: points.length,
      source_url: sourceUrl(record),
      source_kind: "official-coordinate-register",
      geometry_status: "repository-baseline-official-register-transformed",
      transformation: "bojko108/transformations@2.0.0 BGS1970 grid -> BGS2005/CCS2005 -> WGS84",
      transformation_note: "Grid model derived from AGCC official-engine control points; informational map geometry. Verify with official BGSTrans for legal/cadastral use.",
    },
    geometry: {
      type: "Polygon",
      coordinates: [ring],
    },
  });
}

features.sort((a, b) =>
  String(a.properties.concession_id).localeCompare(String(b.properties.concession_id), "bg")
);
pending.sort((a, b) => String(a.concessionId || a.id).localeCompare(String(b.concessionId || b.id), "bg"));

const section = cache.concessions ||= {};
const previousFeatures = Array.isArray(section.features) ? section.features : [];
const changed = !sameFeatureSet(previousFeatures, features) || !sameFeatureSet(section.pending || [], pending);

section.schema = "bgwf-industry-concessions-cache-v1";
section.geometryCrs = "EPSG:4326";
section.featureCount = features.length;
section.features = features;
section.pending = pending;
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
  pendingOfficialRecords: pending.length,
  note: "Legal concession boundary and developed/disturbed footprint are separate geometries.",
};

if (changed) {
  const now = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  section.generatedAt = now;
  cache.lastUpdatedSections ||= {};
  cache.lastUpdatedSections.concessionsBaseline = now;
  fs.writeFileSync(CACHE_PATH, JSON.stringify(cache, null, 2) + "\n", "utf8");
  console.log(`Updated baseline: ${features.length} published polygon(s), ${pending.length} pending record(s).`);
} else {
  console.log(`Baseline unchanged: ${features.length} published polygon(s), ${pending.length} pending record(s).`);
}
