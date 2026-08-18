import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.multimodal_geo_vector.vectorize_annotations import vectorize_json
from tools.multimodal_geo_vector.merge_tile_annotations import merge
from tools.multimodal_geo_vector.select_recent_gee_scene import choose_candidate


def _make_raster(path: Path) -> None:
    with rasterio.open(
        path,
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


def test_pixel_json_to_crs_vector(tmp_path: Path) -> None:
    raster = tmp_path / "image.tif"
    _make_raster(raster)
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({
        "image_size": [100, 80],
        "coordinate_space": "pixel",
        "objects": [{"id": "a", "label": "tree", "geometry_type": "polygon", "confidence": 0.9, "vertices": [[10, 10], [30, 10], [30, 30], [10, 30]]}],
    }))
    result = vectorize_json(labels, raster, tmp_path / "out")
    gdf = gpd.read_file(result["layers"]["polygons"]["gpkg"])
    assert len(gdf) == 1
    assert gdf.crs.to_epsg() == 32637
    assert gdf.geometry.iloc[0].area == 40000


def test_tile_merge_offsets_and_deduplicates(tmp_path: Path) -> None:
    manifest = tmp_path / "tiles_manifest.json"
    annotations = tmp_path / "annotations"
    annotations.mkdir()
    manifest.write_text(json.dumps({
        "global_width": 100,
        "global_height": 80,
        "tiles": [{"tile_id": "tile_0001", "x_offset": 0, "y_offset": 0, "width": 60, "height": 80}, {"tile_id": "tile_0002", "x_offset": 20, "y_offset": 0, "width": 60, "height": 80}],
    }))
    obj = {"image_size": [60, 80], "coordinate_space": "pixel", "objects": [{"id": "a", "label": "car", "geometry_type": "bbox", "confidence": 0.8, "vertices": [20, 20, 40, 40]}]}
    (annotations / "tile_0001.json").write_text(json.dumps(obj))
    obj["objects"][0]["vertices"] = [0, 20, 20, 40]
    obj["objects"][0]["confidence"] = 0.7
    (annotations / "tile_0002.json").write_text(json.dumps(obj))
    out = tmp_path / "merged.json"
    result = merge(manifest, annotations, out)
    assert result["input_objects"] == 2
    assert result["output_objects"] == 1
    assert json.loads(out.read_text())["image_size"] == [100, 80]


def test_polygon_holes_are_preserved(tmp_path: Path) -> None:
    raster = tmp_path / "image.tif"
    _make_raster(raster)
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({
        "image_size": [100, 80],
        "coordinate_space": "pixel",
        "objects": [{
            "id": "field_with_exclusion",
            "label": "target",
            "geometry_type": "polygon",
            "confidence": 0.8,
            "vertices": [[10, 10], [30, 10], [30, 30], [10, 30]],
            "holes": [[[15, 15], [20, 15], [20, 20], [15, 20]]],
        }],
    }))
    result = vectorize_json(labels, raster, tmp_path / "out")
    gdf = gpd.read_file(result["layers"]["polygons"]["gpkg"])
    assert len(gdf.geometry.iloc[0].interiors) == 1
    assert gdf.geometry.iloc[0].area == 37500


def test_recent_scene_prefers_newest_comparable_clear_candidate() -> None:
    selected, rule = choose_candidate([
        {"image_id": "best_old", "time_start": 1000, "valid_fraction": 1, "quality_mean": 0.96, "clear_fraction": 0.95},
        {"image_id": "good_new", "time_start": 2000, "valid_fraction": 1, "quality_mean": 0.94, "clear_fraction": 0.92},
        {"image_id": "cloudy_newest", "time_start": 3000, "valid_fraction": 1, "quality_mean": 0.70, "clear_fraction": 0.30},
    ], quality_tolerance=0.03)
    assert selected["image_id"] == "good_new"
    assert "newest" in rule


def test_recent_scene_does_not_silently_accept_bad_coverage() -> None:
    with pytest.raises(ValueError, match="有效像元阈值"):
        choose_candidate([
            {"image_id": "partial", "time_start": 1000, "valid_fraction": 0.60, "quality_mean": 0.99, "clear_fraction": 0.99},
        ])
