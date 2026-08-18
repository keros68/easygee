# Workflow Profiles

## Contents

1. Source routing
2. Geometry and tiling profiles
3. Prompt construction
4. Cleaning and QA
5. GEE export guidance

## 1. Source routing

- **Local georeferenced raster**: run `prepare_imagery.py local`; preserve the
  input raster as the spatial authority.
- **Local JPG/PNG**: accept only with explicit `--crs` and `--bounds`, or ask
  the user to georeference it in QGIS.
- **GEE image/collection**: run EasyGEE's interaction and method routers,
  resolve the project without hard-coding it, verify the dataset, then run
  `prepare_imagery.py gee` for a small local export. Use an EasyGEE batch
  export plan for large AOIs.
- **Visible web-map screenshot**: use only for exploratory visual annotation;
  do not export CRS vectors unless a separate georeferenced raster defines the
  same pixel grid.

## 2. Geometry and tiling profiles

| Target | Preferred geometry | Initial tile/overlap | QA focus |
| --- | --- | --- | --- |
| Field parcels or water bodies | polygon | 768–1536 px / 10–20% | shared edges, holes, partial border objects |
| Vehicles or vessels | bbox or polygon | 512 px / 20–30% | tiny targets, shadows, duplicates |
| Individual tree crowns | polygon | 512–1024 px / 20–50% | touching crowns, crown groups, shadows |
| Buildings | polygon | 512–1024 px / 15–30% | roof shadows, orthogonality, merged blocks |
| Roads or rivers | line or polygon | 768–1536 px / 20–30% | continuity across tiles, width ambiguity |
| Generic sparse targets | point or bbox | 512–1024 px / 20% | count stability and edge duplicates |

Use `tile_imagery.py` when downsampling the whole scene would make the target
smaller than roughly 8–15 preview pixels. Keep overlap large enough to show a
complete object near tile boundaries.

## 3. Prompt construction

Run `prompt_template.py` and customize:

- target definition and class names;
- inclusion/exclusion rules;
- geometry type;
- treatment of truncated, occluded or touching targets;
- confidence policy.

Prefer structured JSON. Use a bright single-color overlay only when the model
cannot return coordinates. When using overlays, instruct the model to preserve
the original image extent, aspect ratio and pixels, and treat color extraction
as a fallback digitization path.

## 4. Cleaning and QA

Keep generic defaults conservative: repair validity and remove duplicates, but
do not impose circle/size rules across domains. Apply optional thresholds only
when the user defines meaningful units and target expectations:

- minimum/maximum projected area;
- circularity for circular targets;
- simplification tolerance in CRS units;
- confidence threshold;
- overlap IoU for tile deduplication.

Inspect the boundary line layer over the source image in QGIS. Separate model
misses, class ambiguity, coordinate misalignment and post-processing artifacts.
Do not hide discarded objects; retain raw JSON and report filter counts.

## 5. GEE export guidance

Require collection/image id, AOI, bands, time range, reducer, scale, CRS and
scale factor. Apply dataset-specific quality masks only when band semantics are
known. `prepare_imagery.py` includes an SCL mask for Sentinel-2 SR collections;
other datasets need an explicit QA decision.

For small AOIs, use the geemap local download path. For requests that exceed
the Earth Engine direct-download limit, run EasyGEE's `plan_gee_export.py` and
use `ee.batch.Export.image.*`; do not repeatedly shrink or silently coarsen the
requested product without telling the user.
