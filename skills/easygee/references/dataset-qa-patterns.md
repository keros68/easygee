# Dataset QA Patterns

Use this reference when selecting Earth Engine datasets, masking clouds/shadows,
choosing scale/projection, or reviewing whether a geemap workflow is
scientifically safe enough to export.

## Agent Rules

- Treat `filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", ...))` or
  `filter(ee.Filter.lt("CLOUD_COVER", ...))` as scene filtering, not pixel
  cloud masking.
- Prefer official catalog band names, scale factors, QA bit fields, and
  availability notes over remembered snippets.
- Record dataset id, band names, scale factors, QA mask method, projection/scale
  choice, and date range in notebooks and scripts.
- For categorical products, use `mode()`, class counts, grouped reducers, or
  nearest-neighbor behavior. Do not average class labels.
- For composites/mosaics, specify `scale` in reducers/exports. Inspect
  projection before terrain, gradient, alignment, or area-sensitive work.

## Sentinel-2 Surface Reflectance

Dataset: `COPERNICUS/S2_SR_HARMONIZED`.

Key facts:

- Surface reflectance bands are scaled by `10000`; visualization commonly uses
  raw SR ranges such as `min=0, max=3000`, while index ratios can use raw bands.
- Use `CLOUDY_PIXEL_PERCENTAGE` only to filter scenes before a pixel mask.
- QA60 has a historical caveat: legacy cloud polygons stopped on `2022-01-25`;
  legacy-consistent QA60 is reconstructed from MSK_CLASSI bands starting
  `2024-02-28`. Do not rely on QA60 alone across the gap.
- Preferred current mask for many agent workflows: link Cloud Score+
  `GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED` and threshold `cs` or `cs_cdf`.

Cloud Score+ pattern:

```python
s2 = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
cs = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")
qa_band = "cs_cdf"
clear_threshold = 0.60

def mask_s2_clear(img):
    return img.updateMask(img.select(qa_band).gte(clear_threshold))

collection = (
    s2.filterBounds(roi)
    .filterDate(start, end)
    .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 80))
    .linkCollection(cs, [qa_band])
    .map(mask_s2_clear)
)
```

SCL fallback:

```python
def mask_s2_scl(img):
    scl = img.select("SCL")
    good = (
        scl.neq(0)   # no data
        .And(scl.neq(1))   # saturated/defective
        .And(scl.neq(3))   # cloud shadow
        .And(scl.neq(8))   # medium probability cloud
        .And(scl.neq(9))   # high probability cloud
        .And(scl.neq(10))  # cirrus
        .And(scl.neq(11))  # snow/ice, unless snow is the target
    )
    return img.updateMask(good)
```

When bright roofs, snow, haze, or shadow matter, use a visual probe and a small
numeric probe before export; do not treat a median composite as proof of
successful masking.

## Sentinel-2 Cloud Probability

Dataset: `COPERNICUS/S2_CLOUD_PROBABILITY`.

Use when the workflow needs the s2cloudless-style probability band or when
Cloud Score+ is unsuitable. The `probability` band is `0..100` at 10 m; higher
means more likely cloud or highly reflective surface. Join to source S2 images
by `system:index` or use the official join pattern from the catalog/tutorial.

Agent rule: document the threshold and show at least one cloud-probability layer
or mask layer during notebook QA.

## Landsat Collection 2 Level 2

Datasets include:

- `LANDSAT/LC09/C02/T1_L2`
- `LANDSAT/LC08/C02/T1_L2`
- `LANDSAT/LE07/C02/T1_L2`
- `LANDSAT/LT05/C02/T1_L2`

Always apply Collection 2 scale factors before visualizing or exporting
reflectance/temperature:

```python
def apply_landsat_c2_l2_scale(image):
    optical = image.select("SR_B.").multiply(0.0000275).add(-0.2)
    thermal = image.select("ST_B.*").multiply(0.00341802).add(149.0)
    return image.addBands(optical, None, True).addBands(thermal, None, True)
```

Typical QA mask:

```python
def mask_landsat_c2_l2(image):
    qa = image.select("QA_PIXEL")
    dilated_cloud = qa.bitwiseAnd(1 << 1).eq(0)
    cirrus = qa.bitwiseAnd(1 << 2).eq(0)
    cloud = qa.bitwiseAnd(1 << 3).eq(0)
    shadow = qa.bitwiseAnd(1 << 4).eq(0)
    snow = qa.bitwiseAnd(1 << 5).eq(0)
    clear = dilated_cloud.And(cirrus).And(cloud).And(shadow).And(snow)
    return image.updateMask(clear)
```

Use sensor-specific bands for indices:

- Landsat 8/9 NDVI: `SR_B5`, `SR_B4`
- Landsat 5/7 NDVI: `SR_B4`, `SR_B3`

## MODIS Vegetation Indices

Dataset: `MODIS/061/MOD13Q1`.

- `NDVI` and `EVI` are scaled by `0.0001`.
- Use `DetailedQA` or `SummaryQA` to filter poor-quality observations before
  time-series analysis.
- MODIS VI is 250 m and 16-day; avoid mixing directly with Sentinel/Landsat
  pixel statistics without explaining the scale mismatch.

## Dynamic World

Dataset: `GOOGLE/DYNAMICWORLD/V1`.

- Probability bands are `water`, `trees`, `grass`, `flooded_vegetation`,
  `crops`, `shrub_and_scrub`, `built`, `bare`, and `snow_and_ice`; `label` is
  the top class.
- The probability bands sum to 1 per pixel. Use confidence thresholds,
  probability summaries, or class stability checks rather than treating
  `label` as ground truth.
- Images correspond to Sentinel-2 L1C source ids; align date/AOI filters with
  source imagery when combining with S2.

## Sentinel-1 SAR GRD

Dataset: `COPERNICUS/S1_GRD`.

Use when optical imagery is blocked by clouds or when a flood/event-water
workflow benefits from radar backscatter. Filter deliberately:

- `instrumentMode == "IW"` for most land workflows.
- `transmitterReceiverPolarisation` contains the needed bands, commonly `VV`
  and `VH`.
- `resolution_meters == 10` when a 10 m workflow is expected.
- Consider orbit direction and relative orbit when comparing before/after
  images.

Agent rule: a threshold such as `VV < -16 dB` is only a candidate. SAR flood
mapping needs local visual probes and caveats for speckle, terrain shadow,
wind-roughened water, vegetation, and urban double-bounce.

## MODIS Land Surface Temperature

Dataset: `MODIS/061/MOD11A2`.

- `LST_Day_1km` and `LST_Night_1km` use a scale factor of `0.02` Kelvin.
- Convert to Celsius with `image.multiply(0.02).subtract(273.15)` when needed.
- Use `QC_Day` or `QC_Night` to filter poor-quality pixels.
- MOD11A2 is an 8-day 1 km product. Do not compare it directly to Landsat
  30 m LST without a scale/cadence caveat.

For Landsat Collection 2 LST, use `ST_B10` with its scale/offset from the
official catalog and apply `QA_PIXEL` before aggregation.

## Nighttime Lights

Dataset: `NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG`.

Use for monthly nighttime-light composites and human-activity proxies. The
common radiance band is `avg_rad`; use coverage/quality context such as
`cf_cvg` when summarizing.

Agent rule: nighttime lights are proxy evidence. Fires, gas flares, fishing
fleets, saturation, atmospheric effects, and coverage gaps can mislead urban
or economic interpretations.

## Population And Built Exposure

Useful datasets:

- `WorldPop/GP/100m/pop` for relatively fine population-count surfaces.
- `JRC/GHSL/P2023A/GHS_POP` for multi-epoch population surfaces and
  projections.
- `GOOGLE/Research/open-buildings/v3/polygons` for building footprints in
  supported regions.

Agent rules:

- Keep hazard and exposure layers separate until the overlay step.
- Match hazard date to the closest defensible population/building epoch.
- Treat population surfaces as modeled estimates, not observed people.
- For building vectors, filter by AOI and confidence before any heavy operation.
- Summarize exposure with `pixelArea`, population sum, or feature counts; export
  tables rather than downloading large collections.

## Land Cover And DEM Products

ESA WorldCover (`ESA/WorldCover/v200`) is categorical 10 m land cover. Use
class palettes, legends, grouped area reducers, and `mode()` for aggregation.

Copernicus DEM GLO-30 (`COPERNICUS/DEM/GLO30`) is a 30 m DEM. Terrain products
are projection-sensitive; preserve or explicitly set an appropriate projection
for slope/aspect/hillshade workflows.

## Scale And Projection Checklist

- Reducers and exports must specify `scale` or a justified `crs` /
  `crsTransform`.
- `Map.addLayer()` scale comes from zoom level and is a visualization request.
  It does not prove reducer/export scale.
- Composites/mosaics can have a default WGS84 1-degree projection until an
  output request determines the working scale/projection.
- Use `reproject()` sparingly. It can force excessive computation when viewed
  over large extents. Prefer specifying `scale`, `crs`, or `crsTransform` on
  the actual reducer/export.
- For exact grid alignment, use `crs` plus `crsTransform`; `scale` alone can
  choose a grid origin that is unsuitable for pixel-perfect comparisons.
