# Chapter 12: Change Detection

## Core idea

Change detection compares two observations to identify meaningful temporal differences. Registration, normalization, acquisition quality, and thresholding often matter as much as the model.

## Baseline ladder

1. Confirm both rasters cover the same area, grid, CRS, resolution, bands, and date semantics.
2. Compute a band/feature difference and inspect its histogram.
3. Set a threshold from validation data or a quantile, not from visual preference alone.
4. Compare the interpretable baseline with a deep model such as ChangeStar.
5. Vectorize/measure only after reviewing false changes from clouds, shadows, seasonal effects, and misregistration.

The book’s deep-learning route uses `ChangeStarDetection` and stores change, time-1 semantic, time-2 semantic, and vector outputs:

```python
detector = ChangeStarDetection(model_name="s1_s1c1_vitb")
result = detector.predict(
    naip_2019_path, naip_2022_path,
    output_change="changestar_results/change_map.tif",
    output_t1_semantic="changestar_results/t1_buildings.tif",
    output_t2_semantic="changestar_results/t2_buildings.tif",
    output_vector="changestar_results/changes.gpkg",
)
```

## Frameworks introduced

- **Registration before interpretation**: a one-pixel shift can look like a changed boundary.
- **Baseline ladder**: differencing → threshold analysis → deep model → vector analysis.
- **Temporal confounder audit**: check clouds, shadows, season, illumination, sensor, resolution, and preprocessing before labeling change.

## Mental models

Use a difference histogram to understand the data distribution, not as a substitute for reference labels. Think of the change map as a hypothesis that must be explained by the two source images.

## Anti-patterns

- **Comparing unaligned rasters**.
- **Interpreting all large differences as real change**.
- **Changing threshold and model simultaneously**.

## Key takeaways

1. Co-register and normalize before any change claim.
2. Keep threshold sensitivity results and both source dates.
3. Deep models should beat a transparent baseline on held-out geography, not just training examples.

## Connects to

- **Ch04–Ch05**: selecting and comparing temporal imagery.
- **Ch09**: semantic maps at each date.
- **Ch16**: embedding similarity for temporal change.
