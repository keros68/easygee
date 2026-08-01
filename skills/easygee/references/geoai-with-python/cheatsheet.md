# GeoAI with Python — quick reference

## Route the problem

| Question | Use |
|---|---|
| Whole image class? | recognition |
| Where are objects? | detection |
| Which class is each pixel? | semantic segmentation |
| Which pixels belong to each individual object? | instance segmentation |
| What changed between dates? | change detection |
| What continuous value occurs at each pixel? | regression |
| Few labels, new object? | SAM/VLM/embeddings baseline |

## Preflight

`raster shape / bands / dtype / nodata / CRS / resolution / bounds`  
`label CRS / geometry / class field / coverage`  
`band order and value scaling`  
`tile_size, stride/overlap, batch_size, train-val-test split`  
`output CRS, nodata, vectorization/filtering rules`

## Common GeoAI defaults from the book

- Training tiles: `tile_size=512`; use `stride=256` for 50% overlap as a starting point.
- Windowed inference: `window_size=512`, overlap `128–256`; lower batch size before reducing spatial context.
- Segmentation baseline: U-Net + `resnet34`, ImageNet encoder, `num_classes` matching labels.
- Detection baseline: Faster R-CNN + `resnet50_fpn_v2`, confidence threshold around `0.5`; report mAP and visual errors.
- Regression: mask invalid targets, keep target range (NDVI often `[-1, 1]`), report MAE/RMSE/R² and residual maps.
- Vector cleanup: save raw mask first; then remove tiny areas, smooth/regularize, add area/length, and inspect overlays.

## Failure triage

1. Import/CUDA error → verify Python, package versions, `torch.cuda.is_available()`, and model access.
2. Empty/shifted labels → inspect CRS, transform, bounds, rasterization, and band order.
3. OOM → lower `batch_size`, window/tile size, or use CPU; clear cache between large models.
4. Seams/duplicate objects → increase overlap, deduplicate, or use tiled/batch API.
5. Bad generalization → split by scene/region, inspect sensor/resolution mismatch, add labels or calibrate thresholds.
6. Noisy polygons → preserve probability/score, remove small artifacts, smooth/regularize, and validate against imagery.
