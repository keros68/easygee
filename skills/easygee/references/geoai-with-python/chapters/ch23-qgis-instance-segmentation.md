# Chapter 23: Instance Segmentation in QGIS

## Core idea

The Instance Segmentation panel trains and applies Mask R-CNN so each object receives an individual mask/label. Use it when per-object counting, area, shape, or overlap matters.

## Execution method

1. Load imagery and instance-level labels; choose PASCAL VOC-style annotations where required by the panel.
2. Configure tile size, stride, buffer radius, and export directory.
3. Select model configuration and number of classes/channels.
4. Set training hyperparameters and run a small training job.
5. Inspect metrics and sample predictions.
6. Run inference on a test raster with window/overlap and confidence threshold.
7. Preserve instance-level output, vectorize, clean/filter, and compute per-object properties.

## Frameworks introduced

- **Instance-vs-semantic decision**: semantic labels are sufficient for class coverage; instance labels are required for object identity and per-object measurement.
- **Per-object output chain**: Mask R-CNN prediction → instance IDs/classes/scores → vector geometries → area/shape/count statistics.
- **Confidence sensitivity**: compare object counts and geometry as the threshold changes; do not select it solely by visual appeal.

## Practical considerations

Tile size/stride/buffer affect partially visible objects. Large objects need context; crowded scenes need overlap and careful duplicate handling. PASCAL VOC/instance labels are not interchangeable with semantic masks.

## Anti-patterns

- **Treating instance IDs as class IDs**.
- **Comparing semantic and instance results with different thresholds/filters**.
- **Measuring area before checking CRS and geometry validity**.

## Key takeaways

1. Use instance labels and preserve object identity through export.
2. Validate confidence, duplicate handling, and geometry in map space.
3. Record model, channels, tiles, threshold, and post-processing.

## Connects to

- **Ch10**: Python Mask R-CNN workflow.
- **Ch22**: semantic segmentation contrast.
- **Supplement**: cross-panel training/inference practice.
