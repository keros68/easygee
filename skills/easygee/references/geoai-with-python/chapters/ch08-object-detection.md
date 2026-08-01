# Chapter 8: Object Detection

## Core idea

Object detection predicts class, bounding box, and confidence for each object. It is appropriate when object location is needed but pixel-accurate boundaries are not the primary output.

## Frameworks introduced

- **Detector families**: two-stage detectors (proposal then classification/refinement), single-stage detectors (speed), transformer-based detectors (global attention), and zero-shot detectors (prompted/open vocabulary).
- **Detection evaluation**: IoU defines overlap; precision/recall and mAP summarize confidence-ranked detections across classes/thresholds.

## Training workflow

The book uses NWPU-VHR-10 and converts/prepares it through `prepare_nwpu_vhr10`:

```python
splits = geoai.prepare_nwpu_vhr10(data_dir, val_split=0.2, seed=42)
model_path = geoai.train_multiclass_detector(
    images_dir=splits["images_dir"],
    annotations_path=splits["train_annotations"],
    output_dir="nwpu_output",
    model_name="fasterrcnn_resnet50_fpn_v2",
    class_names=splits["class_names"],
    num_channels=3,
    batch_size=4,
    num_epochs=10,
    learning_rate=0.005,
    pretrained=True,
    seed=42,
)
```

Visualize COCO annotations before training. Evaluate with `evaluate_multiclass_detector`; keep background excluded from class metrics when the API expects it. For large rasters, `multiclass_detection` uses `window_size`, `overlap`, `confidence_threshold`, and `batch_size`; then inspect overlays and batch results.

## Key concepts

- **Annotation format**: COCO is useful for multi-class boxes and evaluation; preserve image IDs and coordinate conventions.
- **Small objects**: require sufficient source resolution and a window/resize strategy that preserves pixels.
- **Confidence threshold**: trades recall for precision; choose using validation curves, not habit.
- **NMS/duplicate handling**: overlapping windows can produce repeated boxes.

## Mental models

Use detection when the downstream operation is counting, locating, or cropping objects. Use instance segmentation when object shape, area, perimeter, or overlap matters.

## Anti-patterns

- **Training on uninspected boxes**: coordinate or class-index errors can yield a model that learns nothing.
- **Relying on a single confidence threshold** across sensors/regions.
- **Evaluating only full-scene averages**: inspect tiny, crowded, occluded, and tile-edge objects.

## Key takeaways

1. Verify annotations visually before training.
2. Report mAP/precision/recall with IoU assumptions and per-class errors.
3. Treat window size, overlap, and threshold as part of inference configuration.

## Connects to

- **Ch06**: tiling and split leakage.
- **Ch10**: per-object masks.
- **Ch18, Ch20, Ch23**: QGIS and instance-oriented workflows.
