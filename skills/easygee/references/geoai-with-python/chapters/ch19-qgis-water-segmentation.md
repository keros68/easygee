# Chapter 19: Water Segmentation in QGIS

## Core idea

The Water Segmentation panel provides a sensor-aware route for water-body extraction, using OmniWaterMask-style inference, patch processing, optional OpenStreetMap context, and raster/vector export.

## Execution method

1. Load the input raster and verify sensor, CRS, resolution, and band values.
2. Select the input raster in the panel and configure band ordering for that sensor (for example, Sentinel-2 vs. NAIP).
3. Set patch size/stride or overlap and start with a small region.
4. Optionally use OSM water features as contextual refinement or comparison, not as automatic ground truth.
5. Run segmentation and inspect mask overlay.
6. Export raster and/or vector; apply minimum area, smoothing, and simplification only after reviewing raw output.

## Frameworks introduced

- **Band-order gate**: a water model with wrong bands can fail plausibly; confirm channel mapping before tuning.
- **Permanent vs. temporary water**: seasonal ponds, flood water, shadows, and wetlands need application-specific interpretation.
- **Mask → polygon → measurement**: keep raw mask, cleaned vector, area statistics, and filtering thresholds distinct.

## Practical considerations

Patch-based inference trades context for memory. Use overlap to reduce edge effects. Common failures include wrong band order, clouds/shadows, sensor mismatch, small artifacts, and interpreting OSM coverage as complete.

## Anti-patterns

- **Using RGB order for a multispectral sensor without checking the panel mapping**.
- **Filtering small water bodies without documenting the minimum area**.
- **Treating OSM as a temporally matched reference layer**.

## Key takeaways

1. Band configuration is the first diagnostic.
2. Validate both permanent and temporary/ambiguous water cases.
3. Export raw and post-processed results with parameters recorded.

## Connects to

- **Ch09**: supervised water/semantic segmentation.
- **Ch04–Ch05**: data and map QA.
- **Supplement**: cross-panel QGIS sequence.
