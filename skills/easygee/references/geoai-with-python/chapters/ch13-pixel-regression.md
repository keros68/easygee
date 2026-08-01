# Chapter 13: Pixel-Level Regression

## Core idea

Pixel regression predicts a continuous surface rather than a discrete class. The NDVI example adapts a segmentation architecture, but the target range, invalid pixels, residuals, and temporal transfer determine whether the surface is useful.

## Workflow

1. Download input raster, target raster, and a held-out date/region.
2. Verify matching CRS/grid/extent and target band/range.
3. Create paired tiles with `create_regression_tiles`, filtering low valid ratios.
4. Split tiles by scene/date where possible.
5. Train a regressor and monitor loss/R².
6. Predict a georeferenced raster with overlap.
7. Evaluate with raster metrics, scatter/residual maps, and valid-range checks.

```python
image_paths, target_paths = geoai.create_regression_tiles(
    input_raster=train_raster,
    target_raster=train_target,
    output_dir="ndvi_tiles",
    tile_size=256,
    stride=128,
    target_band=1,
    min_valid_ratio=0.9,
)
model = geoai.train_pixel_regressor(
    train_image_paths=train_imgs,
    train_target_paths=train_tgts,
    val_image_paths=val_imgs,
    val_target_paths=val_tgts,
    encoder_name="resnet34",
    architecture="unet",
    in_channels=in_channels,
)
```

Use `geoai.predict_raster(..., clip_range=(-1.0, 1.0))`, then `plot_regression_comparison` and `plot_scatter`. Keep the target’s physical meaning and scaling in metadata.

## Frameworks introduced

- **Valid-range discipline**: mask invalid target pixels and constrain outputs to a physically meaningful range.
- **Regression evaluation triad**: aggregate metrics (MAE/RMSE/R²) + spatial residuals + temporal/geographic holdout.
- **Architecture reuse with changed head**: segmentation backbones can support regression, but loss/output activation must match the target.

## Anti-patterns

- **Randomly splitting overlapping tiles** and reporting inflated accuracy.
- **Clipping predictions silently**: it can hide systematic bias.
- **Using a visually smooth prediction as evidence of accuracy**.

## Key takeaways

1. Input and target alignment is a hard requirement.
2. Report both numeric error and where errors occur.
3. Test transfer to a new date/region before operational use.

## Connects to

- **Ch06**: paired tiling and splits.
- **Ch09**: segmentation architecture patterns.
- **Ch05**: raster/scatter/residual visualization.
