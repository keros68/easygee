# Chapter 22: Semantic Segmentation in QGIS

## Core idea

The panel provides a no-code training-to-inference route for pixel-level classes. The same contracts as Python still apply: aligned imagery/labels, model/channel configuration, spatial splits, tiled inference, and vector post-processing.

## Execution method

1. Choose sample raster and vector/raster labels.
2. Set tile size, stride, buffer, and output directory; inspect generated chips.
3. Select images/labels directories and class mapping.
4. Choose architecture (for example U-Net, DeepLabV3+, or SegFormer) and encoder/backbone.
5. Set epochs, batch size, learning rate, validation split, and device.
6. Train a small test run; inspect curves and validation predictions.
7. Configure inference raster/model, window/overlap, batch size, and output path.
8. Vectorize and apply smoothing/area filters only after checking the raw mask.

## Frameworks introduced

- **GUI equivalent of the Python pipeline**: create tiles → train → evaluate → infer → vectorize → filter.
- **Architecture/backbone separation**: record both, because changing either changes the learned model.
- **Geographic transfer test**: run on a different region/sensor/date before claiming generalization.

## Troubleshooting

- Empty labels or shifted masks → CRS, rasterization, and tile alignment.
- Training fails immediately → dependency/device/model configuration.
- CUDA out of memory → smaller batch/tile/window or CPU.
- Plausible but poor output → wrong band count/order, class mapping, label quality, or geographic shift.
- Noisy vectors → inspect raw mask, minimum area, smoothing, and simplification.

## Anti-patterns

- **Selecting an architecture before checking label semantics**.
- **Using a random chip split from one scene as geographic validation**.
- **Exporting only final polygons** and losing probability/mask evidence.

## Key takeaways

1. The GUI hides code, not the need for data contracts.
2. Record every panel setting needed to reproduce a run.
3. Validate on a region outside the training footprint.

## Connects to

- **Ch06, Ch09**: tile/train/infer methods.
- **Ch17**: plugin environment.
- **Ch23**: instance-level alternative.
