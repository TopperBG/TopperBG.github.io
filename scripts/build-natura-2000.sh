#!/usr/bin/env bash
set -euo pipefail

service="https://natura2000.egov.bg/arcgis/rest/services/OpenData/ProtectedSitesOpenData_Feature/FeatureServer"
index_file="${1:-data/natura-2000-bg-v1.json}"
output_dir="$(dirname "$index_file")"
base_name="$(basename "$index_file" .json)"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

fetch_layer() {
  local layer_id="$1"
  local target="$2"
  curl --fail --location --retry 3 --max-time 180 --silent --show-error \
    "${service}/${layer_id}/query?where=1%3D1&outFields=SiteCode%2CSiteNameBG%2CSiteType%2CSiteArea&returnGeometry=true&outSR=4326&geometryPrecision=5&maxAllowableOffset=0.0003&f=geojson" \
    --output "$target"
}

fetch_layer 11 "$work_dir/spa.geojson"
fetch_layer 12 "$work_dir/habitats.geojson"

jq --compact-output --slurp '
  {
    type: "FeatureCollection",
    name: "Natura 2000 Bulgaria",
    metadata: {
      source: "МОСВ — Национална информационна система Натура 2000",
      sourceUrl: "https://natura2000.egov.bg/",
      arcgisService: "https://natura2000.egov.bg/arcgis/rest/services/OpenData/ProtectedSitesOpenData_Feature/FeatureServer",
      retrievedAt: (now | strftime("%Y-%m-%dT%H:%M:%SZ")),
      geometryCrs: "EPSG:4326",
      simplification: "ArcGIS maxAllowableOffset=0.0003 degrees; geometryPrecision=5",
      layers: {spa: 11, habitats: 12}
    },
    features: (
      ([.[0].features[] | .properties.naturaClass = "spa"])
      + ([.[1].features[] | .properties.naturaClass = "habitats"])
    )
  }
' "$work_dir/spa.geojson" "$work_dir/habitats.geojson" > "$work_dir/all.geojson"

jq -e '
  .type == "FeatureCollection"
  and ([.features[] | select(.properties.naturaClass == "spa")] | length == 120)
  and ([.features[] | select(.properties.naturaClass == "habitats")] | length == 233)
' "$work_dir/all.geojson" >/dev/null

mkdir -p "$output_dir"
files=()
part_size=30
feature_count="$(jq '.features | length' "$work_dir/all.geojson")"
for ((start=0,part=1; start<feature_count; start+=part_size,part++)); do
  target="${output_dir}/${base_name}-part-${part}.geojson"
  jq --compact-output --argjson start "$start" --argjson size "$part_size" \
    '{type:"FeatureCollection",features:.features[$start:($start+$size)]}' \
    "$work_dir/all.geojson" > "$target"
  files+=("$(basename "$target")")
done

jq --compact-output \
  --arg schema "bgwf-natura-2000-index-v1" \
  --arg source "МОСВ — Национална информационна система Натура 2000" \
  --arg sourceUrl "https://natura2000.egov.bg/" \
  --arg retrievedAt "$(jq -r '.metadata.retrievedAt' "$work_dir/all.geojson")" \
  --argjson featureCount "$feature_count" \
  --argjson files "$(printf '%s\n' "${files[@]}" | jq -R . | jq -s .)" \
  -n '{schema:$schema,source:$source,sourceUrl:$sourceUrl,retrievedAt:$retrievedAt,featureCount:$featureCount,files:$files}' \
  > "$index_file"

printf 'Wrote %s + %s parts (%s features)\n' "$index_file" "${#files[@]}" "$feature_count"
