#!/usr/bin/env python
"""Suggest EasyGEE references and workflow patterns for a task prompt."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Pattern:
    id: str
    title: str
    keywords: tuple[str, ...]
    datasets: tuple[str, ...]
    references: tuple[str, ...]
    first_steps: tuple[str, ...]
    risks: tuple[str, ...]


PATTERNS = [
    Pattern(
        id="vegetation-index",
        title="Vegetation index / phenology",
        keywords=(
            "ndvi", "evi", "vegetation", "crop", "greenness", "phenology", "drought",
            "植被", "长势", "作物", "农田", "物候", "干旱", "植被指数", "绿度",
        ),
        datasets=("COPERNICUS/S2_SR_HARMONIZED", "LANDSAT/*/C02/T1_L2", "MODIS/061/MOD13Q1"),
        references=("references/task-patterns.md", "references/dataset-qa-patterns.md", "references/temporal-compositing.md"),
        first_steps=("Choose sensor/resolution", "Apply QA/cloud mask", "Add RGB and index layers", "Probe small AOI"),
        risks=("Cloud/haze contamination", "Cross-sensor scale mismatch", "Large getInfo time series"),
    ),
    Pattern(
        id="cross-sensor-harmonization",
        title="Landsat and Sentinel-2 harmonization / HLS",
        keywords=(
            "hls", "harmonized landsat sentinel", "harmonization", "cross sensor", "cross-sensor",
            "landsat sentinel", "landsat and sentinel", "landsat 8 and sentinel-2", "landsat 9 and sentinel-2",
            "sensor fusion", "nbar", "bandpass", "跨传感器", "传感器一致化", "传感器融合",
            "landsat与sentinel", "landsat和sentinel", "陆地卫星和哨兵", "光谱响应",
        ),
        datasets=("NASA/HLS/HLSL30/v002", "NASA/HLS/HLSS30/v002"),
        references=("references/cross-sensor-harmonization.md", "references/dataset-qa-patterns.md", "references/temporal-compositing.md"),
        first_steps=("Decide HLS versus native resolution", "Map common bands and Fmask", "Retain sensor identity", "Check paired bias and valid counts"),
        risks=("Rename/resample mistaken for harmonization", "Residual sensor/date bias", "Sentinel-2 red-edge treated as a common band"),
    ),
    Pattern(
        id="water-flood",
        title="Surface water / flood / inundation",
        keywords=(
            "water", "flood", "inundation", "lake", "river", "wetland", "mndwi", "ndwi",
            "水体", "洪水", "淹没", "积水", "湖泊", "河流", "湿地", "水灾", "内涝",
        ),
        datasets=("JRC Global Surface Water", "COPERNICUS/S2_SR_HARMONIZED", "LANDSAT/*/C02/T1_L2", "COPERNICUS/S1_GRD"),
        references=("references/task-patterns.md", "references/dataset-qa-patterns.md", "references/sentinel1-sar-methods.md", "references/geemap-agent-recipes.md"),
        first_steps=("Decide historical vs event mapping", "Add background and water candidate layer", "Threshold and inspect edges", "Summarize area with pixelArea"),
        risks=("Universal threshold assumption", "Optical cloud/shadow false water", "SAR speckle and terrain effects"),
    ),
    Pattern(
        id="sar-analysis",
        title="Sentinel-1 SAR geometry / backscatter analysis",
        keywords=(
            "sentinel-1", "sentinel 1", "s1 grd", "sar", "radar", "backscatter", "speckle",
            "incidence angle", "relative orbit", "ascending", "descending", "db", "linear power",
            "哨兵1", "哨兵-1", "雷达", "后向散射", "斑点噪声", "入射角", "相对轨道", "升轨", "降轨",
        ),
        datasets=("COPERNICUS/S1_GRD", "COPERNICUS/S1_GRD_FLOAT when linear power is required"),
        references=("references/sentinel1-sar-methods.md", "references/dataset-qa-patterns.md"),
        first_steps=("Filter homogeneous mode/polarization/pass/orbit", "Choose dB or linear arithmetic", "Build matched temporal composites", "Inspect angle and terrain"),
        risks=("Mixed viewing geometry", "Ratio of dB values", "Layover/shadow mistaken for change"),
    ),
    Pattern(
        id="classification",
        title="Land cover or supervised classification",
        keywords=(
            "classification", "classifier", "land cover", "crop type", "urban", "worldcover", "dynamic world",
            "分类", "土地覆盖", "地物", "地类", "作物类型", "城市", "建成区", "动态世界",
        ),
        datasets=("GOOGLE/DYNAMICWORLD/V1", "ESA/WorldCover/v200", "Landsat/Sentinel composites"),
        references=("references/task-patterns.md", "references/dataset-qa-patterns.md"),
        first_steps=("Prefer existing classes if suitable", "Document predictors and training labels", "Split train/validation", "Report confusion matrix"),
        risks=("Averaging class labels", "Band order mismatch", "No independent validation"),
    ),
    Pattern(
        id="change-detection",
        title="Change detection / before-after",
        keywords=(
            "change", "before", "after", "loss", "gain", "disturbance", "trend", "delta",
            "变化", "前后", "之前", "之后", "损失", "增加", "扰动", "趋势", "差异", "变化检测",
        ),
        datasets=("Sensor-matched S2/Landsat composites", "Hansen Global Forest Change", "JRC Global Surface Water"),
        references=("references/task-patterns.md", "references/gee-agent-playbook.md", "references/dataset-qa-patterns.md"),
        first_steps=("Match season/sensor/QA/scale", "Build identical pre/post composites", "Map delta or transition", "Summarize changed area"),
        risks=("Seasonality mistaken for change", "Sensor/resolution mismatch", "Threshold not validated"),
    ),
    Pattern(
        id="zonal-statistics",
        title="Zonal statistics / polygon summaries",
        keywords=(
            "zonal", "statistics", "summary", "county", "district", "watershed", "field", "polygon", "admin",
            "分区", "统计", "汇总", "县", "区县", "行政区", "流域", "地块", "多边形", "按区域",
        ),
        datasets=("Any continuous or categorical image with explicit scale",),
        references=("references/task-patterns.md", "references/geemap-agent-recipes.md", "references/gee-agent-playbook.md"),
        first_steps=("Validate zones", "Run one feature first", "Use reduceRegions or geemap.zonal_stats", "Export table"),
        risks=("Missing scale/CRS", "getInfo on large tables", "Mean of categorical labels"),
    ),
    Pattern(
        id="time-series",
        title="Time series / chart",
        keywords=(
            "time series", "timeseries", "chart", "monthly", "annual", "trend", "monitoring",
            "时间序列", "时序", "图表", "月度", "年度", "逐月", "逐年", "监测", "趋势",
        ),
        datasets=("ImageCollection matching metric and cadence",),
        references=("references/task-patterns.md", "references/temporal-compositing.md", "references/workflows.md", "references/geemap-agent-recipes.md"),
        first_steps=("Map image-to-feature function", "Probe a short date range", "Chart/export FeatureCollection", "Avoid large getInfo"),
        risks=("Large client download", "Irregular cadence ignored", "Cloud-masked nulls mishandled"),
    ),
    Pattern(
        id="temporal-composite",
        title="Temporal composite / mosaic semantics",
        keywords=(
            "temporal composite", "monthly composite", "seasonal composite", "median composite",
            "mean composite", "best pixel", "qualitymosaic", "quality mosaic", "mosaic",
            "valid observation", "observation count", "source date", "greenest pixel",
            "时间合成", "月合成", "季节合成", "中值合成", "最佳像元", "质量镶嵌", "有效观测", "来源日期",
        ),
        datasets=("Any QA-masked ImageCollection with explicit cadence",),
        references=("references/temporal-compositing.md", "references/workflows.md", "references/dataset-qa-patterns.md"),
        first_steps=("Choose reducer versus ordered/quality mosaic", "Apply QA before compositing", "Add valid observation count", "Preserve source date when selecting pixels"),
        risks=("Synthetic composite described as one acquisition", "Quality score bias", "Empty or irregular intervals hidden"),
    ),
    Pattern(
        id="terrain",
        title="Terrain / DEM derivatives",
        keywords=("dem", "terrain", "slope", "aspect", "hillshade", "elevation", "高程", "地形", "坡度", "坡向", "阴影", "山体阴影"),
        datasets=("COPERNICUS/DEM/GLO30", "USGS/SRTMGL1_003"),
        references=("references/task-patterns.md", "references/dataset-qa-patterns.md"),
        first_steps=("Inspect projection", "Use native or justified projection", "Compute terrain derivative", "Probe range"),
        risks=("Default projection artifacts", "Careless reproject over huge AOI", "Degrees used as meters"),
    ),
    Pattern(
        id="lst-urban-heat",
        title="Land surface temperature / urban heat",
        keywords=("lst", "land surface temperature", "surface temperature", "thermal", "urban heat", "heat island", "地表温度", "热岛", "城市热岛", "热红外", "热环境"),
        datasets=("LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2", "MODIS/061/MOD11A2"),
        references=("references/task-patterns.md", "references/dataset-qa-patterns.md"),
        first_steps=("Choose thermal resolution/cadence", "Apply QA and scale factors", "Convert units explicitly", "Summarize or export with explicit scale"),
        risks=("Raw thermal DN used as Celsius", "Cloud-contaminated LST", "Mixing 30 m and 1 km products without caveat"),
    ),
    Pattern(
        id="nighttime-lights",
        title="Nighttime lights / human activity proxy",
        keywords=("night lights", "nighttime lights", "viirs", "dnb", "urbanization", "economic", "夜间灯光", "夜光", "灯光", "人类活动", "城市扩张", "经济 proxy"),
        datasets=("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG",),
        references=("references/task-patterns.md", "references/geemap-agent-recipes.md"),
        first_steps=("Choose monthly/annual aggregation", "Mask low-quality/noisy pixels", "Summarize by zones", "State proxy limitations"),
        risks=("Gas flares/fires/noise mistaken for urban activity", "Proxy treated as direct GDP/population", "No coverage quality check"),
    ),
    Pattern(
        id="population-exposure",
        title="Population or building exposure",
        keywords=("population", "exposure", "risk", "people", "building", "buildings", "flood exposure", "人口", "暴露", "风险", "受灾人口", "建筑", "建筑物", "房屋"),
        datasets=("WorldPop/GP/100m/pop", "JRC/GHSL/P2023A/GHS_POP", "GOOGLE/Research/open-buildings/v3/polygons"),
        references=("references/task-patterns.md", "references/dataset-qa-patterns.md", "references/gee-agent-playbook.md"),
        first_steps=("Separate hazard layer from exposure layer", "Choose population/building year", "Mask exposure by hazard", "Sum by zones and export table"),
        risks=("Mismatched hazard and population dates", "Population uncertainty ignored", "Huge building collections not spatially filtered"),
    ),
]


def score(pattern: Pattern, text: str) -> int:
    return sum(1 for keyword in pattern.keywords if keyword in text)


def suggest(text: str, limit: int) -> list[Pattern]:
    normalized = text.lower()
    ranked = sorted(((score(pattern, normalized), pattern) for pattern in PATTERNS), key=lambda item: (-item[0], item[1].id))
    matches = [pattern for value, pattern in ranked if value > 0]
    return (matches or [pattern for _, pattern in ranked])[:limit]


def print_text(patterns: list[Pattern]) -> None:
    for pattern in patterns:
        print(f"{pattern.id}: {pattern.title}")
        print("  datasets: " + ", ".join(pattern.datasets))
        print("  read: " + ", ".join(pattern.references))
        print("  first steps: " + "; ".join(pattern.first_steps))
        print("  risks: " + "; ".join(pattern.risks))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", nargs="*", help="Task prompt text")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    text = " ".join(args.task).strip()
    if not text:
        parser.error("provide task text")
    patterns = suggest(text, max(1, args.limit))
    if args.json:
        print(json.dumps([asdict(pattern) for pattern in patterns], indent=2, ensure_ascii=False))
    else:
        print_text(patterns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
