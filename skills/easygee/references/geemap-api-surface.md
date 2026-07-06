# geemap API Surface

Use this reference when deciding which geemap function, widget, backend, or
export helper to use. It complements `gee-agent-playbook.md`, which covers
Earth Engine execution semantics.

## Backend And Import Choice

- Local Jupyter/JupyterLab with interaction: `import geemap`; use
  `geemap.Map()` with ipyleaflet widgets.
- Colab or lightweight static maps: `import geemap.core as geemap` for many
  official examples, or `import geemap.foliumap as geemap` when ipyleaflet
  widgets are unavailable.
- Static HTML/report: use folium-style output or `Map.to_html()`. Record that
  static output cannot capture future user clicks, draw events, or inspector
  interaction.

Agent rule: choose the backend before writing cells. Do not mix `Map.addLayer`,
`Map.add_layer`, `Map.to_html`, and widget-specific calls blindly across
backends without a quick compatibility check.

## Map Construction And Layers

Common functions:

```python
import geemap

Map = geemap.Map(center=[40, -100], zoom=4)
Map.add_basemap("HYBRID")
Map.addLayer(ee_object, vis_params, "Layer name", shown=True, opacity=0.85)
Map.centerObject(roi, 10)
Map
```

Use:

- `Map.addLayer(...)` / `Map.add_layer(...)`: display EE images, vectors, and
  derived layers for QA.
- `Map.centerObject(ee_object, zoom)`: center on AOI or result.
- `Map.setCenter(lon, lat, zoom)`: center on known coordinates.
- `Map.add_basemap(...)`, `Map.add_tile_layer(...)`, `Map.add_wms_layer(...)`:
  add basemaps or external context.
- `Map.add_legend(...)`: class maps, land cover, QA masks, or categorical
  products.
- `Map.split_map(left_layer=..., right_layer=...)`: before/after comparison or
  basemap comparison.

Layer names should encode dataset, date/composite, metric, and mask state when
the map is part of analysis.

## Drawing, AOI, And Interaction

Use drawing tools when the user needs notebook-driven AOI selection.

```python
feature = Map.draw_last_feature
if feature is None:
    roi = ee.Geometry.Rectangle([119.8, 30.0, 120.5, 30.5])
else:
    roi = ee.Feature(feature).geometry()
```

Newer draw-control workflows can expose drawn geometry as `m.user_roi` and
multiple user regions as `m._user_rois`. Treat these as interactive state:
convert them into an explicit geometry cell before finalizing a notebook.

Use inspector/plotting tools for exploration, but convert any clicked point,
drawn polygon, or marker collection into reproducible `ee.Geometry` or
`ee.FeatureCollection` code before handoff.

## Dataset Discovery

Start with official Earth Engine Data Catalog pages when the dataset is known.
When the task is exploratory:

- Run `scripts/search_gee_dataset.py "<task>" --workflow` for an offline,
  bilingual candidate set with QA, scale, risk, and workflow hints.
- Use geemap dataset search / catalog examples inside notebooks.
- Use `geemap.ee_search()` for Earth Engine API documentation search.
- Use `geemap.ai.EarthEngineDatasetIndex.find_top_matches(...)` only as a
  discovery aid; verify the selected dataset in the official catalog before
  coding analysis.

Agent rule: geemap catalog search helps find candidates; the official catalog
proves band names, scale factors, QA fields, dates, and terms.

## Local Data Bridges

Use:

```python
ee_object = geemap.shp_to_ee("zones.shp")
ee_object = geemap.geojson_to_ee("roi.geojson")
Map.addLayer(ee_object, {}, "Local vector as EE")
```

Before converting local data:

- inspect CRS, geometry validity, file size, and privacy,
- simplify huge geometries where scientifically acceptable,
- avoid uploading or embedding sensitive raw data unless explicitly requested.

For local rasters, use geemap local raster display helpers for visualization;
use Earth Engine asset upload or local raster libraries when the raster must
participate in server-side EE computation.

## Analysis Helpers

Use `geemap.zonal_stats(...)` for quick continuous raster summaries and
`geemap.zonal_stats_by_group(...)` for class-area style summaries.

```python
geemap.zonal_stats(image, zones, "stats.csv", stat_type="MEAN", scale=30)
geemap.zonal_stats_by_group(class_image, zones, "area.csv", stat_type="SUM")
```

Still follow GEE rules:

- set scale intentionally,
- use pixel area for class areas,
- avoid mean of categorical labels,
- run one zone first for expensive or untrusted geometries.

Use geemap chart/timeseries notebooks for visual diagnostics, then export the
underlying `FeatureCollection` or CSV for durable outputs.

## Exports

For natural-language export requests, run `scripts/plan_gee_export.py` first.
It decides whether the user is asking for a raster, table, vector, map
communication artifact, or video; whether the destination is Drive, Cloud
Storage, Earth Engine Asset, BigQuery, or local; and whether to use a geemap
local helper or an explicit `ee.batch.Export.*` task.

Local or notebook-scale image export:

```python
geemap.ee_export_image(
    image.clip(roi),
    filename="output.tif",
    scale=30,
    region=roi,
    file_per_band=False,
)
```

Drive export:

```python
geemap.ee_export_image_to_drive(
    image=image.clip(roi),
    description="clear_task_name",
    folder="earthengine_exports",
    region=roi,
    scale=30,
)
```

Vector export:

```python
geemap.ee_export_vector(fc, "features.geojson")
geemap.ee_to_csv(fc, "features.csv")
```

Map communication export:

```python
Map.to_html(filename="map.html", title="Map", width="100%", height="880px")
Map.to_image(filename="map.png")
```

Export rules:

- Prefer asynchronous EE export tasks for large rasters/tables.
- In EasyGEE Map Console workflows, prefer explicit `ee.batch.Export.*` task
  creation for durable exports so the workbench can persist task id, status,
  destination, AOI, scale/CRS, and file naming.
- Use geemap local helpers for modest notebook outputs and quick local
  downloads; switch to batch exports when size, timeout, quota, or task
  tracking matters.
- Always report destination, task/description, scale, region, CRS/transform
  assumptions, and whether the export was started.
- HTML/PNG map exports are communication artifacts, not analytical exports.

## Conversion And Migration

Use geemap conversion tools for first-pass migration from Earth Engine
JavaScript:

```python
from geemap.conversion import js_to_python_dir, py_to_ipynb_dir
js_to_python_dir("gee-js", "gee-python")
```

Review converted output for:

- Code Editor UI assumptions,
- missing `ee.Initialize(project=...)`,
- `print()`/`getInfo()` behavior,
- export task start behavior,
- `Map` backend compatibility,
- JavaScript anonymous functions translated into Python callables.

## Timelapse And Apps

Use:

- `Map.add_landsat_ts_gif(...)` for quick Landsat timelapse exploration,
- `Map.add_gui("timelapse")` for GUI-driven timelapse creation,
- water/timelapse app notebooks as design patterns for ipywidgets controls.

Agent rule: timelapse output is a storytelling artifact unless the workflow
also exports the underlying image collection, frames, dates, and parameters.

## API Choice Checklist

Before choosing a geemap helper:

1. Is the result interactive exploration, durable analysis, or communication?
2. Does the helper run client-side download or create an EE batch task?
3. Does it preserve scale, region, projection, nodata, and masks?
4. Does it depend on hidden drawn/clicked state?
5. Can `review_ee_code.py` still inspect the generated script/notebook?
