# Chapter 6: Preparing Training Data

## Core idea

Training data quality is a spatial pipeline: align imagery and labels, convert labels into the representation expected by the task, tile without losing context, split without leakage, and visually audit the result.

## Single-image pipeline

1. Download raster and vector/mask labels.
2. Inspect an overlay and label coverage.
3. Rasterize vector labels against the reference raster.
4. Export image/mask chips with shared georeferencing.
5. Display an overview and random tiles.
6. Split by scene/region/date where possible.

```python
geoai.vector_to_raster(vector_path, "labels.tif", reference_raster=raster_path)
geoai.export_geotiff_tiles(
    in_raster=raster_path,
    out_folder="output",
    in_class_data=vector_path,
    tile_size=512,
    stride=384,
    buffer_radius=0,
    create_overview=True,
)
```

`stride < tile_size` creates overlap. Start with 512-pixel tiles and 50% overlap (`stride=256`) when object scale and GPU memory allow; change them after observing edge/context trade-offs.

## Batch pairing methods

`export_geotiff_tiles_batch` supports a single vector file covering all images, masks matched by sorted order, or masks matched by filename (`match_by_name=True`). Choose filename matching when names carry reliable scene identity. Check the returned counts for processed pairs, total tiles, and tiles containing features.

## Frameworks introduced

- **Alignment before augmentation**: a perfectly formatted but shifted label is worse than a smaller dataset with verified overlap.
- **Context–memory trade-off**: larger tiles preserve context but reduce batch size; smaller tiles increase samples but truncate objects.
- **Label-quality loop**: visualize → inspect empty/edge/ambiguous labels → correct/rerun → only then train.

## Dataset organization

Keep `images/`, `labels/` or `masks/`, a manifest, and separate train/validation/test directories or scene IDs. Record tile size, stride, CRS, transform, class mapping, nodata/background, and whether empty tiles were skipped. `skip_empty_tiles=True` improves efficiency but can distort class balance if negative context matters.

## Anti-patterns

- **Randomly splitting adjacent chips from one scene**: produces optimistic validation because neighboring pixels leak.
- **Mixing filename pairing conventions**: images and masks silently mismatch.
- **Discarding empty tiles without checking prevalence**: the model may never learn background diversity.
- **Using `all_touched` or buffer radius without documenting it**: label boundaries and class balance change.

## Key takeaways

1. The reference raster defines grid, CRS, and transform.
2. Tiling parameters are modeling decisions, not mere preprocessing.
3. Inspect overview plus random positive/negative/edge chips before training.

## Connects to

- **Ch03**: raster/vector/annotation formats.
- **Ch07–Ch13**: task-specific datasets.
- **Ch22–Ch23**: the same logic in QGIS panels.
