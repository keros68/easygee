# Chapter 18: Tree Segmentation in QGIS

## Core idea

The Tree Segmentation panel applies pre-trained ecological object models to images and exports object-aware outputs. The method generalizes to related classes such as birds, livestock, nests, and dead trees only when sensor, scale, and ecology are compatible.

## Execution method

1. Load imagery and inspect resolution, CRS, season, and visible object scale.
2. Open the Tree Segmentation panel and load a suitable pre-trained model.
3. Choose single-image or large-tile prediction.
4. Configure tile/window size, overlap, confidence, and output options.
5. Run a small area; inspect predicted boxes/crown outlines over imagery.
6. Export vector results for counting/measurement, raster masks for map algebra, or training data for later supervised adaptation.

## Frameworks introduced

- **Sensor–model match**: resolution, spectral content, geography, ecology, and season jointly determine transfer quality.
- **Box vs. crown output**: boxes are robust for detection/counting; crown outlines are more useful for area/shape but can be more sensitive to segmentation errors.
- **Pre-trained → reviewed → adapted**: use the panel for a baseline, review false positives/negatives, export labels, then train a domain-specific model if necessary.

## Practical considerations

Season affects canopy appearance; geographic/ecological context affects what counts as a tree; large tiles improve context but increase memory/runtime. Compare a single image with a large tile and inspect tile-edge behavior.

## Anti-patterns

- **Assuming “tree” means the same object definition everywhere**.
- **Reporting counts without checking duplicate/overlapping detections**.
- **Exporting training data without manual review**.

## Key takeaways

1. Match model and imagery before tuning thresholds.
2. Choose output geometry based on the downstream measurement.
3. Use panel results as reviewed labels or a baseline, not unquestioned truth.

## Connects to

- **Ch08**: detection concepts and confidence.
- **Ch10**: instance geometry.
- **Ch22**: supervised semantic segmentation when pre-trained transfer fails.
