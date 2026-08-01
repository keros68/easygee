# Chapter 3: Geospatial Data Essentials

## Core idea

A GeoAI input is not merely an image array. The model and every output depend on raster dimensions, band semantics, dtype/scaling, nodata, transform, bounds, CRS, resolution, and compatible labels.

## Data contracts

- **Raster**: GeoTIFF/COG, multispectral or hyperspectral bands, resolution, CRS, transform, nodata, and value range.
- **Vector**: GeoJSON, GeoParquet, Shapefile, or other features with geometry, attributes, and CRS.
- **Annotations**: COCO/YOLO/Pascal VOC for detection/instance tasks; aligned raster masks for segmentation.
- **Tiles**: chips need georeferencing and matching image/label extents. Tile size should cover the object context without exceeding memory.

Inspect before modeling:

```python
import rasterio
with rasterio.open(raster_path) as src:
    print(src.height, src.width, src.count, src.crs, src.res, src.nodata)
```

For vectors, inspect `gdf.crs`, geometry validity, feature count, bounds, and class distribution. Reproject vectors to the raster CRS before overlay or rasterization.

## Frameworks introduced

- **Reference-grid principle**: the raster grid is the authority for rasterized labels and model outputs.
  - Use it whenever vector labels and imagery meet.
  - How: reproject → rasterize with the raster transform → overlay-check → tile together.
- **Spatial resolution principle**: a feature must occupy enough pixels to be learnable; increasing model complexity cannot recover information absent from the sensor.
- **Nodata is not background**: keep invalid/unknown pixels separate from a real negative class.

## Practical operations

`geoai.print_raster_info` and `geoai.print_vector_info` provide quick inspection. `leafmap.reproject` handles raster reprojection; `gdf.to_crs(...)` handles vector reprojection. `geoai.clip_raster_by_bbox` can create a small test window. `leafmap.split_raster` or `geoai.export_geotiff_tiles` creates chips while preserving georeferencing.

Choose projected CRS for area/length calculations. Use geographic CRS for longitude/latitude exchange and web maps, but do not measure meters directly in degrees.

## Anti-patterns

- **Overlaying layers with different CRS and trusting the display**: reprojection can hide a label/data mismatch.
- **Assuming band 1 is always red**: band order differs by product; record a named mapping.
- **Tiling without overlap or context**: objects at tile edges are truncated and predictions become seam-heavy.

## Key takeaways

1. Inspect metadata and an overlay before training.
2. Treat CRS, transform, band order, and nodata as model inputs.
3. Preserve georeferencing through chips and outputs.

## Connects to

- **Ch04–Ch05**: acquisition and visual QA.
- **Ch06**: rasterization, tiling, and split design.
- **Ch09–Ch10**: vectorization and geometric properties.
