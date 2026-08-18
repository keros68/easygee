"""Tile a georeferenced raster for windowed multimodal annotation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import rasterio
from rasterio.windows import Window, transform as window_transform

from prepare_imagery import _preview_from_raster


def tile_raster(input_path: Path, output_dir: Path, tile_size: int = 512, overlap: int = 64) -> dict:
    if overlap >= tile_size:
        raise ValueError("overlap 必须小于 tile_size。")
    output_dir.mkdir(parents=True, exist_ok=True)
    stride = tile_size - overlap
    tiles = []
    with rasterio.open(input_path) as src:
        if not src.crs or src.transform.is_identity:
            raise ValueError("输入影像必须包含 CRS 和 affine transform。")
        tile_index = 0
        for top in range(0, src.height, stride):
            for left in range(0, src.width, stride):
                width = min(tile_size, src.width - left)
                height = min(tile_size, src.height - top)
                window = Window(left, top, width, height)
                tile_index += 1
                tile_path = output_dir / f"tile_{tile_index:04d}.tif"
                profile = src.profile.copy()
                profile.update(width=width, height=height, transform=window_transform(window, src.transform))
                with rasterio.open(tile_path, "w", **profile) as dst:
                    dst.write(src.read(window=window))
                preview_path = output_dir / f"tile_{tile_index:04d}_preview.png"
                _preview_from_raster(tile_path, preview_path, [1, 2, 3])
                tiles.append({
                    "tile_id": tile_path.stem,
                    "raster": str(tile_path),
                    "preview": str(preview_path),
                    "x_offset": int(left),
                    "y_offset": int(top),
                    "width": int(width),
                    "height": int(height),
                })
    manifest = {
        "source_raster": str(input_path),
        "global_width": int(src.width),
        "global_height": int(src.height),
        "tile_size": tile_size,
        "overlap": overlap,
        "stride": stride,
        "tiles": tiles,
    }
    manifest_path = output_dir / "tiles_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tile-size", type=int, default=512)
    parser.add_argument("--overlap", type=int, default=64)
    args = parser.parse_args()
    print(json.dumps(tile_raster(args.input, args.output_dir, args.tile_size, args.overlap), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
