#!/usr/bin/env python
"""Route EasyGEE requests to compute, map, or mixed interaction modes."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass


COMPUTE_KEYWORDS = (
    "calculate",
    "compute",
    "stat",
    "statistics",
    "mean",
    "median",
    "sum",
    "area",
    "trend",
    "compare",
    "difference",
    "batch",
    "zonal",
    "reduce",
    "time series",
    "timeseries",
    "extract",
    "detect",
    "identify",
    "recognize",
    "segment",
    "outline",
    "trace",
    "计算",
    "算",
    "统计",
    "均值",
    "中位数",
    "求和",
    "面积",
    "趋势",
    "对比",
    "比较",
    "差异",
    "批量",
    "分区",
    "时间序列",
    "时序",
    "提取",
    "识别",
    "检测",
    "分割",
    "勾画",
    "勾勒",
    "圈出",
)

MAP_KEYWORDS = (
    "show",
    "display",
    "map",
    "visualize",
    "preview",
    "overlay",
    "layer",
    "inspect",
    "see",
    "look",
    "browser",
    "interactive",
    "highlight",
    "看",
    "显示",
    "地图",
    "可视化",
    "预览",
    "叠加",
    "图层",
    "检查",
    "浏览器",
    "交互",
    "标出",
    "高亮",
    "这里",
    "批注",
)

MAP_CONSOLE_KEYWORDS = (
    "map console",
    "map workbench",
    "open map",
    "open the map",
    "打开地图",
    "打开 easygee 地图",
    "地图工作台",
    "地图控制台",
)

AOI_KEYWORDS = (
    "draw",
    "aoi",
    "roi",
    "extent",
    "画",
    "绘制",
    "研究区",
    "范围",
)

MULTIMODAL_VECTOR_KEYWORDS = (
    "multimodal",
    "vision-language",
    "visual recognition",
    "visual ability",
    "多模态",
    "视觉能力",
    "视觉识别",
)

VECTOR_FILE_KEYWORDS = (
    "geopackage",
    ".gpkg",
    "gpkg",
    "geojson",
    "shapefile",
    "vector file",
    "crs",
    "矢量文件",
    "矢量",
    "带 crs",
)

TABLE_KEYWORDS = (
    "table",
    "csv",
    "spreadsheet",
    "chart",
    "plot",
    "series",
    "表",
    "表格",
    "图表",
    "曲线",
    "序列",
)

EXPORT_KEYWORDS = (
    "export",
    "download",
    "geotiff",
    "drive",
    "asset",
    "导出",
    "下载",
    "栅格",
    "资产",
)

NOTEBOOK_KEYWORDS = ("notebook", "ipynb", "jupyter", "colab", "笔记本")
SCRIPT_KEYWORDS = ("script", "python", ".py", "脚本")

MIXED_HINTS = (
    "then show",
    "then map",
    "if useful",
    "if abnormal",
    "if anomaly",
    "highlight",
    "flag",
    "先算",
    "再看",
    "如果异常",
    "异常",
    "标出来",
    "标出",
)


@dataclass(frozen=True)
class Route:
    mode: str
    browser_policy: str
    artifacts: list[str]
    triggers: list[str]
    next_actions: list[str]
    note: str


def hits(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if keyword in text]


def add_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def route(prompt: str) -> Route:
    text = prompt.strip().lower()
    compute_hits = hits(text, COMPUTE_KEYWORDS)
    map_hits = hits(text, MAP_KEYWORDS)
    map_console_hits = hits(text, MAP_CONSOLE_KEYWORDS)
    aoi_hits = hits(text, AOI_KEYWORDS)
    table_hits = hits(text, TABLE_KEYWORDS)
    export_hits = hits(text, EXPORT_KEYWORDS)
    notebook_hits = hits(text, NOTEBOOK_KEYWORDS)
    script_hits = hits(text, SCRIPT_KEYWORDS)
    mixed_hits = hits(text, MIXED_HINTS)
    multimodal_hits = hits(text, MULTIMODAL_VECTOR_KEYWORDS)
    vector_file_hits = hits(text, VECTOR_FILE_KEYWORDS)
    is_multimodal_vector = bool(multimodal_hits) and bool(vector_file_hits)

    artifacts: list[str] = []
    triggers: list[str] = []
    if compute_hits:
        add_unique(artifacts, "stat")
        triggers.append("compute")
    if table_hits or "time series" in compute_hits or "时间序列" in compute_hits or "时序" in compute_hits:
        add_unique(artifacts, "table")
        triggers.append("table")
    if export_hits:
        add_unique(artifacts, "export_task")
        triggers.append("export")
    if map_hits:
        add_unique(artifacts, "map_layer")
        triggers.append("map")
    if map_console_hits:
        add_unique(artifacts, "map_console")
        triggers.append("map_console")
    if aoi_hits:
        add_unique(artifacts, "aoi_needed")
        triggers.append("aoi")
    if notebook_hits:
        add_unique(artifacts, "notebook")
        triggers.append("notebook")
    if script_hits:
        add_unique(artifacts, "script")
        triggers.append("script")
    if is_multimodal_vector:
        for artifact in ("source_imagery", "visual_annotations", "vector_file", "qa_preview"):
            add_unique(artifacts, artifact)
        triggers.append("multimodal_vector")

    is_mixed = bool(mixed_hits) or (bool(compute_hits) and bool(map_hits)) or is_multimodal_vector
    if is_mixed:
        mode = "mixed"
        browser_policy = "compute_then_handoff_if_useful"
        add_unique(artifacts, "stat")
        if map_hits or mixed_hits or is_multimodal_vector:
            add_unique(artifacts, "map_layer")
        next_actions = [
            "Run the smallest reliable computation first.",
            "Prepare a map layer only for spatial QA, anomalies, thresholds, or user-facing inspection.",
            "Open or update the EasyGEE 地图工作台 (Map Console) after the computation produces something worth seeing.",
        ]
        note = "Compute first, then hand off to the EasyGEE 地图工作台 when visual inspection improves the answer."
    elif map_hits or aoi_hits:
        mode = "map_first"
        browser_policy = "open_for_aoi" if aoi_hits and not map_hits else "open_or_update"
        add_unique(artifacts, "map_layer")
        next_actions = [
            "Open or update the EasyGEE 地图工作台 (Map Console).",
            "Use the browser as the visible map state and interaction surface.",
            "Keep analytical claims separate from visual tile confirmation.",
        ]
        note = "Map requests, including 打开地图 and 地图工作台, use the EasyGEE 地图工作台."
    else:
        mode = "compute_first"
        browser_policy = "defer_and_offer"
        if not artifacts:
            add_unique(artifacts, "stat")
        next_actions = [
            "Run the GEE/API/local computation headlessly.",
            "Return numbers, tables, files, or export task status directly.",
            "Prepare a map layer only if the result needs visual QA or the user asks to see it.",
        ]
        note = "No explicit map/interaction trigger; avoid opening the browser by default."

    if not triggers:
        triggers.append("default")

    return Route(
        mode=mode,
        browser_policy=browser_policy,
        artifacts=artifacts,
        triggers=triggers,
        next_actions=next_actions,
        note=note,
    )


def print_text(result: Route) -> None:
    print(f"mode: {result.mode}")
    print(f"browser_policy: {result.browser_policy}")
    print("artifacts: " + ", ".join(result.artifacts))
    print("triggers: " + ", ".join(result.triggers))
    print("next actions:")
    for action in result.next_actions:
        print(f"  - {action}")
    print(f"note: {result.note}")


def smoke() -> None:
    cases = [
        ("统计北京朝阳公园 NDVI 均值并导出 CSV", "compute_first", "defer_and_offer", {"stat", "table"}),
        ("给我看北京朝阳公园 NDVI，打开地图叠加图层", "map_first", "open_or_update", {"map_layer"}),
        (
            "先算两个区域 NDVI 差异，如果异常就打开地图标出来",
            "mixed",
            "compute_then_handoff_if_useful",
            {"stat", "map_layer"},
        ),
        (
            "从 GEE 获取达拉特光伏基地近期清晰影像，用多模态视觉提取所有可见光伏场区边界，并导出带 CRS 的 GeoPackage。中心约为 109.671°E、40.295°N。",
            "mixed",
            "compute_then_handoff_if_useful",
            {"source_imagery", "visual_annotations", "vector_file", "qa_preview"},
        ),
        ("打开地图", "map_first", "open_or_update", {"map_layer", "map_console"}),
        ("打开地图工作台", "map_first", "open_or_update", {"map_layer", "map_console"}),
    ]
    for prompt, mode, policy, artifacts in cases:
        result = route(prompt)
        if result.mode != mode:
            raise AssertionError(f"{prompt!r}: expected mode {mode}, got {result.mode}")
        if result.browser_policy != policy:
            raise AssertionError(f"{prompt!r}: expected policy {policy}, got {result.browser_policy}")
        if not artifacts.issubset(set(result.artifacts)):
            raise AssertionError(f"{prompt!r}: expected artifacts {artifacts}, got {result.artifacts}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="*", help="EasyGEE user request text")
    parser.add_argument("--json", action="store_true", help="Print a JSON route payload")
    parser.add_argument("--smoke", action="store_true", help="Run built-in routing smoke checks")
    args = parser.parse_args()

    if args.smoke:
        smoke()
        print("route_easygee_interaction smoke passed")
        return 0

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        parser.error("provide prompt text")
    result = route(prompt)
    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
