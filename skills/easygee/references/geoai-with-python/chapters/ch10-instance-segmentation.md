# Chapter 10: Instance Segmentation

## Core idea

Instance segmentation combines object localization and pixel masks: each object gets an instance ID, class label, score, and shape. It is appropriate for per-object measurement, counting, or overlapping features.

## Frameworks introduced

- **Mask R-CNN pipeline**: backbone encoder → region proposal network → detection head → mask head → RoI Align for spatial precision.
- **Instance output contract**: keep instance-ID raster, class-label raster, score raster, and vector geometries distinct.

## Training workflow

The FTW example downloads field-boundary data, prepares it, and trains a two-class four-channel model:

```python
geoai.download_ftw(countries=["luxembourg"], output_dir="ftw_data")
data = geoai.prepare_ftw("ftw_data", country="luxembourg")
geoai.train_instance_segmentation_model(
    images_dir=data["images_dir"],
    labels_dir=data["labels_dir"],
    output_dir="field_boundaries/models",
    num_classes=2,
    num_channels=4,
    batch_size=4,
    num_epochs=20,
    learning_rate=0.005,
    val_split=0.2,
    instance_labels=True,
)
```

Inference returns separate artifacts when `vectorize=True`:

```python
result = geoai.instance_segmentation(
    input_path=test_image_path,
    output_path="field_boundary_prediction.tif",
    model_path="field_boundaries/models/best_model.pth",
    num_classes=2, num_channels=4,
    window_size=256, overlap=128,
    confidence_threshold=0.5, vectorize=True,
    class_names=["background", "building"],
)
```

Clean masks with `clean_instance_mask`, vectorize, add area/length/elongation, and inspect per-object distributions. Use `instance_segmentation_batch` for repeated test images.

## Mental models

Use **semantic segmentation** when class coverage is the target; use **instance segmentation** when identity and per-object geometry are the target. Think of `confidence_threshold`, `min_area`, and hole filtering as an application-specific measurement policy, not a universal truth.

## Anti-patterns

- **Collapsing instance IDs into a binary mask too early**: loses count and object-level analysis.
- **Calling every connected component an object**: touching objects and model errors require inspection.
- **Comparing masks without matching confidence/area filters**: post-processing changes the result.

## Key takeaways

1. Preserve instance, class, score, and vector outputs separately.
2. Evaluate object-level precision/recall and geometry, not only pixel overlap.
3. Use overlap and cleanup carefully for large scenes.

## Connects to

- **Ch08**: boxes and confidence thresholds.
- **Ch09**: semantic vs. instance choice.
- **Ch23**: QGIS Mask R-CNN workflow.
