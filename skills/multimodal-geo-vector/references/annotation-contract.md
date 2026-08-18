# Annotation and Spatialization Contract

## Contents

1. Input imagery contract
2. Model annotation JSON
3. Pixel-to-map conversion
4. Vector output contract
5. Validation rules

## 1. Input imagery contract

Use a GeoTIFF/COG with:

- a declared CRS;
- a non-identity affine transform;
- explicit width, height, band order, nodata and resolution;
- provenance for local files or GEE asset/collection, AOI, time, reducer and scale.

For an unreferenced JPG/PNG, require both `crs` and `bounds`. Treat bounds as
`xmin,ymin,xmax,ymax` in that CRS. Never infer geographic coordinates from
visual appearance, filenames or web-map screenshots.

The preview PNG may be resized. Keep its width and height in the annotation
JSON; spatialization rescales preview pixels to the reference GeoTIFF grid.

## 2. Model annotation JSON

Preferred schema:

```json
{
  "image_size": [1600, 1200],
  "coordinate_space": "pixel",
  "objects": [
    {
      "id": "obj_001",
      "label": "target",
      "geometry_type": "polygon",
      "confidence": 0.88,
      "vertices": [[10, 10], [30, 10], [30, 30], [10, 30]],
      "holes": [[[15, 15], [20, 15], [20, 20], [15, 20]]]
    }
  ]
}
```

Supported geometry types:

- `polygon`: at least three `[x,y]` exterior vertices; the first vertex need not repeat; optional `holes` contains zero or more interior rings using the same coordinate space;
- `bbox`: `[xmin,ymin,xmax,ymax]`;
- `point`: one `[x,y]` pair;
- `line`: at least two `[x,y]` vertices.

`coordinate_space` may be `pixel` or `normalized`. Normalized coordinates must
be in `[0,1]`. Keep `confidence` in `[0,1]`; use `0` when the model does not
provide calibrated confidence.

## 3. Pixel-to-map conversion

Let the annotation image size be `(Wa,Ha)` and the reference raster size be
`(Wr,Hr)`. Convert annotation pixels to reference pixels:

```text
xr = xa * Wr / Wa
yr = ya * Hr / Ha
```

Then apply the raster affine transform to `(xr,yr)`. Use the upper-left pixel
corner convention for polygon vertices. Preserve the source raster CRS in the
native GeoPackage; reproject exchange GeoJSON to EPSG:4326.

For tiled inference, add each tile's `x_offset` and `y_offset` before applying
the global raster transform. Deduplicate same-label detections in overlap
areas by IoU or an application-specific rule.

## 4. Vector output contract

Write separate layers/files for polygons, lines and points. Keep these fields:

- `object_id`;
- `label`;
- `confidence`;
- geometry;
- optional source tile/model/prompt identifiers.

Also write a polygon boundary line layer for QGIS visual QA. Do not fill
polygons by default in presentation screenshots when adjacent objects touch.
Use polygon holes for roads, substations, reservoirs, bare gaps, or other
explicit exclusions inside a continuous candidate region; do not erase them
by replacing the result with a convex hull.

## 5. Validation rules

- Reject vertices outside the declared annotation image unless clipping was
  explicitly requested.
- Repair invalid polygons, but retain the raw annotation JSON.
- Report object count before and after filtering/deduplication.
- Use projected metres for area, distance, simplification and buffering.
- Do not claim detection accuracy without independent reference labels.
- Preserve prompt, model/version, source image metadata and thresholds beside
  outputs when results support quantitative reporting.
