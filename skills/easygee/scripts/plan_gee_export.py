#!/usr/bin/env python
"""Plan Earth Engine/geemap exports from natural-language requests."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DESTINATION_KEYWORDS = {
    "drive": (
        "drive",
        "google drive",
        "my drive",
        "云盘",
        "云端硬盘",
        "google云盘",
        "google 云盘",
        "谷歌云盘",
    ),
    "cloud_storage": ("cloud storage", "gcs", "bucket", "storage bucket", "存储桶", "云存储", "对象存储"),
    "asset": ("asset", "earth engine asset", "ee asset", "资产", "gee资产", "earth engine 资产"),
    "bigquery": ("bigquery", "bq", "big query"),
    "local": (
        "local",
        "download",
        "save locally",
        "geopackage",
        "geo package",
        ".gpkg",
        "gpkg",
        "本地",
        "下载",
        "保存到本地",
        "落盘",
    ),
}

DATA_KIND_KEYWORDS = {
    "map": (
        "map html",
        "map png",
        "screenshot",
        "screen shot",
        "share map",
        "export map",
        "html",
        "png",
        "jpg",
        "地图网页",
        "地图截图",
        "分享地图",
        "导出地图",
        "截图",
    ),
    "video": ("video", "mp4", "gif", "timelapse", "animation", "视频", "动图", "动画", "延时"),
    "table": (
        "csv",
        "table",
        "statistics",
        "stats",
        "zonal",
        "time series",
        "timeseries",
        "chart",
        "plotting",
        "mean",
        "area",
        "summary",
        "表",
        "表格",
        "统计",
        "分区",
        "时序",
        "时间序列",
        "均值",
        "面积",
        "汇总",
        "画图",
    ),
    "vector": (
        "geopackage",
        "geo package",
        ".gpkg",
        "gpkg",
        "shp",
        "shapefile",
        "geojson",
        "kml",
        "kmz",
        "featurecollection",
        "feature collection",
        "polygon",
        "points",
        "footprints",
        "vector",
        "矢量",
        "边界",
        "多边形",
        "点",
        "轮廓",
        "建筑轮廓",
    ),
    "image": (
        "image",
        "raster",
        "geotiff",
        "tiff",
        "tif",
        "cog",
        "ndvi",
        "evi",
        "mndwi",
        "lst",
        "dem",
        "classification",
        "mask",
        "layer",
        "影像",
        "栅格",
        "图像",
        "图层",
        "分类图",
        "掩膜",
        "植被指数",
        "地表温度",
    ),
}

FORMAT_KEYWORDS = {
    "GeoPackage": ("geopackage", "geo package", ".gpkg", "gpkg"),
    "GeoTIFF": ("geotiff", "geo tiff", "tiff", "tif", "栅格"),
    "COG": ("cog", "cloud optimized geotiff", "cloud-optimized geotiff", "云优化"),
    "CSV": ("csv",),
    "SHP": ("shp", "shapefile"),
    "GeoJSON": ("geojson", "geo json"),
    "KML": ("kml",),
    "KMZ": ("kmz",),
    "TFRecord": ("tfrecord", "tf record"),
    "HTML": ("html", "网页"),
    "PNG": ("png", "截图"),
    "MP4": ("mp4",),
    "GIF": ("gif", "动图"),
}

AOI_KEYWORDS = (
    "aoi",
    "roi",
    "region",
    "current area",
    "current view",
    "map viewport",
    "drawn",
    "selected area",
    "这个区域",
    "当前区域",
    "当前aoi",
    "当前 aoi",
    "这个aoi",
    "这个 aoi",
    "画的",
    "绘制",
    "视野",
    "当前地图",
)

IMAGE_COLLECTION_HINTS = (
    "imagecollection",
    "image collection",
    "collection",
    "影像集",
    "集合",
    "monthly",
    "annual",
    "seasonal",
    "summer",
    "winter",
    "spring",
    "autumn",
    "5-9",
    "may-sep",
    "may to september",
    "max",
    "maximum",
    "median",
    "mean",
    "mosaic",
    "qualitymosaic",
    "月度",
    "年度",
    "夏季",
    "冬季",
    "春季",
    "秋季",
    "最大值",
    "中位数",
    "平均",
    "合成",
)

START_KEYWORDS = (
    "start",
    "run",
    "submit",
    "export to",
    "export now",
    "to drive",
    "to google drive",
    "to cloud storage",
    "to asset",
    "直接",
    "开始",
    "启动",
    "提交",
    "现在导出",
    "马上",
    "导出到",
    "导出至",
    "到 drive",
    "到 google drive",
    "到云盘",
)
PREPARE_ONLY_KEYWORDS = ("prepare", "not start", "do not start", "dry run", "只准备", "不要启动", "先别导出", "草稿")


@dataclass(frozen=True)
class ExportPlan:
    data_kind: str
    destination: str
    route: str
    recommended_backend: str
    functions: tuple[str, ...]
    format: str
    scale_m: int | None
    region_source: str
    start_policy: str
    image_collection_materialization: str | None
    defaults: dict[str, object]
    missing_parameters: tuple[str, ...]
    clarifying_questions: tuple[dict[str, object], ...]
    agent_steps: tuple[str, ...]
    review_checklist: tuple[str, ...]
    cautions: tuple[str, ...]


def hits(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def detect_destination(text: str) -> str:
    if contains_any(text, ("geopackage", "geo package", ".gpkg", "gpkg")):
        return "local"
    scores = {name: hits(text, keywords) for name, keywords in DESTINATION_KEYWORDS.items()}
    if scores["local"] and re.search(r"\b(download|local)\b|下载|本地", text):
        return "local"
    best = max(scores.items(), key=lambda item: (item[1], item[0]))
    return best[0] if best[1] > 0 else "unspecified"


def detect_data_kind(text: str) -> str:
    scores = {name: hits(text, keywords) for name, keywords in DATA_KIND_KEYWORDS.items()}
    if scores["map"] > 0:
        return "map"
    if scores["video"] > 0:
        return "video"
    if scores["table"] > 0 and scores["table"] >= scores["image"]:
        return "table"
    if scores["vector"] > 0 and scores["vector"] > scores["table"]:
        return "vector"
    if scores["image"] > 0:
        return "image"
    return "unspecified"


def detect_format(text: str, data_kind: str) -> str:
    for name, keywords in FORMAT_KEYWORDS.items():
        if contains_any(text, keywords):
            return "GeoTIFF" if name == "COG" else name
    if data_kind == "image":
        return "GeoTIFF"
    if data_kind == "table":
        return "CSV"
    if data_kind == "vector":
        return "GeoJSON"
    if data_kind == "map":
        return "HTML"
    if data_kind == "video":
        return "MP4"
    return "unspecified"


def detect_scale(text: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{1,4})\s*(?:m|meter|meters|米|metre|metres)\b", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(?<!\d)(\d{1,4})\s*米", text)
    if match:
        return int(match.group(1))
    return None


def detect_region(text: str) -> str:
    if contains_any(text, AOI_KEYWORDS):
        if "view" in text or "viewport" in text or "视野" in text or "当前地图" in text:
            return "map_viewport"
        return "current_aoi"
    if "global" in text or "worldwide" in text or "全球" in text:
        return "global"
    return "unspecified"


def detect_start_policy(text: str) -> str:
    if contains_any(text, PREPARE_ONLY_KEYWORDS):
        return "prepare_only"
    if contains_any(text, START_KEYWORDS):
        return "start_task"
    return "review_then_start"


def materialization_hint(text: str, data_kind: str) -> str | None:
    if data_kind != "image":
        return None
    if not contains_any(text, IMAGE_COLLECTION_HINTS):
        return None
    if "max" in text or "maximum" in text or "最大值" in text:
        return "Reduce ImageCollection to a single image with max()/qualityMosaic() before export."
    if "median" in text or "中位数" in text:
        return "Reduce ImageCollection to a single median composite before export."
    if "mean" in text or "平均" in text:
        return "Reduce ImageCollection to a single mean composite before export."
    return "Filter and composite the ImageCollection into a single ee.Image before export."


def choose_route(data_kind: str, destination: str, fmt: str) -> tuple[str, str, tuple[str, ...]]:
    effective_destination = "drive" if destination == "unspecified" and data_kind in {"image", "table"} else destination
    if data_kind == "map":
        return "geemap_map_communication_export", "geemap_map_export", ("Map.to_html", "Map.to_image")
    if data_kind == "video":
        if effective_destination == "cloud_storage":
            return "ee_batch_video_to_cloud_storage", "ee_batch", ("ee.batch.Export.video.toCloudStorage",)
        return "ee_batch_video_to_drive", "ee_batch", ("ee.batch.Export.video.toDrive", "geemap.download_ee_video")
    if data_kind == "table":
        if effective_destination == "local":
            return "geemap_table_local_download", "geemap_local", ("geemap.ee_to_csv", "geemap.ee_to_gdf")
        if effective_destination == "cloud_storage":
            return "ee_batch_table_to_cloud_storage", "ee_batch", ("ee.batch.Export.table.toCloudStorage",)
        if effective_destination == "asset":
            return "ee_batch_table_to_asset", "ee_batch", ("ee.batch.Export.table.toAsset",)
        if effective_destination == "bigquery":
            return "ee_batch_table_to_bigquery", "ee_batch", ("ee.batch.Export.table.toBigQuery",)
        return "ee_batch_table_to_drive", "ee_batch", ("ee.batch.Export.table.toDrive", "geemap.ee_export_vector_to_drive")
    if data_kind == "vector":
        if effective_destination == "local":
            if fmt == "GeoPackage":
                return (
                    "local_geopackage_vector_export",
                    "local_gis",
                    ("geemap.ee_to_gdf", "GeoDataFrame.to_file(driver='GPKG')"),
                )
            return "geemap_vector_local_download", "geemap_local", ("geemap.ee_export_vector", "geemap.ee_to_gdf")
        if effective_destination == "cloud_storage":
            return "ee_batch_table_to_cloud_storage", "ee_batch", ("ee.batch.Export.table.toCloudStorage",)
        if effective_destination == "asset":
            return "ee_batch_table_to_asset", "ee_batch", ("ee.batch.Export.table.toAsset",)
        return "ee_batch_table_to_drive", "ee_batch", ("ee.batch.Export.table.toDrive", "geemap.ee_export_vector_to_drive")
    if data_kind == "image":
        if effective_destination == "local":
            return "geemap_image_local_download", "geemap_local", ("geemap.ee_export_image", "geemap.download_ee_image")
        if effective_destination == "cloud_storage":
            return "ee_batch_image_to_cloud_storage", "ee_batch", ("ee.batch.Export.image.toCloudStorage",)
        if effective_destination == "asset":
            return "ee_batch_image_to_asset", "ee_batch", ("ee.batch.Export.image.toAsset",)
        return "ee_batch_image_to_drive", "ee_batch", ("ee.batch.Export.image.toDrive", "geemap.ee_export_image_to_drive")
    return "needs_export_clarification", "ask_user", ()


def missing_parameters(data_kind: str, destination: str, scale_m: int | None, region_source: str) -> tuple[str, ...]:
    missing: list[str] = []
    if data_kind == "unspecified":
        missing.append("output data type: image/raster, table/CSV, vector, map, or video")
    if destination == "unspecified" and data_kind not in {"map", "video"}:
        missing.append("destination: Drive, Cloud Storage, Earth Engine Asset, BigQuery, or local download")
    if data_kind in {"image", "table"} and region_source == "unspecified":
        missing.append("region/AOI or confirmation to use the current Map Console viewport")
    if data_kind == "image" and scale_m is None:
        missing.append("scale/resolution or permission to infer it from the selected dataset")
    if data_kind == "table":
        missing.append("reducer/statistic and output columns, unless already implied by the active analysis recipe")
    if destination == "cloud_storage":
        missing.append("Cloud Storage bucket and object prefix")
    if destination == "asset":
        missing.append("Earth Engine asset id")
    if destination == "bigquery":
        missing.append("BigQuery project.dataset.table")
    return tuple(dict.fromkeys(missing))


def clarifying_questions(data_kind: str, destination: str, materialization: str | None, missing: tuple[str, ...]) -> tuple[dict[str, object], ...]:
    questions: list[dict[str, object]] = []
    if data_kind == "unspecified":
        questions.append(
            {
                "id": "export_product_type",
                "question": "用户没有明确要导出影像、表格、矢量还是地图成品。",
                "options": ["image/raster", "table/csv", "vector", "map/html/png"],
            }
        )
    if destination == "unspecified" and data_kind not in {"map", "video", "unspecified"}:
        questions.append(
            {
                "id": "export_destination",
                "question": "导出目的地未说明；默认大结果走 Google Drive batch task，本地下载只适合小结果。",
                "options": ["Google Drive", "local download", "Cloud Storage", "Earth Engine Asset"],
            }
        )
    if materialization and materialization.startswith("Filter and composite"):
        questions.append(
            {
                "id": "image_collection_recipe",
                "question": "影像集需要先变成单张影像；如果自然语言未指定 reducer，应确认 max/median/mean/mosaic/qualityMosaic。",
                "options": ["max", "median", "mean", "qualityMosaic", "mosaic"],
            }
        )
    if any("scale" in item for item in missing):
        questions.append(
            {
                "id": "export_scale",
                "question": "影像导出缺少 scale；可以按数据集原生分辨率推断，但要在任务摘要中明说。",
                "options": ["infer from dataset", "10 m", "30 m", "250 m", "custom"],
            }
        )
    return tuple(questions)


def build_plan(text: str) -> ExportPlan:
    normalized = text.lower()
    data_kind = detect_data_kind(normalized)
    destination = detect_destination(normalized)
    fmt = detect_format(normalized, data_kind)
    scale_m = detect_scale(normalized)
    region_source = detect_region(normalized)
    start_policy = detect_start_policy(normalized)
    materialization = materialization_hint(normalized, data_kind)
    route, backend, functions = choose_route(data_kind, destination, fmt)
    missing = missing_parameters(data_kind, destination, scale_m, region_source)
    questions = clarifying_questions(data_kind, destination, materialization, missing)

    defaults: dict[str, object] = {"fileFormat": fmt}
    if data_kind in {"image", "table", "vector", "video"}:
        defaults["file_name_prefix"] = "derive from metric_dataset_aoi_date"
    if fmt == "GeoPackage":
        defaults["layer_name"] = "detected_targets"
        defaults["crs"] = "source/native projected CRS or a suitable local UTM CRS"
    if data_kind in {"image", "table", "vector"} and destination in {"drive", "unspecified"}:
        defaults["drive_folder"] = "earthengine_exports"
    if data_kind == "image":
        defaults["maxPixels"] = 1e13
    if fmt == "GeoTIFF" and contains_any(normalized, FORMAT_KEYWORDS["COG"]):
        defaults["formatOptions"] = {"cloudOptimized": True}
    if destination == "unspecified" and data_kind in {"image", "table"}:
        defaults["destination"] = "Google Drive for durable batch exports"
    if region_source == "unspecified" and data_kind in {"image", "table"}:
        defaults["region"] = "current Map Console viewport only after telling the user"
    if scale_m is None and data_kind == "image":
        defaults["scale"] = "infer from selected dataset only when unambiguous"

    steps = [
        "Parse the requested product, destination, format, AOI, scale, and start policy.",
        "Materialize any ImageCollection into an Image or FeatureCollection before exporting.",
        "Run a small visual or numeric probe before starting a long batch task.",
        "Create or start the export through the chosen backend and persist task metadata.",
    ]
    if backend == "geemap_local":
        steps.append("Use local geemap download only for modest AOIs; switch to EE batch export for large rasters/tables.")
    if backend == "local_gis":
        steps.append("Spatialize visual annotations against the source raster transform, write GeoPackage with an explicit CRS, and render a QA overlay.")
    if backend == "ee_batch":
        steps.append("Expose task id, destination, file prefix, region, scale/CRS, maxPixels, and status in the workbench.")

    checklist = [
        "Destination and naming are explicit.",
        "Region/AOI is explicit and not only hidden browser state.",
        "Scale/projection/CRS assumptions are recorded.",
        "Masked/nodata behavior is intentional for raster outputs.",
        "The user can see whether the task is prepared, started, completed, failed, or cancelled.",
    ]

    cautions = [
        "A rendered map layer does not prove the export parameters are correct.",
        "Avoid getInfo() for large images, collections, tables, or time series; export instead.",
    ]
    if backend == "geemap_local":
        cautions.append("Local downloads can timeout or tile heavily; prefer asynchronous EE exports for large work.")
    if backend == "local_gis":
        cautions.append("GeoPackage is a local GIS artifact; visual pixel/normalized coordinates must be tied to the exact source raster before writing it.")
    if destination == "unspecified" and data_kind in {"image", "table", "vector"}:
        cautions.append("Destination is inferred only as a default; ask if the default affects cost, privacy, or workflow.")

    return ExportPlan(
        data_kind=data_kind,
        destination=destination,
        route=route,
        recommended_backend=backend,
        functions=functions,
        format=fmt,
        scale_m=scale_m,
        region_source=region_source,
        start_policy=start_policy,
        image_collection_materialization=materialization,
        defaults=defaults,
        missing_parameters=missing,
        clarifying_questions=questions,
        agent_steps=tuple(steps),
        review_checklist=tuple(checklist),
        cautions=tuple(cautions),
    )


def print_text(plan: ExportPlan) -> None:
    print(f"route: {plan.route}")
    print(f"data kind: {plan.data_kind}")
    print(f"destination: {plan.destination}")
    print(f"backend: {plan.recommended_backend}")
    print(f"format: {plan.format}")
    if plan.scale_m is not None:
        print(f"scale: {plan.scale_m} m")
    print("functions: " + (", ".join(plan.functions) if plan.functions else "clarify first"))
    if plan.image_collection_materialization:
        print("materialization: " + plan.image_collection_materialization)
    if plan.missing_parameters:
        print("missing: " + "; ".join(plan.missing_parameters))
    if plan.clarifying_questions:
        print("questions:")
        for question in plan.clarifying_questions:
            print(f"  - {question['id']}: {question['question']}")
    print("steps:")
    for step in plan.agent_steps:
        print(f"  - {step}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="*", help="Natural-language export request")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    text = " ".join(args.request).strip()
    if not text:
        parser.error("provide export request text")
    plan = build_plan(text)
    if args.json:
        print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
    else:
        print_text(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
