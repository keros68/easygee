"""Prepare local or Earth Engine imagery for multimodal annotation.

Both paths produce the same handoff contract:

* a CRS-preserving GeoTIFF;
* a model-friendly PNG preview;
* JSON metadata describing CRS, transform, dimensions, bands and provenance.

The PNG is never used to infer geographic coordinates by itself. Vector
coordinates are restored from the GeoTIFF's affine transform.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import warnings
from pathlib import Path
from typing import Sequence

import numpy as np
import rasterio
from PIL import Image
from rasterio.errors import NotGeoreferencedWarning


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "imagery"


def _preview_from_raster(raster_path: Path, preview_path: Path, bands: Sequence[int], max_size: int = 1600) -> dict:
    with rasterio.open(raster_path) as src:
        if not src.crs:
            raise ValueError("输入影像没有 CRS；请提供带地理参考的 GeoTIFF/COG 或先完成配准。")
        if src.transform.is_identity:
            raise ValueError("输入影像的仿射变换是 identity；无法把像素标注恢复到地图坐标。")
        valid_bands = [b for b in bands if 1 <= b <= src.count]
        if not valid_bands:
            raise ValueError(f"bands={bands} 不在影像波段范围 1..{src.count} 内。")
        while len(valid_bands) < 3:
            valid_bands.append(valid_bands[-1])
        scale = min(1.0, max_size / max(src.width, src.height))
        out_h, out_w = max(1, int(src.height * scale)), max(1, int(src.width * scale))
        masked = src.read(
            valid_bands[:3],
            out_shape=(3, out_h, out_w),
            resampling=rasterio.enums.Resampling.bilinear,
            masked=True,
        )
        arr = masked.filled(np.nan).astype("float32")
        valid = np.isfinite(arr) & ~np.ma.getmaskarray(masked)
        valid_pixels = np.all(valid, axis=0)
        valid_fraction = float(valid_pixels.mean())
        if not valid_pixels.any():
            raise ValueError("影像没有可显示的有限像元。")
        stretched = np.zeros_like(arr, dtype="float32")
        percentiles: list[list[float]] = []
        for band_index in range(3):
            band_values = arr[band_index][valid[band_index]]
            lo, hi = np.nanpercentile(band_values, (2, 98))
            percentiles.append([float(lo), float(hi)])
            stretched[band_index] = np.clip((arr[band_index] - lo) / max(float(hi - lo), 1e-6), 0, 1)
        stretched[~np.isfinite(stretched)] = 0
        stretched[:, ~valid_pixels] = 0
        Image.fromarray((stretched * 255).astype("uint8").transpose(1, 2, 0), mode="RGB").save(preview_path, optimize=True)
        return {
            "crs": src.crs.to_string(),
            "width": src.width,
            "height": src.height,
            "count": src.count,
            "transform": list(src.transform)[:6],
            "bounds": list(src.bounds),
            "resolution": list(src.res),
            "preview_width": out_w,
            "preview_height": out_h,
            "preview_bands": list(valid_bands[:3]),
            "stretch_percentiles": [2, 98],
            "stretch_values_by_band": percentiles,
            "valid_pixel_fraction": valid_fraction,
        }


def _attach_georeference(input_path: Path, output_path: Path, crs: str, bounds: str) -> Path:
    bbox = _parse_bbox(bounds)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with rasterio.open(input_path) as src:
                data = src.read()
                profile = src.profile.copy()
                width, height = src.width, src.height
    except rasterio.errors.RasterioIOError:
        arr = np.asarray(Image.open(input_path))
        if arr.ndim == 2:
            arr = arr[:, :, None]
        arr = arr[:, :, :3]
        data = arr.transpose(2, 0, 1)
        height, width = arr.shape[:2]
        profile = {"driver": "GTiff", "dtype": str(data.dtype), "count": data.shape[0]}
    profile.update(
        driver="GTiff",
        width=width,
        height=height,
        count=data.shape[0],
        crs=crs,
        transform=rasterio.transform.from_bounds(*bbox, width=width, height=height),
    )
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(data)
    return output_path


def prepare_local(input_path: Path, output_dir: Path, bands: Sequence[int], name: str | None, crs: str | None = None, bounds: str | None = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(name or input_path.stem)
    raster_path = input_path
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with rasterio.open(input_path) as src:
                needs_georef = not src.crs or src.transform.is_identity
    except rasterio.errors.RasterioIOError:
        needs_georef = True
    if needs_georef:
        if not crs or not bounds:
            raise ValueError("本地影像没有地理参考；必须同时提供 --crs 和 --bounds，或先在 GIS 中完成配准。")
        raster_path = _attach_georeference(input_path, output_dir / f"{stem}.tif", crs, bounds)
    preview_path = output_dir / f"{stem}_preview.png"
    metadata = _preview_from_raster(raster_path, preview_path, bands)
    metadata.update({"source_type": "local", "source": str(input_path), "prepared_raster": str(raster_path), "source_bands": list(bands)})
    metadata_path = output_dir / f"{stem}.metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"raster": str(raster_path), "preview": str(preview_path), "metadata": str(metadata_path)}


def _parse_bbox(text: str) -> list[float]:
    values = [float(x.strip()) for x in text.split(",")]
    if len(values) != 4 or values[0] >= values[2] or values[1] >= values[3]:
        raise ValueError("region 必须为 xmin,ymin,xmax,ymax，且范围有效。")
    return values


def _mask_s2_scl(image):
    scl = image.select("SCL")
    mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
    return image.updateMask(mask)


def prepare_gee(
    project: str,
    output_dir: Path,
    region: str,
    bands: Sequence[str],
    scale: float,
    crs: str,
    collection: str | None,
    image_id: str | None,
    start: str | None,
    end: str | None,
    cloud_field: str | None,
    cloud_max: float | None,
    reducer: str,
    scale_factor: float,
    name: str | None,
) -> dict:
    import ee
    import geemap

    ee.Initialize(project=project)
    bbox = _parse_bbox(region)
    aoi = ee.Geometry.Rectangle(bbox, geodesic=False)
    source_properties: dict[str, object] = {}
    if image_id:
        source_image = ee.Image(image_id)
        source_properties = source_image.toDictionary(
            ["system:index", "system:time_start", "CLOUDY_PIXEL_PERCENTAGE", "CLOUD_COVER"]
        ).getInfo()
        image = source_image.select(list(bands))
        scene_count = 1
        source_name = image_id
    else:
        if not collection:
            raise ValueError("GEE 输入必须提供 --collection 或 --image-id。")
        images = ee.ImageCollection(collection).filterBounds(aoi)
        if start:
            images = images.filterDate(start, end or "2100-01-01")
        if cloud_field and cloud_max is not None:
            images = images.filter(ee.Filter.lt(cloud_field, cloud_max))
        if collection.startswith("COPERNICUS/S2_SR"):
            images = images.map(_mask_s2_scl)
        scene_count = int(images.size().getInfo())
        if scene_count == 0:
            raise RuntimeError("GEE 集合在指定 AOI/时间/质量条件下没有影像。")
        if reducer == "mosaic":
            image = images.mosaic()
        elif reducer == "first":
            image = ee.Image(images.sort("system:time_start").first())
        else:
            image = images.median()
        image = image.select(list(bands))
        source_name = collection
    if scale_factor != 1:
        image = image.multiply(scale_factor)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(name or (image_id or collection or "gee_image"))
    raster_path = output_dir / f"{stem}.tif"
    preview_path = output_dir / f"{stem}_preview.png"
    metadata_path = output_dir / f"{stem}.metadata.json"
    geemap.ee_export_image(
        image,
        filename=str(raster_path),
        scale=scale,
        region=aoi,
        crs=crs,
        file_per_band=False,
        timeout=300,
    )
    local_meta = _preview_from_raster(raster_path, preview_path, [1, 2, 3])
    local_meta.update({
        "source_type": "gee",
        "source": source_name,
        "project": project,
        "region_wgs84": bbox,
        "source_bands": list(bands),
        "scale_m": scale,
        "scale_factor": scale_factor,
        "date_range": [start, end],
        "matched_scene_count": scene_count,
        "reducer": reducer,
        "selected_image_id": image_id,
        "selected_image_properties": source_properties,
    })
    metadata_path.write_text(json.dumps(local_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"raster": str(raster_path), "preview": str(preview_path), "metadata": str(metadata_path), "matched_scene_count": scene_count}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    local = sub.add_parser("local", help="prepare a georeferenced local raster")
    local.add_argument("--input", type=Path, required=True)
    local.add_argument("--output-dir", type=Path, required=True)
    local.add_argument("--bands", default="1,2,3")
    local.add_argument("--name")
    local.add_argument("--crs", help="CRS for an unreferenced JPG/PNG, e.g. EPSG:4326")
    local.add_argument("--bounds", help="xmin,ymin,xmax,ymax expressed in --crs")

    gee = sub.add_parser("gee", help="filter/export a GEE image or collection")
    gee.add_argument("--project", default=os.environ.get("EE_PROJECT", ""))
    gee.add_argument("--output-dir", type=Path, required=True)
    gee.add_argument("--region", required=True, help="xmin,ymin,xmax,ymax in WGS84")
    gee.add_argument("--bands", required=True, help="dataset band names, e.g. B4,B3,B2")
    gee.add_argument("--scale", type=float, required=True)
    gee.add_argument("--crs", required=True)
    gee.add_argument("--collection")
    gee.add_argument("--image-id")
    gee.add_argument("--start")
    gee.add_argument("--end")
    gee.add_argument("--cloud-field")
    gee.add_argument("--cloud-max", type=float)
    gee.add_argument("--reducer", choices=["median", "mosaic", "first"], default="median")
    gee.add_argument("--scale-factor", type=float, default=1.0)
    gee.add_argument("--name")
    args = parser.parse_args()

    if args.mode == "local":
        print(json.dumps(prepare_local(args.input, args.output_dir, [int(x) for x in args.bands.split(",")], args.name, args.crs, args.bounds), ensure_ascii=False, indent=2))
    else:
        if not args.project:
            parser.error("GEE 模式需要 --project 或 EE_PROJECT。")
        print(json.dumps(prepare_gee(args.project, args.output_dir, args.region, args.bands.split(","), args.scale, args.crs, args.collection, args.image_id, args.start, args.end, args.cloud_field, args.cloud_max, args.reducer, args.scale_factor, args.name), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
