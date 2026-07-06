# Workflow Patterns

Use this reference for practical GEE/geemap coding patterns after setup and
authentication are understood.

## Notebook Exploration

Use notebooks when the user needs visual inspection, layer styling, interactive
ROI drawing, quick plots, or communication artifacts.

```python
import ee
import geemap

ee.Initialize(project="my-earthengine-project")

m = geemap.Map()
roi = ee.Geometry.Rectangle([119.8, 30.0, 120.5, 30.5])
m.centerObject(roi, 10)
```

Prefer `geemap.Map()` for rich local/Jupyter use. In Google Colab, official
Earth Engine docs show `import geemap.core as geemap` for the preinstalled core
path; adapt imports to the runtime.

## Server-Side Collection Pattern

Keep transformations server-side:

```python
def add_ndvi(img):
    return img.addBands(img.normalizedDifference(["B8", "B4"]).rename("NDVI"))

collection = (
    ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
    .filterBounds(roi)
    .filterDate("2024-01-01", "2024-12-31")
    .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
    .map(add_ndvi)
)
```

Avoid Python loops that call `getInfo()` on each image. Use reducers and
`FeatureCollection` outputs.

## Time Series Extraction

```python
def image_to_feature(img):
    stats = img.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=roi,
        scale=30,
        maxPixels=1e9,
    )
    return ee.Feature(None, {
        "date": img.date().format("YYYY-MM-dd"),
        "ndvi": stats.get("NDVI"),
    })

series = collection.map(image_to_feature)
rows = series.getInfo()["features"]  # acceptable only for small diagnostic output
```

For large time series, export the `FeatureCollection` instead of calling
`getInfo()`.

## Exports

When the user describes an export in natural language, first run
`scripts/plan_gee_export.py "<request>" --json` to classify product type,
destination, backend, format, AOI source, scale, and missing parameters.

Prefer explicit names, region, scale, and `maxPixels`.

```python
task = ee.batch.Export.image.toDrive(
    image=ndvi,
    description="ndvi_2024_hangzhou",
    folder="earthengine_exports",
    fileNamePrefix="ndvi_2024_hangzhou",
    region=roi,
    scale=30,
    maxPixels=1e13,
)
task.start()
print(task.id)
```

Report whether an export task was only defined, started, or completed. Earth
Engine exports are asynchronous.

## Local Data To Earth Engine

Small GeoJSON geometries can be converted directly. Large or sensitive local
datasets should stay local unless the user explicitly wants to upload assets.

```python
import geemap

fc = geemap.geojson_to_ee("roi.geojson")
```

For heavy vector/raster preprocessing, use local geospatial tools first
(`geopandas`, `rasterio`, `gdal`) and then pass only the necessary geometry or
asset reference to Earth Engine.

## Combining With Other Skills

If remote-sensing methodology is the main challenge, pair this skill with the
local `geomaster` skill. Use `easygee` for auth, initialization, geemap, and
GEE execution shape; use `geomaster` for domain choices such as indices, SAR,
classification, terrain, hydrology, and CRS handling.
