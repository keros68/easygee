# Chapter 14: SAM for Geospatial Applications

## Core idea

Segment Anything enables rapid object extraction from geospatial imagery through text, point, box, and batch prompts. It reduces task-specific labeling, but the prompt and model output remain hypotheses that need spatial QA.

## Setup and first mask

The book uses `geoai-py` plus `segment-geospatial[samgeo3]` and supports Hugging Face-backed checkpoints. A minimal geospatial flow is:

```python
from samgeo import SamGeo3, download_file
sam = SamGeo3(backend="meta", load_from_HF=True)
sam.set_image(image_path)
sam.generate_masks(prompt="building")
sam.save_masks("building_masks.tif", unique=True)
```

Use `save_scores` when confidence inspection matters. Keep model backend, checkpoint/access method, prompt, CRS, and image preprocessing with the output.

## Prompt selection

- **Text prompt**: fast exploratory extraction of a semantic object class.
- **Point prompt**: precise instance seed; positive points include, negative points exclude.
- **Box prompt**: constrain a known object/region; geographic boxes need `box_crs`.
- **Batch point/box prompt**: apply labeled vector locations or boxes across a raster/patch.
- **Tiled segmentation**: use `generate_masks_tiled` for large rasters; set tile size, overlap, min object size, and output dtype deliberately.
- **Video**: initialize a video model, prompt objects, propagate, inspect frames, and save masks/video; remove or refine bad object IDs.

## Frameworks introduced

- **Prompt → inspect → save score/ID → vectorize → regularize → validate**.
- **Weakest sufficient prompt**: start with text for discovery, add points/boxes for precision, and use supervised training when prompts are too unstable.
- **Geospatial coordinate discipline**: pixel coordinates and geographic coordinates are different; always declare CRS for geographic prompts.

## Post-processing

Use `raster_to_vector` to create polygons and `regularize`/`smooth_vector` for usable geometry. Filter tiny artifacts or holes with explicit thresholds. Compare masks to imagery and known labels; inspect false positives from roofs, roads, shadows, and water.

## Anti-patterns

- **Assuming a text prompt is a class definition** across sensors and geographies.
- **Mixing pixel and longitude/latitude coordinates**.
- **Running full-scene tiled inference before validating one tile**.
- **Publishing masks without model/prompt/threshold provenance**.

## Key takeaways

1. Use SAM for fast baselines and annotation assistance, not automatic truth.
2. Save scores, IDs, raw masks, and prompt metadata.
3. Increase prompt specificity or switch to supervised training when errors are systematic.

## Connects to

- **Ch03, Ch06**: CRS and tiling.
- **Ch09–Ch10**: semantic/instance output semantics.
- **Ch21**: the same methods through QGIS.
