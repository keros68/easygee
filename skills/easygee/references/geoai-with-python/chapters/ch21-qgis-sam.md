# Chapter 21: Segment Anything in QGIS

## Core idea

The SAM panel exposes text-prompted, point-prompted, box-prompted, interactive, and batch segmentation without requiring Python. It is a practical annotation/rapid-extraction interface, not a replacement for checking prompt semantics and output quality.

## Execution method

1. Load imagery and a map canvas that makes the target object visible.
2. Load an accessible SAM model/checkpoint.
3. Start with a text prompt for broad discovery, or points/boxes when the target instance is known.
4. Inspect the mask and, for ambiguous objects, add positive/negative points or refine the box.
5. For batches, use georeferenced points/boxes and confirm CRS/coordinate interpretation.
6. Export raster masks and/or vectors; regularize, simplify, and area-filter only after preserving the raw result.

## Frameworks introduced

- **Prompt specificity ladder**: text → point → positive/negative points → box → batch geometry.
- **Interactive correction loop**: prompt → inspect → refine → compare → export.
- **Batch provenance**: input feature ID, prompt type, CRS, model, output dtype, and post-processing must travel with the result.

## Practical considerations

Large rasters need tiling or batch processing; processing many objects can be memory-intensive. Polygon regularization/simplification changes geometry—keep tolerances explicit and retain the original mask/vector.

## Anti-patterns

- **Mixing screen/pixel coordinates with geographic coordinates**.
- **Using one successful prompt as evidence the model generalizes**.
- **Simplifying polygons before measuring sensitivity to the raw mask**.

## Key takeaways

1. Choose prompt type based on what is known about the object.
2. Use interactive refinement for ambiguous/overlapping features.
3. Preserve raw outputs and all prompt/model metadata.

## Connects to

- **Ch14**: programmatic SAM methods.
- **Ch10, Ch23**: instance-level geometry.
- **Ch06**: SAM outputs can become reviewed training labels.
