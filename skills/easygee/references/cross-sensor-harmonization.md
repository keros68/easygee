# Cross-Sensor Harmonization: Landsat And Sentinel-2

Use this compact reference when a workflow combines Landsat 8/9 and
Sentinel-2 observations. Harmonization is more than renaming bands or
resampling pixels: atmospheric correction, spectral response, grid alignment,
view/illumination geometry, QA, and temporal sampling can all create apparent
change.

## Default decision

- Prefer NASA HLS when the objective is one dense, analysis-ready Landsat plus
  Sentinel-2 surface-reflectance series at a common 30 m grid.
- Keep native Sentinel-2 when 10 m detail or MSI red-edge bands are essential.
- Keep native Landsat when thermal information or the longest Landsat archive
  is essential.
- If native products are mixed, explicitly harmonize band definitions,
  reflectance scaling, projection/scale, QA, and observation geometry. A band
  rename plus `merge()` is not sufficient evidence of comparability.

## HLS route

Earth Engine collections:

- `NASA/HLS/HLSL30/v002`: Landsat 8/9 OLI, 30 m NBAR.
- `NASA/HLS/HLSS30/v002`: Sentinel-2 A/B MSI, 30 m NBAR.

HLS applies atmospheric correction, cloud/cloud-shadow masking support,
co-registration and common gridding, illumination/view-angle normalization,
and spectral bandpass adjustment. The two products remain separate
collections and must be merged deliberately. The advertised combined revisit
does not guarantee a valid observation at every pixel after QA.

Common comparison bands:

| Common name | HLSL30 | HLSS30 |
|---|---|---|
| blue | `B2` | `B2` |
| green | `B3` | `B3` |
| red | `B4` | `B4` |
| narrow NIR | `B5` | `B8A` |
| SWIR1 | `B6` | `B11` |
| SWIR2 | `B7` | `B12` |

Do not silently substitute Sentinel-2 broad NIR `B8` for the harmonized
narrow-NIR comparison. Red-edge bands are Sentinel-2-specific predictors, not
common HLS bands.

## QA and minimal merge pattern

HLS `Fmask` uses bit 1 for cloud, bit 2 for cloud/shadow adjacency, bit 3 for
cloud shadow, bit 4 for snow/ice, bit 5 for water, and bits 6-7 for aerosol
level. Keep water when water is the target; treat aerosol thresholds as a
documented analysis choice.

```python
def mask_hls(image):
    invalid = (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)
    clear = image.select("Fmask").bitwiseAnd(invalid).eq(0)
    return image.updateMask(clear)

def prep_l30(image):
    return (
        mask_hls(image)
        .select(["B2", "B3", "B4", "B5", "B6", "B7"],
                ["blue", "green", "red", "nir", "swir1", "swir2"])
        .set("hls_sensor", "L30")
    )

def prep_s30(image):
    return (
        mask_hls(image)
        .select(["B2", "B3", "B4", "B8A", "B11", "B12"],
                ["blue", "green", "red", "nir", "swir1", "swir2"])
        .set("hls_sensor", "S30")
    )

l30 = ee.ImageCollection("NASA/HLS/HLSL30/v002").map(prep_l30)
s30 = ee.ImageCollection("NASA/HLS/HLSS30/v002").map(prep_s30)
hls = l30.merge(s30).sort("system:time_start")
```

Use HLS reflectance semantics as documented by the HLS catalog. Do not apply
the Landsat Collection 2 `0.0000275/-0.2` coefficients to HLS assets.

## Validation and reporting

1. Report both source collection ids, common band mapping, QA bits, output
   scale/grid, and retained sensor label.
2. Plot valid-observation count by sensor as well as the merged count.
3. Use near-coincident L30/S30 observations over stable targets to inspect
   residual bias; report distributions or paired differences, not only maps.
4. Use the same temporal windows and reducer for both sensors. Different dates
   or seasons can dominate a nominal sensor comparison.
5. Do not claim that HLS makes the sensors identical. It reduces known
   systematic differences while residual QA, geometry, and sampling effects
   remain.

Official sources are listed in `SOURCES.md` under the HLS catalog entries.
