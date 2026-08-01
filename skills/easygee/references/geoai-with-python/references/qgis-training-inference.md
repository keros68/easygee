# Supplement: Training and Inference in QGIS

The repository contains `book/qgis/segmentation-plugin.md`, a compact page that is not listed among the current 23 chapters. Keep it as a cross-panel mental model rather than treating it as a separate formal chapter.

## Cross-panel sequence

1. Load a georeferenced raster and verify the visible extent.
2. Choose the panel that matches the output: semantic mask, instance objects, tree model, or water model.
3. For supervised work, create training tiles and labels in the same CRS/grid, choose architecture/backbone/hyperparameters, and train a small run.
4. Run inference on a small area first. Inspect raw output, then vectorize and export.
5. Record model, panel settings, tile size/stride, threshold, output CRS, and post-processing so the GUI run can be repeated.

## When panels overlap

- Semantic segmentation answers “what class is each pixel?”
- Instance segmentation answers “which pixels form each individual object?”
- DeepForest-style tree workflows are object detection/segmentation baselines for ecological features.
- OmniWaterMask is a specialized water extraction route; band order and sensor compatibility are decisive.

## Exercises to preserve as practice

Compare semantic vs. instance outputs on the same buildings, compare architectures, inspect tree-crown predictions, vary water-mask settings, and analyze how object-level outputs support counting or measurement.

Source: <https://github.com/giswqs/GeoAI-Book/blob/main/book/qgis/segmentation-plugin.md>
