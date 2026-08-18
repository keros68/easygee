---
name: multimodal-geo-vector
description: Use when Codex needs to detect, count, outline, segment, or localize visible targets in local or Google Earth Engine remote-sensing imagery and deliver CRS-aware GeoPackage or GeoJSON vectors, including fields, vehicles, vessels, tree crowns, buildings, roads, water bodies, or other objects.
---

# Multimodal Geo Vector

Turn visual-model annotations into reproducible GIS artifacts. Keep the
reference raster—not the preview or model—as the authority for CRS, transform,
extent and pixel grid.

## Infer safe defaults from short requests

- Treat a named site or center coordinate as an AOI seed. Choose an initial
  extent appropriate to the target scale, expand it when candidates touch the
  edge, and record the radius/bounds. Do not hide a fixed default radius in the
  script. Interpret “all” as all visible candidates inside the recorded AOI;
  expand until candidates no longer touch the outer review margin or document
  the explicit coverage limit. Ask only when whole-site versus sample-area
  coverage materially changes the result or cost.
- Treat `GeoPackage`/`.gpkg` as a local projected-vector deliverable. Preserve
  the source CRS when suitable; otherwise use a local projected/UTM CRS and
  record it.
- Infer ordinary bands, preview size, tiling and overlap from the source and
  target. Do not require the user to restate the workflow in a long prompt.
- Record the mapping unit before inference: individual object, continuous
  same-target region, or enclosing site. Visibly separable roads, buildings,
  water, bare gaps and other excluded surfaces become polygon holes when they
  lie inside a continuous region. Ask only if another interpretation would
  materially change the output.
- Never infer CRS or bounds from visual appearance.

## Route the request

1. Classify the source:
   - local georeferenced raster → `local_first`;
   - GEE image/collection followed by local vectorization → `hybrid`;
   - unreferenced JPG/PNG → require explicit CRS and bounds or georeferencing;
   - screenshot without a matching georeferenced raster → visual exploration
     only; do not promise CRS vectors.
2. For a GEE source, also use the sibling `easygee` skill. Run its interaction
   and geospatial-method routers, resolve the project from user settings, verify
   the dataset, and plan a batch export when a local download is too large.
3. Read [references/workflow-profiles.md](references/workflow-profiles.md) for
   target-specific geometry, tiling, prompt and QA choices.
4. Read [references/annotation-contract.md](references/annotation-contract.md)
   before accepting model JSON, merging tiles, or diagnosing CRS misalignment.

## Check readiness

Run:

```powershell
python scripts/check_environment.py --mode local
```

Use `--mode gee` when Earth Engine access is required. Do not install or
authenticate before checking. Never print or store GEE credentials. For GEE
authorization/project issues, defer to the sibling EasyGEE auth workflow.

## Prepare imagery

### Local raster

Run:

```powershell
python scripts/prepare_imagery.py local --input <image.tif> --output-dir <prepared> --bands 1,2,3
```

For an unreferenced JPG/PNG, accept it only with explicit map information:

```powershell
python scripts/prepare_imagery.py local --input <image.png> --output-dir <prepared> --crs <EPSG:code> --bounds <xmin,ymin,xmax,ymax>
```

Do not infer bounds or CRS from scene appearance.

### GEE source

Resolve project, AOI seed, bands, dates, scale, CRS and scale factor. For
boundary extraction, prefer one actual acquisition over a median composite.
Select a recent clear scene using AOI-valid-pixel coverage and AOI-local cloud
quality; collection footprint coverage or scene-level cloud metadata alone is
not enough. Run:

```powershell
python scripts/select_recent_gee_scene.py --project <project> --center <lon,lat> --radius-km <km>
```

Pass its `selected_image_id` to preparation so the exact acquisition remains
traceable:

```powershell
python scripts/prepare_imagery.py gee --project <project> --output-dir <prepared> --region <xmin,ymin,xmax,ymax> --image-id <selected-image-id> --bands <red,green,blue> --scale <metres> --crs <EPSG:code> --name <scene>
```

Use a composite only when the user requests one or no adequate single scene
exists, and label that fallback. The selector must fail when its coverage or
clarity thresholds are unmet; use `--allow-best-available` only as an explicit,
reported fallback. Verify the prepared raster's `valid_pixel_fraction`; reject
or reselect scenes with clipped/nodata AOI coverage.

Use the EasyGEE export planner and `ee.batch.Export.image.*` for large results.
Do not silently coarsen scale or shrink AOI to bypass download limits.

The preparation script must produce:

- a CRS-preserving raster;
- a model-friendly PNG preview;
- metadata containing source, bands, dimensions, transform, bounds, CRS and
  GEE provenance where relevant.

## Choose whole-scene or tiled inference

Use the whole preview only when targets remain visually separable. For small
or dense targets, create overlapping georeferenced tiles:

```powershell
python scripts/tile_imagery.py --input <prepared.tif> --output-dir <tiles> --tile-size 512 --overlap 128
```

Prefer tiling when a target would be smaller than roughly 8–15 pixels in the
model preview. Keep context around border objects.

## Obtain multimodal annotations

Generate a strict prompt:

```powershell
python scripts/prompt_template.py --image <preview.png> --target "<target definition>" --geometry <polygon|bbox|point|line> --output <prompt.txt>
```

Use the model's visual capability to return structured pixel JSON. Prefer JSON
over painted overlays. Require the model to:

- use the declared preview width/height and upper-left pixel origin;
- return object id, label, geometry type, confidence and coordinates;
- avoid guessing map coordinates;
- lower confidence or omit ambiguous targets;
- follow explicit inclusion/exclusion rules.

If the model cannot return coordinates, request a single bright-color outline
overlay that preserves the exact extent and aspect ratio. Treat overlay color
extraction as a fallback because image edits can alter pixels or produce inner
and outer duplicate contours.

## Merge tiled annotations

Save tile-local JSON files as `<tile_id>.json` or
`<tile_id>_annotations.json`, then run:

```powershell
python scripts/merge_tile_annotations.py --manifest <tiles_manifest.json> --annotations-dir <tile-json-dir> --output <merged_annotations.json> --iou-threshold 0.5
```

Report object counts before and after overlap deduplication.

## Restore CRS and export vectors

For structured annotations, run:

```powershell
python scripts/vectorize_annotations.py json --annotations <annotations.json> --raster <reference.tif> --output-stem <results/targets>
```

For a bright-color overlay, run:

```powershell
python scripts/vectorize_annotations.py overlay --overlay <overlay.png> --raster <reference.tif> --output-stem <results/targets> --color cyan
```

Apply `--min-area`, `--max-area`, `--min-circularity` or `--simplify` only
when the target definition and projected CRS make the thresholds meaningful.
Do not impose field-specific shape filters on vehicles, crowns or generic
objects.

Write separate polygon, line and point GeoPackages in the raster's native CRS,
EPSG:4326 GeoJSON exchange files, a polygon-boundary line GeoPackage, and a
manifest with counts and paths.

Render a boundary-only QA overlay before handoff:

```powershell
python scripts/render_vector_qa.py --raster <reference.tif> --vector <results/targets_polygons.gpkg> --layer polygons --output <results/qa_overlay.png>
```

## Validate and hand off

1. Confirm raster and native vectors have the expected CRS.
2. Confirm all geometries are valid and output bounds overlap the raster.
3. Load the boundary line layer above the source raster in QGIS; use transparent
   polygon fill during QA.
4. Inspect duplicates, border truncation, shadows, touching objects and class
   confusion.
5. Preserve raw annotation JSON, prompt, model/version, thresholds and source
   metadata.
6. Call results candidate annotations unless independent labels support
   precision/recall, IoU or count-accuracy claims.
7. Report the selected image id/date, native pixel size, effective preview
   scale, candidate count, filters, and expected boundary uncertainty.

Run the no-data smoke test after modifying scripts:

```powershell
python scripts/smoke_test.py
```

Do not bundle user imagery, case-specific labels or demonstration outputs in
this skill. Use synthetic temporary data for offline tests or a user-selected,
small GEE AOI for live verification.
