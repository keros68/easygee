# Chapter 11: Image Translation

## Core idea

Image translation transforms imagery between domains or resolutions. The book demonstrates latent-diffusion super-resolution for remote sensing and emphasizes uncertainty, tiling, and validation against real high-resolution evidence.

## Method

Inspect input band count, size, CRS, resolution, and dtype before inference. A small patch smoke test can use:

```python
sr_image, uncertainty = geoai.super_resolution(
    input_lr_path=s2_path,
    output_sr_path="sr_output.tif",
    output_uncertainty_path="uncertainty.tif",
    rgb_nir_bands=[1, 2, 3, 4],
    window=(700, 1300, 128, 128),
    sampling_steps=100,
)
```

Use `geoai.plot_sr_comparison` and `geoai.plot_sr_uncertainty`. For a larger region, run tiled inference with overlap and inspect seams. Keep the original CRS and output resolution metadata; verify that the output is georeferenced and that downstream users understand it is generated imagery.

## Frameworks introduced

- **Patch-first translation**: validate one small window → compare input/output → estimate uncertainty → scale to tiles → validate across land-cover types.
- **Uncertainty-aware output**: generated detail and confidence are separate products; retain the uncertainty map.
- **Hallucination boundary**: super-resolution can create plausible texture that is not supported by the low-resolution observation.

## Key concepts

- **Sampling steps**: more steps may change quality/runtime; compare systematically.
- **Overlap/stitching**: reduces seams but costs compute.
- **Validation target**: compare against suitable high-resolution imagery, not only visual sharpness.

## Anti-patterns

- **Treating sharpened pixels as new measurement evidence** for quantitative analysis without validation.
- **Scaling to a full scene before checking a patch**.
- **Ignoring uncertainty and edge artifacts**.

## Key takeaways

1. Verify input metadata and output georeferencing.
2. Retain uncertainty and inspect tile boundaries.
3. Validate against appropriate higher-resolution references before scientific or operational use.

## Connects to

- **Ch03**: sensor metadata and resolution.
- **Ch05**: split-map comparisons.
- **Ch06**: tiled processing.
