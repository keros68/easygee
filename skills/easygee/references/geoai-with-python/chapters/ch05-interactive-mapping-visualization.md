# Chapter 5: Interactive Mapping and Visualization

## Core idea

Visualization is an evidence step: use interactive maps to inspect data alignment, compare bands/dates, find artifacts, and communicate model outputs—not just to make a final figure.

## Core workflow

```python
import leafmap
m = leafmap.Map(center=[36.16, -115.15], zoom=11)
m.add_basemap("Esri.WorldImagery")
m.add_raster(image_path, layer_name="Imagery")
m
```

Use `add_raster` for local GeoTIFFs, `add_cog_layer` for remote COGs, `add_gdf`/`add_geojson` for vector overlays, and `split_map` for side-by-side comparison. For multispectral data, select band indexes explicitly and apply a documented stretch or colormap; a display composite is not a change to the source raster.

## Frameworks introduced

- **Three-map QA**: source imagery alone → labels/predictions over source → split/side-by-side comparison.
  - Use it before training, after inference, and after vectorization.
- **Visual contract**: every output should answer “where is it?”, “what does the value mean?”, and “how does it compare with the source?”
- **Exploration before narrative**: inspect raw distributions, nodata, contrast, and scale before styling.

## Methods and patterns

- `geoai.view_raster` / `geoai.view_vector` for quick static checks.
- `geoai.view_vector_interactive(..., tiles=raster_path)` to verify geometry placement.
- `geoai.create_split_map` to compare a prediction/vector with imagery.
- `m.add_raster(..., indexes=[4, 1, 2])` for false color when the sensor supports it.
- `m.add_raster(..., vmin=..., vmax=..., colormap=...)` for continuous values or masks.
- `m.add_raster(..., nodata=0, opacity=...)` so masks do not hide the source.

## Model-result QA

For classification, inspect representative correct/incorrect predictions and a confusion matrix. For detection, overlay boxes and examine crowded, tiny, and edge objects. For segmentation, inspect raw mask, probability/score, vectorized geometry, and filtered geometry. For regression, compare raster, scatter plot, residuals, and valid-range mask. For change detection, inspect both dates, difference distribution, threshold, and change polygons.

## Anti-patterns

- **Using a basemap as evidence of model truth**: web basemaps may be different dates/resolutions.
- **Stretching each image independently without recording it**: visual differences can be introduced by display settings.
- **Only viewing a zoomed-in success case**: always sample full-scene and boundary/edge cases.

## Key takeaways

1. Overlay checks catch CRS and transform problems early.
2. Split maps expose false positives and temporal/sensor mismatch.
3. Keep visualization parameters with the result metadata.

## Connects to

- **Ch03–Ch04**: inspect acquired data.
- **Ch06**: validate chips and labels.
- **Ch09–Ch16**: evaluate model outputs spatially.
