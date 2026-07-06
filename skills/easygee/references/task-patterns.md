# Task Patterns

Use this reference when the user asks for a geospatial analysis outcome rather
than a specific Earth Engine API call. It routes common requests into safe
GEE/geemap workflow shapes.

## Universal Task Frame

Before coding, write down:

- AOI: explicit geometry, drawn geometry fallback, asset id, or local vector.
- Time: date range, season, baseline period, event date, or monitoring cadence.
- Unit: pixel map, zonal table, time series, classification map, export, app.
- Dataset: exact Earth Engine id plus band/QA/scale facts.
- Validation: one visual probe, one small numeric probe, and one failure mode.
- Persistence: notebook, script, map HTML/PNG, Drive/Cloud/Asset export, CSV.

If any of these are missing, choose a conservative default only when the user is
exploring; label it as a placeholder in the notebook/script.

## Ambiguous Extraction Requests

Use `scripts/resolve_ambiguous_geo_request.py "<prompt>" --json` before running
analysis when the user gives a target noun without method details, for example
"提取这个 AOI 中的水体", "extract water here", "提取这个影像里的屋顶", or "识别当前图层里的目标".

Default order:

1. Prefer a reproducible GEE product or remote-sensing workflow when the user is
   asking for an AOI result, a statistic, an export, or a layer that should be
   explainable later.
2. Use current-image visual recognition when the user explicitly says "this
   image/current image/这个影像/屏幕可见" or when no suitable GEE product or
   sensor workflow can answer the target at the needed resolution.
3. If the target wording changes the answer, ask one multiple-choice
   clarification before computing. Do not silently choose among permanent water,
   current water, flood water, building footprints, roof surfaces, and
   screen-visible annotations.

Common clarifications:

| Prompt | Ask | Routes |
|---|---|---|
| Water in an AOI | Long-term/permanent water, current water, or flood/event water? | JRC/Dynamic World product; Sentinel-2/Landsat water index; Sentinel-1 SAR flood workflow |
| Rooftops/buildings in current image | Visible rooftops, building footprints, or roof surface/material? | Current-image visual recognition; Open Buildings/built-up products where covered; custom segmentation/classification |
| Unknown object/class | Existing catalog class, custom remote-sensing method, or current-image visible object? | Dataset search; supervised/threshold workflow; visual annotation |

When the route is ready, run the work in the background and sync results back to
the Map Console as ordinary layers, vectors, task-log entries, or tables. Do not
add a new toolbar button for each analysis.

## Pattern Router

| User Intent | Prefer | Read Also | First Probe | Common Failure |
|---|---|---|---|---|
| Vegetation health, greenness, crop vigor, NDVI/EVI | Sentinel-2 SR, Landsat C2 L2, MOD13Q1 for long coarse series | `dataset-qa-patterns.md` | Add RGB + index layer; reduce mean over tiny AOI | Cloud/haze left unmasked, mixing 10 m and 250 m without saying so |
| Surface water, flood extent, inundation | JRC Global Surface Water for historical occurrence; Sentinel-2/Landsat index threshold for event maps; Sentinel-1 when cloudy | `dataset-qa-patterns.md`, `geemap-agent-recipes.md` | Add water mask and inspect edge pixels | Threshold treated as universal truth; shadows/clouds confuse optical water |
| Land cover, crop/urban/forest classes | Dynamic World / ESA WorldCover for existing classes; supervised classifier for custom classes | `dataset-qa-patterns.md` | Class palette + class area table | Averaging class labels; no validation split/confusion matrix |
| Change detection, disturbance, loss/gain | Pre/post composites, differenced index, categorical transitions, Hansen/JRC products when appropriate | `gee-agent-playbook.md` | Side-by-side maps and histogram/delta summary | Seasonal mismatch or different sensors/scales masquerade as change |
| Zonal statistics, admin summaries, area by class | `reduceRegions`, grouped reducers, `geemap.zonal_stats`, table export | `geemap-agent-recipes.md` | Run one feature first, then full collection | Missing scale/CRS or class pixel area calculation |
| Time series and charts | Map image collection to FeatureCollection, chart in notebook, export CSV for large series | `workflows.md`, `geemap-agent-recipes.md` | Plot 5-20 rows before export | `getInfo()` on large FeatureCollection |
| Supervised classification | Sample predictors, train classifier, classify, validate with holdout/confusion matrix | `dataset-qa-patterns.md` | Show training points over composite | Band order mismatch; class labels not integer/consecutive |
| Terrain, slope, aspect, hillshade | DEM native projection when possible, terrain functions, cautious resampling | `dataset-qa-patterns.md` | Inspect projection and slope range | Default composite projection or forced `reproject()` over huge area |
| Land surface temperature, heat island | Landsat C2 L2 for 30 m LST snapshots; MOD11A2 for coarse time series | `dataset-qa-patterns.md` | LST map plus min/mean/max over small AOI | Raw thermal DN treated as Celsius; QA/cloud effects ignored |
| Nighttime lights, human activity | VIIRS monthly DNB composites | `dataset-qa-patterns.md` | Monthly/annual radiance map and zonal summary | Proxy interpreted as direct GDP/population; gas flares/fires/noise ignored |
| Population or building exposure | WorldPop/GHSL plus hazard mask; Open Buildings for supported regions | `dataset-qa-patterns.md`, `gee-agent-playbook.md` | One hazard/exposure overlay and one zone sum | Hazard and exposure dates mismatch; huge vectors not spatially filtered |
| Communication map or demo app | geemap map, legend, split panel, inspector/draw widgets, HTML/PNG export | `opengeos-patterns.md` | Open map with labeled layers | Pretty map used as proof of analysis correctness |

## Vegetation Index Workflow

Use when the user asks for NDVI, EVI, vegetation health, crop vigor, greenness,
phenology, or drought proxies.

1. Pick resolution by question: Sentinel-2 10 m for field/local maps, Landsat
   30 m for longer historical analysis, MODIS 250 m for coarse dense time
   series.
2. Apply dataset QA first: Cloud Score+/SCL for S2, QA_PIXEL and scale factors
   for Landsat, DetailedQA/SummaryQA and `0.0001` scaling for MODIS VI.
3. Compute index server-side with named bands. For S2 NDVI use `B8`, `B4`; for
   Landsat 8/9 NDVI use `SR_B5`, `SR_B4`; for Landsat 5/7 use `SR_B4`, `SR_B3`.
4. Add RGB and index layers. Use a fixed palette and date-aware layer names.
5. Probe with `reduceRegion` over one small AOI at explicit scale; export table
   for long time series.

Agent refusal point: do not compare vegetation values across sensors/resolutions
without writing the harmonization caveat.

## Water And Flood Workflow

Use when the user asks for water extent, wetland inundation, flood mapping, lake
area, river change, or occurrence.

- Historical occurrence: use JRC Global Surface Water layers and threshold
  occurrence/change/seasonality according to the question.
- Event mapping in clear optical scenes: use Sentinel-2/Landsat with QA mask,
  MNDWI/NDWI/AWEI-style candidate layers, then threshold and inspect edges.
- Cloudy flood mapping: consider Sentinel-1 SAR with pre/post composites and a
  ratio/difference threshold; note speckle, terrain shadow, and urban false
  positives.
- Area: multiply binary mask by `ee.Image.pixelArea()`, divide units explicitly,
  and summarize with `reduceRegion`/`reduceRegions`.

geemap pattern: show RGB/SAR background, index/probability layer, binary mask,
and optional split panel for pre/post.

## Classification Workflow

Use when the user asks for land cover, crop type, urban/bare/forest mapping, or
custom classes.

For existing products, prefer Dynamic World or ESA WorldCover when their classes
match the question. Use probability/confidence bands where available.

For supervised classification:

1. Build a cloud-masked, scaled composite with predictors documented in order.
2. Load or draw training data; class property must be numeric and consecutive.
3. Use `sampleRegions()` or `sample()` with explicit scale and geometries.
4. Split training/validation using `randomColumn()` or independent samples.
5. Train classifier, classify image, and report confusion matrix/accuracy
   limits.
6. Export classification map and validation table separately.

Agent refusal point: do not present a classified map as reliable without naming
training data provenance and validation method.

## Change Detection Workflow

Use when the user asks "before/after", "loss/gain", "trend", "disturbance", or
"changed area".

1. Match season, sensor, bands, QA, and scale between baseline and target
   periods.
2. Create composites for each period using the same function.
3. Compute a delta image or categorical transition map.
4. Add pre, post, delta, and thresholded change layers.
5. Summarize area with `pixelArea()` and export both raster and table when the
   result will be used outside the notebook.

For forest loss, water occurrence, or land-cover transitions, prefer stable
curated products when they directly answer the question.

## Zonal Statistics Workflow

Use when the output is "by county", "by watershed", "per polygon", "for each
field", or "summary table".

- Validate the zone geometries first: CRS is handled by EE, but invalid or huge
  geometries still hurt performance.
- Run one feature through `reduceRegion` before `reduceRegions`.
- For continuous rasters, report reducer, scale, units, and masked-pixel
  behavior.
- For categorical rasters, use grouped reducers and `pixelArea()`, not means of
  class labels.
- Export large tables with `Export.table` or `geemap.zonal_stats`; avoid pulling
  large results through `getInfo()`.

## Dataset Discovery Workflow

Use when the user asks which GEE dataset to use, asks in Chinese for data such
as "洪水淹没范围", "人口暴露", "夜间灯光", "地表温度", "土地覆盖", or when the analysis
goal is underspecified.

1. Run `scripts/search_gee_dataset.py "<task>" --workflow`.
2. Treat the result as candidates, then open or cite the official catalog page
   for the selected dataset.
3. Record dataset id, type, bands, scale, date coverage, QA method, and terms.
4. Identify companion datasets, such as Cloud Score+ for Sentinel-2 or a
   population layer for exposure analysis.
5. Pick the workflow template only after the dataset semantics fit the task.

Agent refusal point: do not write final analysis code from a remembered dataset
id alone when the official catalog has not been checked or recorded.

## Notebook Delivery Bar

A good geemap task notebook has:

- a visible AOI layer and fallback geometry,
- source and dataset id cells,
- at least one visual QA layer before the result layer,
- one small numeric diagnostic,
- export cells that are not accidentally started,
- a short limitations/provenance cell,
- `review_ee_code.py` output reviewed before handoff.
