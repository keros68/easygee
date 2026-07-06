# GEE Agent Playbook

Use this reference before writing non-trivial Earth Engine code. It distills
Earth Engine's official execution model into operational rules for AI agents
using Python and geemap.

## Mental Model

Earth Engine code builds a computation graph. Python code constructs server-side
proxy objects such as `ee.Image`, `ee.ImageCollection`, `ee.FeatureCollection`,
`ee.Geometry`, `ee.Reducer`, and `ee.List`. The graph is evaluated only when
the client requests a result, such as:

- rendering tiles in a geemap map,
- calling `getInfo()` or displaying an object through notebook helpers,
- starting an export task,
- requesting a thumbnail, chart, or download URL.

Agent rule: build server-side graphs deliberately, then use small probes to
validate them. Do not confuse a rendered map tile with a completed analysis.

## Client/Server Rules

- Anything constructed with `ee.*` is a server-side proxy. It is not a Python
  value, even if it prints nicely.
- Use `getInfo()` only for small scalars, metadata, short lists, tiny samples,
  or debugging. It blocks Python execution and can trigger expensive requests.
- In mapped functions, do not mutate external variables, print, call `getInfo()`,
  or use native Python `if`/`for` on server-side objects.
- Prefer filters, reducers, joins, `map()`, `iterate()` only when necessary,
  and server-side dictionaries/lists over client loops.
- Prefer `filter()` and `limit()` over `toList()` for collections.
- Avoid `ee.Algorithms.If()` as a default branch mechanism. Use filters,
  masks, and separate collection paths when possible.

## Standard Agent Workflow

1. **Frame**: identify AOI, time range, dataset, bands, scale, output format,
   and environment (notebook, script, QGIS, app).
2. **Discover**: record dataset ids and key band/QA fields from official
   catalog/docs or clearly label assumptions. Use
   `references/data-layer-records.md` when dataset semantics or provenance need
   to travel with the result.
3. **Filter**: filter by geometry, date, collection metadata, and QA/cloud
   fields. Use `references/boundary-compute-patterns.md` when AOI complexity,
   bbox filtering, exact final geometry, tiling, or task count matters. Keep a
   diagnostic collection size query small.
4. **Probe visually**: add a representative image/composite with explicit
   visualization params and a meaningful layer name.
5. **Probe numerically**: sample a small point/ROI or run a small reducer.
6. **Scale carefully**: switch to batch export, chunking, or coarser scale when
   interactive requests become expensive.
7. **Persist**: save a notebook, script, map HTML, export task metadata, or
   project state. Include dataset ids, parameters, and validation notes.

## Debugging Ladder

Use this order before rewriting the whole workflow:

1. Print object type/metadata without forcing large data. Use `image.bandNames()`,
   `image.projection()`, `collection.size()`, `collection.first()`, and
   `aggregate_array()` on small metadata fields.
2. Run the mapped function on one element: `fn(collection.first())`.
3. Clip or filter to a tiny AOI and short time window.
4. Add intermediate layers to geemap with opacity off or low opacity.
5. Check masks: use `.mask()`, `.selfMask()`, `.unmask()`, and layer display to
   determine whether missing output is masked rather than absent.
6. Check scale/projection: inspect projection, nominal scale, CRS, and export
   transform before trusting pixel alignment.
7. Replace interactive reducer calls with an export when timeout/memory errors
   appear.
8. If quota/rate errors appear, reduce concurrency, cache repeated requests,
   and use backoff rather than retry storms.

## Reducer Patterns

- ImageCollection to image: use `collection.median()`, `mean()`, `mosaic()`,
  `qualityMosaic()`, or `collection.reduce(reducer)` depending on the science.
- Image to scalar/table: use `reduceRegion()` for one geometry and
  `reduceRegions()` or mapping `reduceRegion()` over features for many regions.
- FeatureCollection columns: use `reduceColumns()`.
- Multiple stats: combine reducers where possible rather than running separate
  reductions.
- Grouped classes: use grouped reducers for land-cover composition and class
  area summaries.

Always specify or justify:

- `geometry` / `region`,
- `scale`,
- `crs` or projection assumptions when alignment matters,
- `maxPixels` for large reductions/exports,
- reducer name and output units,
- masking and nodata behavior.
- boundary/compute risk when the ROI is large, complex, tiled, or expensive.

## Export Rules

For natural-language export requests, run `scripts/plan_gee_export.py` before
writing code. Treat the result as an export contract: product type,
destination, format, AOI/region, scale/CRS, ImageCollection reducer, task
lifecycle, and missing parameters.

Prefer explicit export parameters:

```python
task = ee.batch.Export.image.toDrive(
    image=image,
    description="clear_task_name",
    folder="earthengine_exports",
    fileNamePrefix="clear_file_prefix",
    region=region,
    scale=30,
    crs="EPSG:4326",  # only when appropriate
    maxPixels=1e13,
    fileFormat="GeoTIFF",
    formatOptions={"cloudOptimized": True},
)
task.start()
```

Use `scale` for approximate resolution. Use `crs` plus `crsTransform` when the
export must align exactly with an existing pixel grid; scale alone can shift the
grid because Earth Engine computes transform origin values.

For masked pixels, decide intentionally:

- keep masks for analysis semantics,
- use `.unmask(no_data_value)` before GeoTIFF export when downstream tools need
  explicit nodata,
- ensure nodata lies inside the image pixel type range.

Report task id, destination, region, scale/CRS, `maxPixels`, and whether the
task was started or just defined.

Do not export an `ImageCollection` as if it were a single raster. First reduce
or composite it into an `ee.Image`, or map it into a `FeatureCollection` when
the user wants a time-series/table export.

## Quota And Performance Rules

- Use batch exports for long-running or expensive computations.
- Avoid repeated identical interactive requests; cache metadata and map state
  in notebooks or local files when appropriate.
- Reduce request concurrency when seeing HTTP 429 or quota messages.
- Do not try to bypass quotas with multiple accounts.
- Use smaller AOIs, fewer bands, coarser scale, fewer dates, or tiling before
  changing the scientific method.

## Agent Code Review Checklist

Before presenting code:

- `ee.Initialize(project=...)` is explicit or the project is intentionally
  deferred.
- Dataset ids, bands, QA masks, date range, AOI, scale, and visualization params
  are explicit.
- Data-layer semantics include source provenance, units, scale/offset, QA/mask,
  transformations, and verification status when they affect the result.
- Boundary/compute choices include AOI source, exact vs bbox geometry, tiling
  safety, and task count when relevant.
- `getInfo()` calls are small and justified.
- Server-side functions do not contain Python-native control flow over
  server-side objects.
- Reducers include geometry, scale, and pixel-limit choices.
- Exports include task metadata and do not silently upload private data.
- Notebook outputs do not depend on hidden state or unrecorded clicked geometry
  unless the user was explicitly asked to draw/select it.
