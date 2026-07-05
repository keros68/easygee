#!/usr/bin/env python
"""Suggest geemap functions for a requested notebook or workflow action."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ToolRoute:
    id: str
    functions: tuple[str, ...]
    keywords: tuple[str, ...]
    read: tuple[str, ...]
    caution: str


ROUTES = [
    ToolRoute(
        id="interactive-map",
        functions=("geemap.Map", "Map.addLayer", "Map.centerObject", "Map.add_basemap"),
        keywords=("map", "visualize", "layer", "basemap", "display", "interactive", "地图", "可视化", "图层", "底图", "显示", "交互"),
        read=("references/geemap-api-surface.md", "references/geemap-agent-recipes.md"),
        caution="A rendered layer is a visual probe, not proof of analysis correctness.",
    ),
    ToolRoute(
        id="draw-aoi",
        functions=("Map.draw_last_feature", "Map.user_roi", "Map._user_rois"),
        keywords=("draw", "aoi", "roi", "polygon", "select area", "clip", "画", "绘制", "研究区", "感兴趣区", "区域", "多边形", "裁剪"),
        read=("references/geemap-api-surface.md", "references/geemap-agent-recipes.md"),
        caution="Convert drawn/clicked state into explicit geometry before handoff.",
    ),
    ToolRoute(
        id="export-image",
        functions=("geemap.ee_export_image", "geemap.ee_export_image_to_drive", "ee.batch.Export.image.*"),
        keywords=("export image", "geotiff", "tif", "download raster", "drive", "asset", "导出影像", "下载栅格", "导出栅格", "云盘", "资产"),
        read=("references/geemap-api-surface.md", "references/gee-agent-playbook.md"),
        caution="Large rasters should use asynchronous EE exports with explicit scale, region, and maxPixels.",
    ),
    ToolRoute(
        id="export-vector",
        functions=("geemap.ee_export_vector", "geemap.ee_to_csv", "ee.batch.Export.table.*"),
        keywords=(
            "export table", "export vector", "export a table", "export the result", "csv", "shp", "geojson", "kml",
            "featurecollection", "table", "for plotting", "download table",
            "导出表", "导出矢量", "表格", "矢量", "导出结果",
        ),
        read=("references/geemap-api-surface.md", "references/gee-agent-playbook.md"),
        caution="Avoid pulling large FeatureCollections through getInfo(); export tables instead.",
    ),
    ToolRoute(
        id="zonal-stats",
        functions=("geemap.zonal_stats", "geemap.zonal_stats_by_group", "ee.Image.reduceRegions"),
        keywords=(
            "zonal", "statistics", "by polygon", "by polygons", "polygons", "multiple polygons",
            "by county", "by watershed", "area by class", "field boundaries", "boundaries", "mean ndvi",
            "分区统计", "按多边形", "按县", "按流域", "分类面积", "按区域", "地块边界",
        ),
        read=("references/geemap-api-surface.md", "references/task-patterns.md"),
        caution="Use grouped reducers/pixelArea for categorical class areas, not mean class labels.",
    ),
    ToolRoute(
        id="local-vector",
        functions=("geemap.shp_to_ee", "geemap.geojson_to_ee", "Map.addLayer"),
        keywords=("shapefile", "geojson", "local vector", "upload vector", "boundary file", "本地矢量", "边界文件", "上传矢量", "行政边界", "地块边界"),
        read=("references/geemap-api-surface.md", "references/setup-auth.md"),
        caution="Check CRS, geometry validity, size, and privacy before sending local data to EE.",
    ),
    ToolRoute(
        id="conversion",
        functions=("geemap.conversion.js_to_python_dir", "geemap.conversion.py_to_ipynb_dir"),
        keywords=("javascript", "js", "convert", "migration", "code editor", "ipynb", "转换", "迁移", "代码编辑器", "转python", "转notebook"),
        read=("references/geemap-api-surface.md", "references/geemap-agent-recipes.md"),
        caution="Review converted code for UI assumptions, initialization, exports, and getInfo behavior.",
    ),
    ToolRoute(
        id="timelapse",
        functions=("Map.add_landsat_ts_gif", "Map.add_gui('timelapse')", "geemap.download_ee_video"),
        keywords=("timelapse", "gif", "animation", "landsat animation", "frames", "延时", "动图", "动画", "逐帧"),
        read=("references/geemap-api-surface.md", "references/task-patterns.md"),
        caution="Export or document dates/parameters; a GIF alone is not a reproducible analysis result.",
    ),
    ToolRoute(
        id="catalog-search",
        functions=("geemap.ee_search", "geemap.ai.EarthEngineDatasetIndex.find_top_matches"),
        keywords=(
            "search dataset", "data catalog", "find dataset", "which dataset", "best gee dataset",
            "gee dataset", "dataset for", "dataset", "api docs",
            "查数据集", "找数据集", "数据目录", "哪个数据集", "数据集检索",
        ),
        read=("references/geemap-api-surface.md", "references/SOURCES.md"),
        caution="Use search for discovery; verify band names, QA, scale, and terms in official catalog pages.",
    ),
    ToolRoute(
        id="map-export",
        functions=("Map.to_html", "Map.to_image"),
        keywords=("html", "png", "jpg", "export map", "share map", "report map", "导出地图", "分享地图", "报告地图", "网页地图"),
        read=("references/geemap-api-surface.md", "references/opengeos-patterns.md"),
        caution="Map exports are communication artifacts and do not validate reducer/export correctness.",
    ),
]


def score(route: ToolRoute, text: str) -> int:
    return sum(1 for keyword in route.keywords if keyword in text)


def choose(text: str, limit: int) -> list[ToolRoute]:
    normalized = text.lower()
    ranked = sorted(((score(route, normalized), route) for route in ROUTES), key=lambda item: (-item[0], item[1].id))
    matches = [route for value, route in ranked if value > 0]
    return (matches or [route for _, route in ranked])[:limit]


def print_text(routes: list[ToolRoute]) -> None:
    for route in routes:
        print(route.id)
        print("  functions: " + ", ".join(route.functions))
        print("  read: " + ", ".join(route.read))
        print("  caution: " + route.caution)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="*", help="Requested geemap action")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    text = " ".join(args.request).strip()
    if not text:
        parser.error("provide requested action text")

    routes = choose(text, max(1, args.limit))
    if args.json:
        print(json.dumps([asdict(route) for route in routes], ensure_ascii=False, indent=2))
    else:
        print_text(routes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
