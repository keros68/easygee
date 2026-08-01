# Chapter 9: Semantic Segmentation

## Core idea

Semantic segmentation predicts a class for every pixel. The book’s reusable route is aligned labels → tiled training data → U-Net/encoder model → windowed inference → probability/mask QA → vectorization and geometry filtering.

## Supervised method

```python
geoai.export_geotiff_tiles(
    in_raster=train_raster_path,
    out_folder="buildings",
    in_class_data=train_vector_path,
    tile_size=512,
    stride=256,
)
geoai.train_segmentation_model(
    images_dir="buildings/images",
    labels_dir="buildings/labels",
    output_dir="buildings/unet_models",
    architecture="unet",
    encoder_name="resnet34",
    encoder_weights="imagenet",
    num_channels=3,
    num_classes=2,
    batch_size=8,
    num_epochs=20,
    learning_rate=0.001,
    val_split=0.2,
)
```

Run `geoai.semantic_segmentation` with the same architecture, encoder, channels, and classes. For large rasters, use `window_size` and `overlap`; save `probability_path` when threshold or uncertainty analysis is important. For batches, use `semantic_segmentation_batch`.

## Seven-task segmentation examples

- **Buildings**: vector labels → mask → polygons → `orthogonalize`/geometric properties.
- **Water**: binary masks or `segment_water`/OmniWaterMask with sensor-specific band order.
- **Clouds/shadows**: categorical mask, statistics, cleanup, vectorization, cloud-free mask.
- **Land cover**: multi-class mask and legend/colormap preservation.
- **Multispectral transfer**: train with matching channel count and sensor scaling; inspect false-color composites.

## Frameworks introduced

- **Mask-to-map ladder**: inspect source → raw mask → probability → cleaned mask → vector → filtered geometry.
- **Architecture/encoder separation**: U-Net/DeepLabV3+ defines decoder/task shape; encoder/backbone supplies transferable features.
- **Sensor-agnostic claim test**: a model is not sensor-agnostic until band order, scaling, resolution, and geography are validated.

## Post-processing

Use `raster_to_vector`, `smooth_vector`, `orthogonalize`, and `add_geometric_properties` only after inspecting the raw mask. Filter by area/shape with thresholds tied to the application; save both raw and filtered outputs.

## Anti-patterns

- **Using RGB configuration for a six-band model** or silently swapping bands.
- **Calling a probability map a class mask** without thresholding/legend semantics.
- **Vectorizing speckle before cleanup**: produces unusable polygons.

## Key takeaways

1. Match train and inference channels/architecture exactly.
2. Save probabilities when decisions depend on threshold.
3. Validate masks and vectors against imagery and known geometry.

## Connects to

- **Ch03, Ch06**: alignment and tiling.
- **Ch10**: instance-level alternative.
- **Ch19, Ch22**: water and QGIS implementations.
