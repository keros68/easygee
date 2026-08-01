# Temporal Compositing And Time-Series Semantics

Use this reference when an Earth Engine workflow calls `median()`, `mean()`,
`mosaic()`, `qualityMosaic()`, builds monthly/seasonal composites, or extracts
a time series. The output may look like one image while its pixels come from
different observations and dates.

## Choose the operation by meaning

| Operation | Pixel source | Appropriate use | Main caveat |
|---|---|---|---|
| `median()` / `mean()` | Per-band statistic across valid observations at each pixel | Robust seasonal background or interval summary | Output is synthetic and bands need not equal one observed spectrum |
| percentile/min/max | Per-band statistic at each pixel | Distribution envelope or documented extreme | Outliers and incomplete QA can dominate |
| `mosaic()` | Last valid pixel in collection order | Spatial assembly or explicit priority stack | Collection order is the rule; it is not a quality score |
| `qualityMosaic(q)` | All bands from the image with maximum `q` at each pixel | Best-pixel, greenest-pixel, or most-recent composite | Pixels can have different source dates; poor quality definitions create bias |
| image-to-feature series | One statistic per image/date/zone | Trend, phenology, event timing | Missing/irregular observations must remain visible |

Earth Engine collection reducers are pixel-wise. A median RGB composite can
combine different dates and even different contributing observations among
bands; it should not be described as a real acquisition.

## Required QA diagnostics

Always carry a valid-observation count with a composite:

```python
masked = collection.map(mask_and_scale)
median = masked.select(target_bands).median()
valid_count = masked.select(target_bands[0]).count().rename("valid_obs")
result = median.addBands(valid_count)
```

For a quality mosaic, preserve the selected source time:

```python
def add_source_time(image):
    time = ee.Image.constant(image.date().millis()).toDouble().rename("source_time")
    return image.addBands(time)

best = collection.map(add_source_time).qualityMosaic("quality")
```

Display or summarize `valid_obs` and `source_time`. A clean-looking composite
with one valid observation is not equally supported as a pixel with twenty.

## Periodic composites

For monthly, seasonal, or annual series:

1. Define half-open intervals `[start, end)` and attach interval start/end to
   each output.
2. Apply sensor scaling and pixel QA before reduction.
3. Record source image count and per-pixel valid count.
4. Keep empty intervals as explicit missing values rather than silently
   dropping them when cadence matters.
5. Use the same interval definition, reducer, bands, scale, and zone geometry
   across comparison periods.

Do not interpolate or smooth until the missing-data rule is explicit. A
smoothed phenology curve is a model of observations, not a recovered sequence
of cloud-free acquisitions.

## Bias checks

- Greenest-pixel composites can select residual cloud/haze or favor different
  phenological dates. Combine the quality rule with a cloud mask and preserve
  source date.
- Mean composites are sensitive to residual contamination; median composites
  reduce outlier influence but can suppress short events.
- A before/after comparison needs matched seasons and comparable valid counts.
- Mixed sensors need `cross-sensor-harmonization.md`; temporal compositing does
  not itself harmonize sensors.
- Classification validation should use spatially independent holdout blocks
  when nearby train/test samples would leak spatial autocorrelation.

## Reporting minimum

State the interval, reducer or ordering rule, QA mask, scale/projection,
observation-count diagnostic, source-date behavior, and treatment of empty
intervals. Call the result a composite, summary, or modeled series—not a
single-date cloud-free observation.

Official reducer, compositing, mosaicking, and `qualityMosaic()` sources are
listed in `SOURCES.md`.
