#!/usr/bin/env python
"""Render CRS vectors over their reference raster for visual QA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image, ImageDraw
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon


def _rgb_preview(src, bands: list[int], max_size: int) -> tuple[Image.Image, float, float]:
    valid_bands = [band for band in bands if 1 <= band <= src.count]
    if not valid_bands:
        raise ValueError(f"bands={bands} 不在影像波段范围 1..{src.count} 内。")
    while len(valid_bands) < 3:
        valid_bands.append(valid_bands[-1])
    ratio = min(1.0, max_size / max(src.width, src.height))
    out_w = max(1, int(src.width * ratio))
    out_h = max(1, int(src.height * ratio))
    masked = src.read(
        valid_bands[:3],
        out_shape=(3, out_h, out_w),
        resampling=rasterio.enums.Resampling.bilinear,
        masked=True,
    )
    arr = masked.filled(np.nan).astype("float32")
    out = np.zeros_like(arr)
    for index in range(3):
        values = arr[index][np.isfinite(arr[index])]
        if not values.size:
            continue
        low, high = np.nanpercentile(values, (2, 98))
        out[index] = np.clip((arr[index] - low) / max(float(high - low), 1e-6), 0, 1)
    out[~np.isfinite(out)] = 0
    return Image.fromarray((out * 255).astype("uint8").transpose(1, 2, 0), mode="RGB"), out_w / src.width, out_h / src.height


def _draw_geometry(draw: ImageDraw.ImageDraw, geometry, to_pixel, color: tuple[int, int, int], width: int) -> None:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, Polygon):
        draw.line([to_pixel(x, y) for x, y in geometry.exterior.coords], fill=color, width=width, joint="curve")
        for ring in geometry.interiors:
            draw.line([to_pixel(x, y) for x, y in ring.coords], fill=color, width=width, joint="curve")
    elif isinstance(geometry, (LineString,)):
        draw.line([to_pixel(x, y) for x, y in geometry.coords], fill=color, width=width, joint="curve")
    elif isinstance(geometry, Point):
        x, y = to_pixel(geometry.x, geometry.y)
        radius = max(3, width * 2)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=width)
    elif isinstance(geometry, (MultiPolygon, MultiLineString, GeometryCollection)):
        for part in geometry.geoms:
            _draw_geometry(draw, part, to_pixel, color, width)


def render_qa(
    raster_path: Path,
    vector_path: Path,
    output_path: Path,
    *,
    layer: str | None = None,
    bands: list[int] | None = None,
    color: tuple[int, int, int] = (255, 40, 30),
    width: int = 3,
    max_size: int = 1800,
) -> dict[str, object]:
    gdf = gpd.read_file(vector_path, layer=layer)
    with rasterio.open(raster_path) as src:
        if not src.crs:
            raise ValueError("参考栅格没有 CRS。")
        if gdf.crs is None:
            raise ValueError("矢量没有 CRS。")
        gdf = gdf.to_crs(src.crs)
        raster_crs = src.crs.to_string()
        image, scale_x, scale_y = _rgb_preview(src, bands or [1, 2, 3], max_size)
        inverse = ~src.transform

        def to_pixel(x: float, y: float) -> tuple[float, float]:
            col, row = inverse * (x, y)
            return float(col * scale_x), float(row * scale_y)

        draw = ImageDraw.Draw(image)
        for geometry in gdf.geometry:
            _draw_geometry(draw, geometry, to_pixel, color, width)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, optimize=True)
    return {
        "output": str(output_path),
        "feature_count": int(len(gdf)),
        "raster_crs": raster_crs,
        "vector_crs": gdf.crs.to_string(),
        "preview_size": list(image.size),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raster", type=Path, required=True)
    parser.add_argument("--vector", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--layer")
    parser.add_argument("--bands", default="1,2,3")
    parser.add_argument("--color", default="255,40,30")
    parser.add_argument("--width", type=int, default=3)
    parser.add_argument("--max-size", type=int, default=1800)
    args = parser.parse_args()
    color = tuple(int(value.strip()) for value in args.color.split(","))
    if len(color) != 3 or any(value < 0 or value > 255 for value in color):
        parser.error("--color 必须为 R,G,B，且每项在 0..255。")
    result = render_qa(
        args.raster,
        args.vector,
        args.output,
        layer=args.layer,
        bands=[int(value) for value in args.bands.split(",")],
        color=color,
        width=args.width,
        max_size=args.max_size,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
