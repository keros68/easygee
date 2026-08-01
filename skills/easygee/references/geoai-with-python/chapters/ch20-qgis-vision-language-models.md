# Chapter 20: Vision-Language Models in QGIS

## Core idea

The VLM panel makes image captioning, visual question answering, object detection, and point localization available to GIS users through a GUI. The output still needs spatial and semantic validation.

## Execution method

1. Load a raster with a clear geographic extent.
2. Load the Moondream model and wait for dependency/checkpoint initialization.
3. Generate short/normal/long captions to understand scene context.
4. Ask narrow questions whose answers can be checked visually.
5. Run object detection or point localization for candidate features.
6. Overlay returned boxes/points on the raster, inspect false positives, and export only after review.

## Frameworks introduced

- **GUI query loop**: load → caption → ask → detect/locate → overlay → refine question/window.
- **Text-to-geometry discipline**: natural-language output becomes useful GIS data only after conversion to explicit point/box/vector objects and coordinate checks.

## Tips and limitations

Use concise prompts, compare output at different image scales, and split large rasters when necessary. VLMs may hallucinate counts or misread tiny/occluded features; captions are not inventories, and detected points are not survey-grade coordinates.

## Anti-patterns

- **Using a caption as a formal land-cover classification**.
- **Accepting a detected object without looking at its location on the source raster**.
- **Assuming GUI defaults reproduce a Python run** without recording model revision, window, prompt, and threshold.

## Key takeaways

1. Ask questions that can be checked against the imagery.
2. Treat detection/point output as candidate GIS features.
3. Record prompts and panel settings for reproducibility.

## Connects to

- **Ch15**: programmatic Moondream/CLIP methods.
- **Ch05**: overlay and split-map QA.
- **Ch21**: prompted segmentation for precise masks.
