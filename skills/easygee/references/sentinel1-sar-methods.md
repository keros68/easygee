# Sentinel-1 SAR Method Boundaries

Use this compact reference for Sentinel-1 GRD filtering, pre/post comparison,
flood mapping, speckle handling, and terrain caveats in Earth Engine.

## What Earth Engine already provides

`COPERNICUS/S1_GRD` contains calibrated, ortho-corrected GRD backscatter in
decibels. Earth Engine preprocessing includes orbit information, noise
handling, radiometric calibration, terrain correction, and conversion to dB.
The collection is heterogeneous; preprocessing does not make all acquisitions
directly comparable. Radiometric terrain flattening is not applied by the
standard ingestion pipeline.

Do not apply another generic calibration or dB conversion to
`COPERNICUS/S1_GRD`. Use `COPERNICUS/S1_GRD_FLOAT` or an explicit dB-to-linear
conversion only when a method genuinely needs linear power.

## Homogeneous collection first

For common land applications, filter mode, polarization, resolution, pass,
and—when doing strict pre/post comparison—relative orbit:

```python
s1 = (
    ee.ImageCollection("COPERNICUS/S1_GRD")
    .filterBounds(roi)
    .filterDate(start, end)
    .filter(ee.Filter.eq("instrumentMode", "IW"))
    .filter(ee.Filter.eq("resolution_meters", 10))
    .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
    .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
    .filter(ee.Filter.eq("orbitProperties_pass", "DESCENDING"))
    .filter(ee.Filter.eq("relativeOrbitNumber_start", relative_orbit))
    .select(["VV", "VH", "angle"])
)
```

If one relative orbit does not cover the AOI or dates, analyze orbit groups
separately. Mixing ascending and descending views can make geometry look like
surface change.

## dB and linear arithmetic

- Difference in dB: `post_db.subtract(pre_db)` is the log-ratio expression.
- Ratio of dB numbers is not a physical power ratio.
- Convert to linear power with `10 ** (dB / 10)` when averaging/ratio methods
  require it, or use `COPERNICUS/S1_GRD_FLOAT`.
- State which domain a filter, average, threshold, or ratio uses.

```python
def db_to_power(image):
    return ee.Image(10).pow(image.divide(10))

delta_db = post_db.subtract(pre_db).rename("delta_db")
power_ratio = db_to_power(post_db).divide(db_to_power(pre_db)).rename("ratio")
```

## Speckle, angle, and terrain

- Multi-temporal median/mean over geometry-matched acquisitions is often a
  safer first speckle reduction than an undocumented spatial filter.
- Spatial filters trade noise reduction for boundary/detail loss. Name the
  filter, window, domain, and effect on resolution.
- The `angle` band is an approximate incidence angle from the ellipsoid. Use it
  to inspect/filter edge-angle effects, not as proof that local terrain effects
  are removed.
- Orthorectification does not remove layover, foreshortening, radar shadow, or
  slope-dependent backscatter. In mountains, add DEM-derived slope/aspect
  diagnostics and treat radiometric slope correction as a separate validated
  method choice.

## Flood/change decision rule

1. Build pre and post composites from the same mode, polarization, pass,
   relative orbit, seasonal context, and reducer.
2. Show pre, post, change metric, angle, and candidate mask layers.
3. Derive thresholds from local histograms/reference samples; a universal
   value such as `VV < -16 dB` is only a candidate.
4. Exclude or discuss permanent water, terrain shadow, wind-roughened water,
   vegetation, and urban double-bounce.
5. Report valid acquisition counts and validate against independent imagery or
   reference samples when accuracy is claimed.

SAR can observe through clouds, but it does not reconstruct optical color or
surface reflectance beneath a cloud. Treat optical/SAR fusion as a separate
modeling task with explicit target and validation.

Official Sentinel-1 GRD catalog and preprocessing sources are listed in
`SOURCES.md`.
