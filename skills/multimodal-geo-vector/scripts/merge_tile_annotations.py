"""Merge tile-local multimodal annotations into one global pixel JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon


def _as_polygon(obj: dict[str, Any]) -> Polygon | None:
    kind = obj.get("geometry_type", "polygon")
    v = obj.get("vertices", [])
    if kind == "bbox" and len(v) == 4:
        x0, y0, x1, y1 = v
        v = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        kind = "polygon"
    if kind != "polygon" or len(v) < 3:
        return None
    p = Polygon(v)
    return p if p.is_valid else p.buffer(0)


def _iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    pa, pb = _as_polygon(a), _as_polygon(b)
    if pa is None or pb is None or pa.is_empty or pb.is_empty:
        return 0.0
    inter = pa.intersection(pb).area
    union = pa.union(pb).area
    return float(inter / union) if union else 0.0


def merge(manifest_path: Path, annotation_dir: Path, output_json: Path, iou_threshold: float = 0.5) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    merged: list[dict[str, Any]] = []
    found = 0
    for tile in manifest["tiles"]:
        tile_id = tile["tile_id"]
        candidates = [annotation_dir / f"{tile_id}.json", annotation_dir / f"{tile_id}_annotations.json"]
        annotation_path = next((p for p in candidates if p.exists()), None)
        if annotation_path is None:
            continue
        found += 1
        payload = json.loads(annotation_path.read_text(encoding="utf-8"))
        image_w, image_h = payload.get("image_size", [tile["width"], tile["height"]])
        sx, sy = tile["width"] / float(image_w), tile["height"] / float(image_h)
        for obj in payload.get("objects", payload.get("polygons", [])):
            work = dict(obj)
            kind = work.get("geometry_type", "polygon")
            raw = work.get("vertices", work.get("coordinates", []))
            normalized = payload.get("coordinate_space") == "normalized"
            if normalized:
                if kind == "point":
                    raw = [float(raw[0]) * image_w, float(raw[1]) * image_h]
                elif kind == "bbox":
                    raw = [float(v) * (image_w if i % 2 == 0 else image_h) for i, v in enumerate(raw)]
                else:
                    raw = [[float(x) * image_w, float(y) * image_h] for x, y in raw]
            if kind == "point":
                work["vertices"] = [float(raw[0]) * sx + tile["x_offset"], float(raw[1]) * sy + tile["y_offset"]]
            elif kind == "bbox":
                work["vertices"] = [
                    float(raw[0]) * sx + tile["x_offset"],
                    float(raw[1]) * sy + tile["y_offset"],
                    float(raw[2]) * sx + tile["x_offset"],
                    float(raw[3]) * sy + tile["y_offset"],
                ]
            else:
                work["vertices"] = [[float(x) * sx + tile["x_offset"], float(y) * sy + tile["y_offset"]] for x, y in raw]
            work["source_tile"] = tile_id
            merged.append(work)

    # Non-maximum suppression for overlapping tiles: retain the higher
    # confidence polygon when the same label overlaps heavily.
    kept: list[dict[str, Any]] = []
    for obj in sorted(merged, key=lambda x: float(x.get("confidence", 0.0)), reverse=True):
        label = obj.get("label", "target")
        if any(label == old.get("label", "target") and _iou(obj, old) >= iou_threshold for old in kept):
            continue
        kept.append(obj)
    result = {
        "image_size": [manifest["global_width"], manifest["global_height"]],
        "coordinate_space": "pixel",
        "objects": kept,
        "tile_manifest": str(manifest_path),
        "tiles_with_annotations": found,
    }
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"tiles_with_annotations": found, "input_objects": len(merged), "output_objects": len(kept), "output": str(output_json)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--annotations-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iou-threshold", type=float, default=0.5)
    args = parser.parse_args()
    print(json.dumps(merge(args.manifest, args.annotations_dir, args.output, args.iou_threshold), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
