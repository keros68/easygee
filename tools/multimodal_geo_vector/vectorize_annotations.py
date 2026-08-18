"""Convert multimodal pixel annotations or painted overlays to CRS vectors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import xy
from shapely.geometry import LineString, Point, Polygon
from skimage.measure import find_contours


def _map_point(transform, x: float, y: float) -> tuple[float, float]:
    return tuple(xy(transform, float(y), float(x), offset="ul"))


def _geometry_from_object(obj: dict[str, Any], transform, sx: float, sy: float):
    kind = obj.get("geometry_type", "polygon").lower()
    raw = obj.get("vertices", obj.get("coordinates"))
    if kind == "bbox":
        if not raw or len(raw) != 4:
            return None
        x0, y0, x1, y1 = raw
        raw = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        kind = "polygon"
    if kind == "point":
        if not raw or len(raw) != 2:
            return None
        return Point(_map_point(transform, float(raw[0]) * sx, float(raw[1]) * sy))
    if not raw or len(raw) < 2:
        return None
    coords = [_map_point(transform, float(x) * sx, float(y) * sy) for x, y in raw]
    if kind == "line":
        return LineString(coords)
    if len(coords) < 3:
        return None
    holes = []
    for ring in obj.get("holes", []):
        if len(ring) < 3:
            continue
        holes.append([_map_point(transform, float(x) * sx, float(y) * sy) for x, y in ring])
    polygon = Polygon(coords, holes=holes)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return polygon if not polygon.is_empty else None


def _write_groups(groups: dict[str, list[dict[str, Any]]], output_stem: Path) -> dict[str, Any]:
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"layers": {}, "total": 0}
    for kind, records in groups.items():
        if not records:
            continue
        gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=records[0]["_crs"])
        gdf = gdf.drop(columns=["_crs"])
        native_path = output_stem.parent / f"{output_stem.name}_{kind}.gpkg"
        wgs84_path = output_stem.parent / f"{output_stem.name}_{kind}.geojson"
        gdf.to_file(native_path, layer=kind, driver="GPKG")
        gdf.to_crs("EPSG:4326").to_file(wgs84_path, driver="GeoJSON")
        manifest["layers"][kind] = {
            "count": len(gdf),
            "crs": gdf.crs.to_string(),
            "gpkg": str(native_path),
            "geojson": str(wgs84_path),
        }
        manifest["total"] += len(gdf)
        if kind == "polygons":
            boundary = gdf.copy()
            boundary["geometry"] = boundary.geometry.boundary
            boundary_path = output_stem.parent / f"{output_stem.name}_boundaries.gpkg"
            boundary.to_file(boundary_path, layer="boundaries", driver="GPKG")
            manifest["boundary_gpkg"] = str(boundary_path)
    manifest_path = output_stem.parent / f"{output_stem.name}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest


def vectorize_json(annotation_json: Path, raster_path: Path, output_stem: Path, min_area: float = 0, max_area: float | None = None, min_circularity: float = 0, simplify: float = 0) -> dict[str, Any]:
    payload = json.loads(annotation_json.read_text(encoding="utf-8"))
    with rasterio.open(raster_path) as src:
        if not src.crs or src.transform.is_identity:
            raise ValueError("GeoTIFF 必须包含有效 CRS 和 affine transform。")
        image_size = payload.get("image_size", [src.width, src.height])
        image_w, image_h = float(image_size[0]), float(image_size[1])
        coordinate_space = payload.get("coordinate_space", "pixel")
        sx = src.width / image_w
        sy = src.height / image_h
        objects = payload.get("objects", payload.get("polygons", []))
        groups: dict[str, list[dict[str, Any]]] = {"polygons": [], "lines": [], "points": []}
        for idx, obj in enumerate(objects, start=1):
            work = dict(obj)
            if coordinate_space == "normalized":
                raw = work.get("vertices", work.get("coordinates"))
                if work.get("geometry_type", "polygon") == "bbox":
                    raw = work.get("vertices", work.get("coordinates"))
                if raw:
                    if work.get("geometry_type", "polygon") == "point":
                        work["vertices"] = [float(raw[0]) * image_w, float(raw[1]) * image_h]
                    elif work.get("geometry_type", "polygon") == "bbox":
                        work["vertices"] = [float(v) * (image_w if i % 2 == 0 else image_h) for i, v in enumerate(raw)]
                    else:
                        work["vertices"] = [[float(x) * image_w, float(y) * image_h] for x, y in raw]
                if work.get("holes"):
                    work["holes"] = [
                        [[float(x) * image_w, float(y) * image_h] for x, y in ring]
                        for ring in work["holes"]
                    ]
            geometry = _geometry_from_object(work, src.transform, sx, sy)
            if geometry is None:
                continue
            kind = "points" if geometry.geom_type == "Point" else "lines" if geometry.geom_type in {"LineString", "MultiLineString"} else "polygons"
            if kind == "polygons":
                area = float(geometry.area)
                circularity = float(4 * np.pi * area / max(geometry.length ** 2, 1e-12))
                if area < min_area or (max_area is not None and area > max_area) or circularity < min_circularity:
                    continue
                if simplify > 0:
                    geometry = geometry.simplify(simplify, preserve_topology=True)
            groups[kind].append({
                "object_id": str(work.get("id", f"obj_{idx:03d}")),
                "label": str(work.get("label", "target")),
                "confidence": float(work.get("confidence", 0.0)),
                "geometry": geometry,
                "_crs": src.crs,
            })
    return _write_groups(groups, output_stem)


def _color_mask(image: np.ndarray, color: str) -> np.ndarray:
    presets = {
        "cyan": np.array([0, 210, 230]),
        "red": np.array([235, 30, 30]),
        "green": np.array([30, 220, 80]),
        "orange": np.array([245, 110, 20]),
        "magenta": np.array([230, 20, 210]),
    }
    if color.lower() in presets:
        target = presets[color.lower()]
    else:
        target = np.array([int(x) for x in color.split(",")])
    distance = np.linalg.norm(image.astype("float32") - target.reshape(1, 1, 3), axis=2)
    return distance < 110


def overlay_to_json(overlay: Path, raster_path: Path, output_json: Path, color: str = "cyan", min_area_px: float = 20, max_area_px: float | None = None, dedupe_px: float = 10) -> dict[str, Any]:
    image = np.asarray(Image.open(overlay).convert("RGB"))
    mask = _color_mask(image, color)
    contours = find_contours(mask.astype("float32"), 0.5)
    with rasterio.open(raster_path) as src:
        sx, sy = src.width / image.shape[1], src.height / image.shape[0]
        raster_width, raster_height = src.width, src.height
    candidates: list[tuple[Polygon, float, float, float]] = []
    for contour in contours:
        if len(contour) < 20:
            continue
        coords = [(float(col) * sx, float(row) * sy) for row, col in contour]
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            continue
        area = float(poly.area)
        if area < min_area_px or (max_area_px is not None and area > max_area_px):
            continue
        candidates.append((poly, area, float(poly.centroid.x), float(poly.centroid.y)))
    selected: list[tuple[Polygon, float, float]] = []
    for poly, _, cx, cy in sorted(candidates, key=lambda x: x[1], reverse=True):
        if dedupe_px > 0 and any((cx - x) ** 2 + (cy - y) ** 2 < dedupe_px ** 2 for _, x, y in selected):
            continue
        selected.append((poly, cx, cy))
    payload = {
        # Vertices below have already been rescaled into the reference raster
        # pixel grid, so the JSON image_size must describe that grid rather
        # than the (possibly resized) overlay PNG.
        "image_size": [int(raster_width), int(raster_height)],
        "coordinate_space": "pixel",
        "objects": [
            {"id": f"overlay_{i:03d}", "label": "target", "geometry_type": "polygon", "confidence": 0.0, "vertices": [[float(x), float(y)] for x, y in poly.exterior.coords]}
            for i, (poly, _, _) in enumerate(selected, start=1)
        ],
    }
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"annotation_json": str(output_json), "candidate_count": len(selected)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    js = sub.add_parser("json")
    js.add_argument("--annotations", type=Path, required=True)
    js.add_argument("--raster", type=Path, required=True)
    js.add_argument("--output-stem", type=Path, required=True)
    js.add_argument("--min-area", type=float, default=0)
    js.add_argument("--max-area", type=float)
    js.add_argument("--min-circularity", type=float, default=0)
    js.add_argument("--simplify", type=float, default=0)
    ov = sub.add_parser("overlay")
    ov.add_argument("--overlay", type=Path, required=True)
    ov.add_argument("--raster", type=Path, required=True)
    ov.add_argument("--output-stem", type=Path, required=True)
    ov.add_argument("--color", default="cyan")
    ov.add_argument("--min-area-px", type=float, default=20)
    ov.add_argument("--max-area-px", type=float)
    ov.add_argument("--dedupe-px", type=float, default=10)
    args = parser.parse_args()
    if args.mode == "json":
        print(json.dumps(vectorize_json(args.annotations, args.raster, args.output_stem, args.min_area, args.max_area, args.min_circularity, args.simplify), ensure_ascii=False, indent=2))
    else:
        annotation_json = args.output_stem.parent / f"{args.output_stem.name}_overlay_annotations.json"
        print(json.dumps(overlay_to_json(args.overlay, args.raster, annotation_json, args.color, args.min_area_px, args.max_area_px, args.dedupe_px), ensure_ascii=False, indent=2))
        print(json.dumps(vectorize_json(annotation_json, args.raster, args.output_stem), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
