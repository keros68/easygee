# Patterns and methods

## End-to-end GeoAI workflow
**When to use**: Any new project.  
**How**: define target → acquire data → inspect metadata/overlays → align labels → tile/split → baseline → evaluate → spatialize → validate/export.  
**Trade-offs**: More checkpoints take time but prevent expensive training on invalid data.

## STAC-first acquisition
**When to use**: Satellite/aerial data with searchable metadata.  
**How**: open the catalog, select collection, search by bbox/date/cloud cover, inspect item assets, download only needed bands, record item ID/date/license.  
**Trade-offs**: More reproducible than ad-hoc downloads; endpoints and asset names vary by collection.

## Reference-grid label preparation
**When to use**: Vector labels plus raster imagery.  
**How**: reproject labels to the raster CRS, rasterize against the raster transform, overlay-check, then tile imagery and labels together.  
**Trade-offs**: Preserves alignment; small polygons can disappear if resolution is too coarse.

## Overlapping patch inference
**When to use**: Input is larger than GPU memory or model context.  
**How**: choose `window_size`, set `overlap`/stride, batch windows, stitch in the source grid, inspect seams and duplicate objects.  
**Trade-offs**: Better boundary quality, higher runtime and storage.

## Supervised segmentation baseline
**When to use**: You have labels and need repeatable domain-specific outputs.  
**How**: `export_geotiff_tiles` → `train_segmentation_model` → inspect `training_history.pth`/`best_model.pth` → `semantic_segmentation` → vectorize and filter.  
**Trade-offs**: More setup than a foundation model; offers clearer control over classes and validation.

## Prompted foundation-model extraction
**When to use**: Rapid extraction or weak/no labels.  
**How**: choose text/point/box prompt → generate mask → inspect score/ID → save raster → vectorize/regularize → sample-validate.  
**Trade-offs**: Fast and flexible, but prompt/model behavior can be unstable across sensors and geographies.

## Change-detection baseline ladder
**When to use**: Two dates need comparison.  
**How**: co-register and normalize → inspect band differences/histogram → threshold a simple difference → compare with ChangeStar/deep model → export change vectors.  
**Trade-offs**: Baseline is interpretable; deep models may improve robustness but add domain and compute requirements.

## Embedding-to-lightweight-model
**When to use**: Foundation embeddings are available but end-to-end fine-tuning is too expensive.  
**How**: spatially join labels to patches → split embeddings spatially/stratified → train kNN, random forest, or logistic regression → inspect PCA/similarity and held-out accuracy.  
**Trade-offs**: Efficient and easy to iterate; inherits the embedding model’s geography, sensor, and label limitations.

## QGIS no-code translation
**When to use**: GIS users need an operational workflow without Python.  
**How**: install GeoAI plugin/dependencies → load raster → choose panel → configure model/bands/tiles → run small test → inspect result → export raster/vector/training data.  
**Trade-offs**: Accessible and interactive; reproducibility requires recording panel settings and plugin/environment versions.
