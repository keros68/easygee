# Chapter 1: Introduction to GeoAI

## Core idea

GeoAI is AI applied to data whose meaning depends on location, scale, coordinate systems, sensor properties, and time. The spatial context changes both the data contract and the failure modes: a model can be numerically accurate yet geographically misplaced or unable to transfer across sensors.

## Frameworks introduced

- **Seven core GeoAI tasks**: image recognition, object detection, semantic segmentation, instance segmentation, image translation, change detection, and pixel-level regression.
  - Use it to translate a user request into a model/output type.
  - How: classify the expected output first—one label, boxes, class mask, instance IDs, transformed raster, change map, or continuous raster.
- **Open-source GeoAI ecosystem**: PyTorch/torchvision for deep learning; rasterio/geopandas for data; leafmap for interactive maps; torchgeo for datasets; `geoai` for high-level workflows; segment-geospatial for SAM.

## Task routing

- Whole-image scene or land-use label → recognition.
- Individual objects with location and confidence → detection.
- A class per pixel, such as water or land cover → semantic segmentation.
- One mask per building/tree/field → instance segmentation.
- Low-resolution to high-resolution or one sensor/domain to another → image translation.
- Two dates or conditions → change detection; align first.
- Canopy height, NDVI, biomass, or population density → pixel regression.
- Little labeling and unfamiliar objects → SAM/VLM/embedding baseline, followed by validation.

## Key concepts

- **Spatial data is structured**: pixels have a grid, transform, CRS, resolution, bands, and nodata.
- **Scale matters**: object size relative to pixel size and tile size determines what a model can learn.
- **Transfer learning**: pre-trained visual features reduce data and compute requirements but do not remove domain shift.
- **Foundation model**: a broadly pre-trained model adapted through prompts or embeddings rather than task-specific training.

## Mental models

Use **output-first design**: decide what a downstream analyst must receive before choosing a network. Think of **geographic generalization** as a separate test from random validation; a random chip split can reward memorization of one scene.

## Anti-patterns

- **Calling every geospatial image task “classification”**: this hides whether spatial boundaries or object identity matter.
- **Ignoring sensor/domain shift**: RGB aerial data, multispectral Sentinel-2, and high-resolution commercial imagery are not interchangeable.
- **Using a foundation model as ground truth**: prompts provide hypotheses; validation still requires reference data.

## Key takeaways

1. Start from the desired geospatial output.
2. Carry spatial metadata through every stage.
3. Use high-level packages for speed, but inspect the underlying raster/vector result.

## Connects to

- **Ch03**: data contracts and CRS.
- **Ch07–Ch13**: supervised task methods.
- **Ch14–Ch16**: foundation-model alternatives.
