# Chapter 15: Vision-Language Models

## Core idea

Vision-language models combine image understanding with natural-language prompts. In the book, `MoondreamGeo` supports captions, visual question answering, object detection, and point localization, while GeoAI maps returned geometries back onto imagery.

## Basic workflow

```python
from geoai import MoondreamGeo
processor = MoondreamGeo(
    model_name="vikhyatk/moondream2",
    revision="2025-06-21",
)
caption = processor.caption(image_path, length="normal")
answer = processor.query("How many buildings are in the image?", image_path)
```

Use short/normal/long captions as a controlled comparison. For object detection or point localization, inspect the returned GeoDataFrame/coordinates on a map; the model’s language output alone is not a spatial measurement.

## Scaling beyond one image

Large rasters require sliding-window analysis. Choose tile size and overlap, run caption/query/detection per window, translate local coordinates to the source CRS, and merge/deduplicate results. Compare regular and sliding-window behavior on a known test image before scaling.

## CLIP-based segmentation

The book also uses `geoai.CLIPSegmentation(tile_size=512, overlap=32)` with a text prompt, threshold, and smoothing sigma. Treat the threshold as a calibration parameter and compare masks with reference samples.

## Frameworks introduced

- **Question → evidence loop**: ask a narrow question, inspect answer/geometry, ask a follow-up or refine window, then validate.
- **Windowed VLM**: split large imagery, preserve local-to-global coordinates, merge results, and inspect duplicate/edge detections.
- **Language is an interface, not a metric**: convert answers into explicit labels/geometries before analysis.

## Limitations

VLMs may hallucinate counts, confuse visually similar objects, fail on tiny/occluded features, or change behavior with crop/scale. They can be useful for triage, annotation suggestions, or exploratory interpretation; quantitative claims need reference data.

## Anti-patterns

- **Using one caption as a land-cover inventory**.
- **Ignoring coordinate conversion in windowed detection**.
- **Treating point/box output as ground truth without sampling validation**.

## Key takeaways

1. Keep prompts and model revision with results.
2. Use sliding windows for large scenes and merge geometries carefully.
3. Validate language-derived objects like any other model output.

## Connects to

- **Ch05**: map and overlay QA.
- **Ch14**: prompt-based segmentation.
- **Ch20**: QGIS VLM panel.
