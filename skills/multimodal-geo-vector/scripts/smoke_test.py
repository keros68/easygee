"""Run a no-download synthetic smoke test for pixel-to-CRS vectorization."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image, ImageDraw
from rasterio.transform import from_origin

from merge_tile_annotations import merge
from prepare_imagery import prepare_local
from render_vector_qa import render_qa
from select_recent_gee_scene import choose_candidate
from tile_imagery import tile_raster
from vectorize_annotations import overlay_to_json, vectorize_json


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="easygee-mm-vector-") as tmp:
        root = Path(tmp)
        raster = root / "synthetic.tif"
        with rasterio.open(
            raster,
            "w",
            driver="GTiff",
            width=100,
            height=80,
            count=3,
            dtype="uint8",
            crs="EPSG:32637",
            transform=from_origin(400000, 3300000, 10, 10),
        ) as dst:
            dst.write(np.zeros((3, 80, 100), dtype="uint8"))
        prepared = prepare_local(raster, root / "prepared", [1, 2, 3], "synthetic")
        annotations = root / "annotations.json"
        annotations.write_text(json.dumps({
            "image_size": [100, 80],
            "coordinate_space": "pixel",
            "objects": [{
                "id": "obj_001",
                "label": "target",
                "geometry_type": "polygon",
                "confidence": 0.9,
                "vertices": [[10, 10], [30, 10], [30, 30], [10, 30]],
                "holes": [[[15, 15], [20, 15], [20, 20], [15, 20]]],
            }],
        }), encoding="utf-8")
        result = vectorize_json(annotations, raster, root / "result")
        gdf = gpd.read_file(result["layers"]["polygons"]["gpkg"])
        assert Path(prepared["preview"]).exists()
        assert len(gdf) == 1
        assert gdf.crs.to_epsg() == 32637
        assert round(gdf.geometry.iloc[0].area) == 37500
        metadata = json.loads(Path(prepared["metadata"]).read_text(encoding="utf-8"))
        assert metadata["valid_pixel_fraction"] == 1.0
        qa_path = root / "qa.png"
        qa = render_qa(raster, Path(result["layers"]["polygons"]["gpkg"]), qa_path, layer="polygons")
        assert qa_path.exists() and qa["feature_count"] == 1

        selected, rule = choose_candidate(
            [
                {"image_id": "old_best", "time_start": 1000, "valid_fraction": 1, "quality_mean": 0.95, "clear_fraction": 0.95},
                {"image_id": "new_comparable", "time_start": 2000, "valid_fraction": 1, "quality_mean": 0.93, "clear_fraction": 0.94},
                {"image_id": "new_cloudy", "time_start": 3000, "valid_fraction": 1, "quality_mean": 0.70, "clear_fraction": 0.20},
            ],
            quality_tolerance=0.03,
        )
        assert selected["image_id"] == "new_comparable"
        assert "newest" in rule

        plain_png = root / "plain.png"
        Image.fromarray(np.zeros((20, 30, 3), dtype="uint8"), mode="RGB").save(plain_png)
        attached = prepare_local(plain_png, root / "attached", [1, 2, 3], "plain", "EPSG:4326", "100,20,101,21")
        with rasterio.open(attached["raster"]) as src:
            assert src.crs.to_epsg() == 4326
            assert src.bounds.left == 100
            assert src.bounds.top == 21

        overlay = Image.new("RGB", (200, 160), "black")
        ImageDraw.Draw(overlay).rectangle((20, 20, 60, 60), outline=(0, 230, 240), width=4)
        overlay_path = root / "overlay.png"
        overlay.save(overlay_path)
        overlay_json = root / "overlay.json"
        overlay_result = overlay_to_json(overlay_path, raster, overlay_json, "cyan", 20, None, 8)
        assert overlay_result["candidate_count"] >= 1
        assert json.loads(overlay_json.read_text(encoding="utf-8"))["image_size"] == [100, 80]

        tiled = tile_raster(raster, root / "tiles", tile_size=64, overlap=24)
        assert len(tiled["tiles"]) > 1
        ann_dir = root / "tile_annotations"
        ann_dir.mkdir()
        for tile in tiled["tiles"][:2]:
            payload = {
                "image_size": [tile["width"], tile["height"]],
                "coordinate_space": "pixel",
                "objects": [{"id": tile["tile_id"], "label": "target", "geometry_type": "point", "confidence": 0.8, "vertices": [5, 5]}],
            }
            (ann_dir / f"{tile['tile_id']}.json").write_text(json.dumps(payload), encoding="utf-8")
        merged_json = root / "merged.json"
        merged = merge(Path(tiled["manifest"]), ann_dir, merged_json)
        assert merged["tiles_with_annotations"] == 2
    print(json.dumps({"ok": True, "checks": ["preview", "valid_fraction", "pixel_to_crs", "polygon_hole", "gpkg", "qa_overlay", "scene_selection", "plain_image_georeference", "overlay_resize", "tiling", "tile_merge"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
