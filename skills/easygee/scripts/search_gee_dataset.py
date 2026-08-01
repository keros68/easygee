#!/usr/bin/env python
"""Find likely Earth Engine datasets for a geospatial task.

This compatibility command combines a curated workflow layer with EasyGEE's
provenance-aware official/community catalog engine. It can optionally call
geemap's AI dataset index when that package is installed. Treat results as
candidates; verify the chosen dataset before final coding.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass


CATALOG_BASE = "https://developers.google.com/earth-engine/datasets/catalog/"


@dataclass(frozen=True)
class Dataset:
    id: str
    title: str
    kind: str
    official_url: str
    tasks: tuple[str, ...]
    keywords: tuple[str, ...]
    scale: str
    temporal: str
    bands: tuple[str, ...]
    qa: str
    best_for: str
    cautions: tuple[str, ...]
    workflow: tuple[str, ...]
    read: tuple[str, ...]


DATASETS = [
    Dataset(
        id="COPERNICUS/S2_SR_HARMONIZED",
        title="Sentinel-2 MSI Level-2A Surface Reflectance Harmonized",
        kind="ImageCollection",
        official_url=CATALOG_BASE + "COPERNICUS_S2_SR_HARMONIZED",
        tasks=("vegetation-index", "water-flood", "urban", "change-detection", "classification", "communication-map"),
        keywords=(
            "sentinel-2",
            "sentinel 2",
            "s2",
            "ndvi",
            "evi",
            "vegetation",
            "crop",
            "greenness",
            "mndwi",
            "ndwi",
            "water",
            "urban",
            "built",
            "10m",
            "光学",
            "哨兵2",
            "哨兵-2",
            "植被",
            "长势",
            "作物",
            "农田",
            "水体",
            "城市",
            "变化",
            "分类",
        ),
        scale="10 m / 20 m / 60 m bands; common RGB/NDVI work at 10 m",
        temporal="2017-present for global SR_HARMONIZED use; verify AOI/date coverage",
        bands=("B2", "B3", "B4", "B8", "B11", "B12", "SCL", "QA60"),
        qa="Filter scenes with CLOUDY_PIXEL_PERCENTAGE, then apply pixel mask with Cloud Score+ or SCL.",
        best_for="Recent high-resolution optical maps, vegetation indices, clear-sky water/urban/change workflows.",
        cautions=(
            "Scene cloud percentage is not a pixel cloud mask.",
            "QA60 has a 2022-2024 caveat; prefer Cloud Score+ for many agent workflows.",
            "Cloud/shadow/snow confusion can dominate flood and water maps.",
        ),
        workflow=(
            "Filter by AOI/date.",
            "Link Cloud Score+ and mask clear pixels.",
            "Add RGB plus target index/probability layer.",
            "Probe collection size and one reducer before export.",
        ),
        read=("references/dataset-qa-patterns.md", "references/geemap-agent-recipes.md"),
    ),
    Dataset(
        id="GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED",
        title="Cloud Score+ S2 Harmonized",
        kind="ImageCollection companion QA",
        official_url=CATALOG_BASE + "GOOGLE_CLOUD_SCORE_PLUS_V1_S2_HARMONIZED",
        tasks=("vegetation-index", "water-flood", "classification", "change-detection"),
        keywords=(
            "cloud score",
            "cloudscore",
            "cloud mask",
            "s2 cloud",
            "sentinel-2",
            "sentinel 2",
            "s2",
            "ndvi",
            "vegetation",
            "water",
            "classification",
            "clear pixel",
            "cs_cdf",
            "云",
            "云掩膜",
            "去云",
            "清晰像元",
            "哨兵2云",
        ),
        scale="Matches Sentinel-2 granules; use with S2 SR harmonized",
        temporal="Companion to Sentinel-2 harmonized collections",
        bands=("cs", "cs_cdf"),
        qa="Use as the pixel-level clear-score source for Sentinel-2 workflows.",
        best_for="Making S2 workflows safer than scene-level CLOUDY_PIXEL_PERCENTAGE alone.",
        cautions=("This is usually a companion QA dataset, not the primary analysis image.",),
        workflow=("Link to S2 with image.linkCollection(...).", "Threshold cs or cs_cdf and updateMask."),
        read=("references/dataset-qa-patterns.md",),
    ),
    Dataset(
        id="COPERNICUS/S2_CLOUD_PROBABILITY",
        title="Sentinel-2 Cloud Probability",
        kind="ImageCollection companion QA",
        official_url=CATALOG_BASE + "COPERNICUS_S2_CLOUD_PROBABILITY",
        tasks=("vegetation-index", "water-flood", "classification", "change-detection"),
        keywords=("s2cloudless", "cloud probability", "probability", "云概率", "云检测", "s2cloudless"),
        scale="10 m probability band",
        temporal="Companion to Sentinel-2 imagery; verify dates in catalog",
        bands=("probability",),
        qa="Join to S2 by system:index, threshold probability, and optionally combine with shadow logic.",
        best_for="S2 workflows that need the s2cloudless probability pattern.",
        cautions=("Highly reflective surfaces can look cloud-like; inspect probability and mask layers.",),
        workflow=("Join to source S2 collection.", "Mask probability below a documented threshold.", "Show mask layer in notebook QA."),
        read=("references/dataset-qa-patterns.md",),
    ),
    Dataset(
        id="COPERNICUS/S1_GRD",
        title="Sentinel-1 SAR GRD",
        kind="ImageCollection",
        official_url=CATALOG_BASE + "COPERNICUS_S1_GRD",
        tasks=("water-flood", "change-detection", "disaster", "wetland", "rice"),
        keywords=(
            "sentinel-1",
            "sentinel 1",
            "s1",
            "sar",
            "radar",
            "flood",
            "inundation",
            "water",
            "storm",
            "all weather",
            "cloudy",
            "哨兵1",
            "哨兵-1",
            "雷达",
            "洪水",
            "淹没",
            "积水",
            "水灾",
            "阴天",
            "多云",
            "全天候",
        ),
        scale="Commonly 10 m; depends on acquisition/product",
        temporal="2014-present; updated frequently",
        bands=("VV", "VH", "HH", "HV", "angle"),
        qa="Filter instrumentMode, orbitProperties_pass, transmitterReceiverPolarisation, resolution_meters, and date.",
        best_for="Flood mapping when optical imagery is cloudy; pre/post water or backscatter change.",
        cautions=(
            "Speckle, terrain shadow, wind roughness, and urban double-bounce affect thresholds.",
            "Do not use a universal dB threshold without local visual/numeric probes.",
        ),
        workflow=("Build pre/post composites.", "Optionally smooth or ratio/difference.", "Threshold candidate water.", "Summarize area with pixelArea."),
        read=("references/task-patterns.md", "references/dataset-qa-patterns.md"),
    ),
    Dataset(
        id="NASA/HLS/HLSL30/v002",
        title="HLS Landsat 8/9 L30 Surface Reflectance NBAR v2",
        kind="ImageCollection",
        official_url=CATALOG_BASE + "NASA_HLS_HLSL30_v002",
        tasks=("cross-sensor-harmonization", "vegetation-index", "time-series", "change-detection"),
        keywords=(
            "hls", "hlsl30", "landsat sentinel", "landsat and sentinel", "cross sensor", "harmonization",
            "harmonized", "sentinel-2", "common bands", "nbar", "30m", "dense time series",
            "跨传感器", "传感器一致化", "陆地卫星和哨兵", "高频时序",
        ),
        scale="30 m common HLS grid",
        temporal="Landsat 8/9 HLS observations from 2013; verify current catalog coverage",
        bands=("B2", "B3", "B4", "B5", "B6", "B7", "Fmask", "SZA", "VZA"),
        qa="Use HLS Fmask; keep sensor identity and inspect valid observation count.",
        best_for="Combining Landsat 8/9 with HLS Sentinel-2 S30 in a common 30 m NBAR series.",
        cautions=(
            "Harmonization reduces but does not eliminate residual sensor and sampling differences.",
            "Do not apply Landsat Collection 2 DN scale coefficients to HLS assets.",
        ),
        workflow=("Pair with HLSS30.", "Mask Fmask cloud/adjacency/shadow/snow.", "Rename common bands.", "Validate paired stable-target differences."),
        read=("references/cross-sensor-harmonization.md", "references/temporal-compositing.md"),
    ),
    Dataset(
        id="NASA/HLS/HLSS30/v002",
        title="HLS Sentinel-2 S30 Surface Reflectance NBAR v2",
        kind="ImageCollection",
        official_url=CATALOG_BASE + "NASA_HLS_HLSS30_v002",
        tasks=("cross-sensor-harmonization", "vegetation-index", "time-series", "change-detection"),
        keywords=(
            "hls", "hlss30", "landsat sentinel", "landsat and sentinel", "cross sensor", "harmonization",
            "harmonized", "sentinel-2", "common bands", "nbar", "30m", "dense time series",
            "跨传感器", "传感器一致化", "陆地卫星和哨兵", "高频时序",
        ),
        scale="30 m common HLS grid",
        temporal="Sentinel-2 HLS observations from 2015; verify current catalog coverage",
        bands=("B2", "B3", "B4", "B8A", "B11", "B12", "Fmask", "SZA", "VZA"),
        qa="Use HLS Fmask; use B8A as the common narrow-NIR mapping and retain sensor identity.",
        best_for="Combining Sentinel-2 with HLS Landsat L30 in a common 30 m NBAR series.",
        cautions=(
            "Sentinel-2 red-edge and broad-NIR bands are not all common Landsat comparison bands.",
            "Combined revisit does not guarantee a valid observation after QA.",
        ),
        workflow=("Pair with HLSL30.", "Mask Fmask cloud/adjacency/shadow/snow.", "Rename common bands.", "Validate paired stable-target differences."),
        read=("references/cross-sensor-harmonization.md", "references/temporal-compositing.md"),
    ),
    Dataset(
        id="LANDSAT/LC08/C02/T1_L2 and LANDSAT/LC09/C02/T1_L2",
        title="Landsat 8/9 Collection 2 Tier 1 Level 2",
        kind="ImageCollection",
        official_url=CATALOG_BASE + "LANDSAT_LC08_C02_T1_L2",
        tasks=("vegetation-index", "lst", "change-detection", "water-flood", "classification"),
        keywords=(
            "landsat",
            "landsat 8",
            "landsat 9",
            "long term",
            "historical",
            "surface temperature",
            "lst",
            "thermal",
            "ndvi",
            "water",
            "change",
            "陆地卫星",
            "兰德赛特",
            "长时序",
            "历史",
            "地表温度",
            "热岛",
            "热红外",
            "植被",
            "水体",
        ),
        scale="30 m optical reflectance; thermal bands have their own native scale",
        temporal="2013-present for LC08; LC09 from 2021-present",
        bands=("SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7", "ST_B10", "QA_PIXEL", "QA_RADSAT"),
        qa="Apply Collection 2 scale factors, QA_PIXEL fill/cloud/shadow/snow bits, and QA_RADSAT before analysis.",
        best_for="Medium-resolution historical change, LST/urban heat, vegetation/water with longer time span than S2.",
        cautions=(
            "Raw L2 optical/thermal bands require scale factors.",
            "QA mask is required before composites; sensor mixing needs documentation.",
        ),
        workflow=("Apply scale factors.", "Mask QA_PIXEL.", "Build seasonal composite.", "Use explicit scale in reducers/exports."),
        read=("references/dataset-qa-patterns.md", "references/task-patterns.md"),
    ),
    Dataset(
        id="MODIS/061/MOD13Q1",
        title="MODIS Terra Vegetation Indices 16-Day Global 250 m",
        kind="ImageCollection",
        official_url=CATALOG_BASE + "MODIS_061_MOD13Q1",
        tasks=("vegetation-index", "time-series", "drought", "phenology"),
        keywords=("modis", "mod13q1", "ndvi", "evi", "phenology", "time series", "drought", "vegetation", "月度", "16天", "时间序列", "植被", "物候", "干旱"),
        scale="250 m",
        temporal="2000-present; 16-day cadence",
        bands=("NDVI", "EVI", "DetailedQA", "SummaryQA"),
        qa="Scale NDVI/EVI by 0.0001 and filter with DetailedQA or SummaryQA.",
        best_for="Long, dense vegetation time series over large regions or many polygons.",
        cautions=("Do not mix directly with S2/Landsat pixel statistics without explaining scale mismatch.",),
        workflow=("Map image collection to date/value features.", "Apply QA and scale factor.", "Export FeatureCollection/CSV for long series."),
        read=("references/dataset-qa-patterns.md", "references/workflows.md"),
    ),
    Dataset(
        id="MODIS/061/MOD11A2",
        title="MODIS Terra Land Surface Temperature and Emissivity 8-Day 1 km",
        kind="ImageCollection",
        official_url=CATALOG_BASE + "MODIS_061_MOD11A2",
        tasks=("lst", "urban-heat", "climate", "time-series"),
        keywords=("mod11a2", "lst", "land surface temperature", "surface temperature", "urban heat", "heat island", "modis", "地表温度", "热岛", "城市热岛", "温度", "热环境"),
        scale="~1 km",
        temporal="2000-present; 8-day cadence",
        bands=("LST_Day_1km", "LST_Night_1km", "QC_Day", "QC_Night"),
        qa="Use QC_Day/QC_Night and convert scaled Kelvin to Celsius when needed.",
        best_for="Coarse land-surface-temperature time series and urban heat screening.",
        cautions=("MOD11A2 averages daily values; still inspect QA and missing/cloud effects.",),
        workflow=("Filter date/AOI.", "Apply scale conversion.", "Use QC mask.", "Summarize by zones or export time series."),
        read=("references/dataset-qa-patterns.md", "references/task-patterns.md"),
    ),
    Dataset(
        id="NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG",
        title="VIIRS Stray Light Corrected Monthly Nighttime Lights",
        kind="ImageCollection",
        official_url=CATALOG_BASE + "NOAA_VIIRS_DNB_MONTHLY_V1_VCMSLCFG",
        tasks=("nighttime-lights", "urban", "economic-proxy", "change-detection", "time-series"),
        keywords=("viirs", "nighttime", "night lights", "lights", "urbanization", "economic", "city", "夜间灯光", "夜光", "灯光", "城市扩张", "经济", "人类活动"),
        scale="~463.83 m",
        temporal="2014-present monthly composites; verify latest catalog date",
        bands=("avg_rad", "cf_cvg"),
        qa="Use coverage/quality context and mask unstable/noisy areas when appropriate.",
        best_for="Monthly night-light trend, urban expansion proxy, activity/economic proxy maps.",
        cautions=("Night lights are a proxy; saturation, gas flares, fires, lunar/stray-light artifacts can mislead.",),
        workflow=("Build monthly/annual composites.", "Mask low coverage/noise.", "Summarize by zones.", "Report proxy limitations."),
        read=("references/task-patterns.md",),
    ),
    Dataset(
        id="GOOGLE/DYNAMICWORLD/V1",
        title="Dynamic World V1 Near Real-Time Land Cover",
        kind="ImageCollection",
        official_url=CATALOG_BASE + "GOOGLE_DYNAMICWORLD_V1",
        tasks=("classification", "land-cover", "urban", "crop", "water-flood", "change-detection"),
        keywords=("dynamic world", "land cover", "classification", "label", "probability", "built", "crop", "trees", "土地覆盖", "地物分类", "分类", "建筑", "农田", "森林", "水体"),
        scale="10 m",
        temporal="Near real-time with Sentinel-2 L1C source imagery",
        bands=("label", "water", "trees", "grass", "flooded_vegetation", "crops", "shrub_and_scrub", "built", "bare", "snow_and_ice"),
        qa="Use probability bands and confidence thresholds; do not treat label as ground truth.",
        best_for="Fast land-cover maps, class probability inspection, land-cover area summaries.",
        cautions=("Mean of label is meaningless; summarize class counts/area or probabilities.",),
        workflow=("Filter by AOI/date.", "Use mode label or probability threshold.", "Group pixelArea by class.", "Export table and map separately."),
        read=("references/dataset-qa-patterns.md", "references/task-patterns.md"),
    ),
    Dataset(
        id="ESA/WorldCover/v200",
        title="ESA WorldCover 10 m 2021 v200",
        kind="ImageCollection",
        official_url=CATALOG_BASE + "ESA_WorldCover_v200",
        tasks=("classification", "land-cover", "baseline", "area-by-class"),
        keywords=("worldcover", "esa", "land cover", "baseline", "class area", "土地覆盖", "基准", "分类面积", "地类", "esa"),
        scale="10 m",
        temporal="2021 baseline product",
        bands=("Map",),
        qa="Categorical product; use palettes, legends, mode/count/grouped area reducers.",
        best_for="Static land-cover baseline when classes match the question.",
        cautions=("Do not average class labels; use grouped area/count summaries.",),
        workflow=("Clip to AOI.", "Add class legend.", "Compute area by class using pixelArea grouped reducer.", "Export CSV."),
        read=("references/dataset-qa-patterns.md", "references/task-patterns.md"),
    ),
    Dataset(
        id="JRC/GSW1_4/GlobalSurfaceWater",
        title="JRC Global Surface Water Mapping Layers v1.4",
        kind="Image",
        official_url=CATALOG_BASE + "JRC_GSW1_4_GlobalSurfaceWater",
        tasks=("water-flood", "water-history", "change-detection", "baseline"),
        keywords=("jrc", "global surface water", "surface water", "water occurrence", "water history", "lake", "river", "水体", "长期水体", "水体变化", "水频率", "湖泊", "河流"),
        scale="30 m Landsat-derived",
        temporal="Maps surface-water history from 1984 to 2021",
        bands=("occurrence", "change_abs", "change_norm", "seasonality", "recurrence", "transition", "max_extent"),
        qa="Use as historical water context, not necessarily event flood truth.",
        best_for="Long-term water occurrence, permanent/seasonal water baseline, water-change context.",
        cautions=("Event floods after 2021 need another event dataset such as S1/S2/Landsat.",),
        workflow=("Use occurrence/seasonality as background.", "Threshold documented water occurrence.", "Compare event water mask against baseline if needed."),
        read=("references/task-patterns.md", "references/dataset-qa-patterns.md"),
    ),
    Dataset(
        id="WorldPop/GP/100m/pop",
        title="WorldPop Global Project Population 100 m",
        kind="ImageCollection",
        official_url=CATALOG_BASE + "WorldPop_GP_100m_pop",
        tasks=("population", "exposure", "risk", "zonal-statistics"),
        keywords=("population", "worldpop", "exposure", "people", "risk", "vulnerability", "flood exposure", "人口", "暴露", "风险", "脆弱性", "受灾人口", "人口暴露"),
        scale="~100 m",
        temporal="Annual estimates available for 2000-2021; verify country/year coverage",
        bands=("population",),
        qa="Check year, country coverage, units as people per pixel, and license/terms.",
        best_for="Population exposure estimates at relatively fine global scale.",
        cautions=("Population surface uncertainty can dominate exposure estimates; cite year/source.",),
        workflow=("Choose year closest to hazard date.", "Mask population by hazard.", "Sum population with explicit scale and zones.", "Export table."),
        read=("references/task-patterns.md", "references/dataset-qa-patterns.md"),
    ),
    Dataset(
        id="JRC/GHSL/P2023A/GHS_POP",
        title="GHSL Global Population Surfaces 1975-2030 P2023A",
        kind="ImageCollection",
        official_url=CATALOG_BASE + "JRC_GHSL_P2023A_GHS_POP",
        tasks=("population", "urban", "exposure", "long-term", "zonal-statistics"),
        keywords=("ghsl", "population", "exposure", "urban", "built", "long term", "人口", "城市", "建成区", "长期", "暴露", "风险"),
        scale="Grid-cell population; verify resolution per epoch in catalog",
        temporal="1975-2030 in 5-year intervals and projections",
        bands=("population_count",),
        qa="Pick epoch deliberately and document projection/projection year.",
        best_for="Long-term population or urban exposure where 5-year epochs are acceptable.",
        cautions=("Projected years are not observations; avoid false precision.",),
        workflow=("Select epoch.", "Align hazard/time window.", "Sum by zones with explicit scale.", "Report projection caveat."),
        read=("references/task-patterns.md", "references/dataset-qa-patterns.md"),
    ),
    Dataset(
        id="GOOGLE/Research/open-buildings/v3/polygons",
        title="Open Buildings V3 Polygons",
        kind="FeatureCollection",
        official_url=CATALOG_BASE + "GOOGLE_Research_open-buildings_v3_polygons",
        tasks=("buildings", "exposure", "urban", "infrastructure"),
        keywords=("open buildings", "building", "buildings", "footprint", "infrastructure", "settlement", "建筑", "建筑物", "房屋", "足迹", "基础设施", "暴露"),
        scale="Vector building polygons derived from high-resolution imagery; regional coverage",
        temporal="Versioned static product; verify geography/coverage",
        bands=("geometry", "confidence", "area_in_meters"),
        qa="Filter confidence and coverage area; respect regional limitations.",
        best_for="Building exposure and settlement structure in supported regions.",
        cautions=("Huge FeatureCollection; filter spatially before any operation.", "Coverage is not global."),
        workflow=("Filter bounds first.", "Filter confidence.", "Intersect with hazard or AOI.", "Export counts/area, not full global table."),
        read=("references/task-patterns.md", "references/gee-agent-playbook.md"),
    ),
    Dataset(
        id="COPERNICUS/DEM/GLO30_2024_1",
        title="Copernicus DEM GLO-30 (2024_1)",
        kind="ImageCollection",
        official_url=CATALOG_BASE + "COPERNICUS_DEM_GLO30_2024_1",
        tasks=("terrain", "slope", "hydrology", "orthorectification", "flood-context"),
        keywords=("dem", "elevation", "terrain", "slope", "hillshade", "watershed", "高程", "地形", "坡度", "坡向", "阴影", "流域"),
        scale="30 m",
        temporal="Static DEM product",
        bands=("DEM",),
        qa="Preserve or explicitly choose projection/scale for terrain derivatives.",
        best_for="Elevation context, slope/aspect/hillshade, hydrologic context.",
        cautions=("Terrain derivatives are projection-sensitive; avoid careless reproject over huge AOIs.",),
        workflow=("Mosaic/filter to AOI.", "Compute terrain derivative at justified scale.", "Add hillshade/slope probe.", "Export with explicit CRS/scale."),
        read=("references/dataset-qa-patterns.md", "references/task-patterns.md"),
    ),
]


def normalize(text: str) -> str:
    return text.casefold()


def score_dataset(dataset: Dataset, query: str) -> int:
    text = normalize(query)
    score = 0
    id_text = dataset.id.casefold()
    if id_text in text:
        score += 12
    for task in dataset.tasks:
        if task.replace("-", " ") in text or task in text:
            score += 5
    for keyword in dataset.keywords:
        key = keyword.casefold()
        if key and key in text:
            score += 4 if len(key) > 3 else 2
    for band in dataset.bands:
        if band.casefold() in text:
            score += 2
    return score


def find_datasets(query: str, limit: int) -> list[tuple[int, Dataset]]:
    ranked = sorted(((score_dataset(dataset, query), dataset) for dataset in DATASETS), key=lambda item: (-item[0], item[1].id))
    matches = [(score, dataset) for score, dataset in ranked if score > 0]
    return matches[: max(1, limit)]


def geemap_ai_matches(query: str, limit: int) -> list[dict[str, object]]:
    try:
        from geemap.ai import EarthEngineDatasetIndex  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency path
        return [{"error": f"geemap AI dataset index unavailable: {exc}"}]
    try:
        index = EarthEngineDatasetIndex()
        matches = index.find_top_matches(query, results=limit)
    except Exception as exc:  # pragma: no cover - optional network/package path
        return [{"error": f"geemap AI dataset index failed: {exc}"}]
    if hasattr(matches, "to_dict"):
        return matches.to_dict(orient="records")  # type: ignore[no-any-return]
    return [{"result": str(matches)}]


def expanded_catalog_matches(query: str, limit: int) -> list[dict[str, object]]:
    try:
        from dataset_catalog_engine import load_catalog, search_catalog
    except Exception as exc:
        return [{"error": f"expanded catalog unavailable: {exc}"}]
    try:
        catalog, source = load_catalog(catalog_mode="auto", fetch_seconds=12)
        payload = search_catalog(catalog, query, limit=limit)
    except Exception as exc:
        return [{"error": f"expanded catalog search failed: {exc}"}]
    results = payload["candidates"]
    return results or [
        {
            "source": source.get("source") or "official/community catalog",
            "note": payload.get("clarification") or "No matching official/community entries were found.",
            "needs_clarification": True,
        }
    ]


def candidate_record(score: int, dataset: Dataset) -> dict[str, object]:
    record = asdict(dataset)
    record["score"] = score
    record["verification_rule"] = "Verify id, bands, scale/QA, dates, terms, and examples in the official catalog URL before coding."
    return record


def print_text(results: list[tuple[int, Dataset]], include_workflow: bool) -> None:
    for index, (score, dataset) in enumerate(results, start=1):
        print(f"{index}. {dataset.id} - {dataset.title}")
        print(f"   score: {score}")
        print(f"   kind: {dataset.kind}")
        print(f"   official: {dataset.official_url}")
        print(f"   scale/time: {dataset.scale}; {dataset.temporal}")
        print(f"   bands: {', '.join(dataset.bands)}")
        print(f"   QA: {dataset.qa}")
        print(f"   best for: {dataset.best_for}")
        print(f"   cautions: {'; '.join(dataset.cautions)}")
        print(f"   read: {', '.join(dataset.read)}")
        if include_workflow:
            print(f"   workflow: {' -> '.join(dataset.workflow)}")


def print_expanded_catalog(records: list[dict[str, object]]) -> None:
    if not records:
        return
    print("\nExpanded official/community catalog candidates:")
    for index, item in enumerate(records, start=1):
        if item.get("error") or item.get("note"):
            print(f"{index}. {item.get('error') or item.get('note')}")
            continue
        print(f"{index}. {item.get('id')} - {item.get('title')}")
        print(f"   source: {item.get('source')}  kind: {item.get('kind')}")
        if item.get("provider"):
            print(f"   provider: {item.get('provider')}")
        if item.get("url"):
            print(f"   catalog: {item.get('url')}")


def smoke() -> int:
    cases = {
        "2024 Sentinel-2 NDVI with cloud mask": ("COPERNICUS/S2_SR_HARMONIZED", "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"),
        "洪水淹没范围和人口暴露": ("COPERNICUS/S1_GRD", "WorldPop/GP/100m/pop"),
        "夜间灯光城市扩张": ("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG",),
        "地表温度热岛": ("MODIS/061/MOD11A2",),
        "土地覆盖分类统计": ("GOOGLE/DYNAMICWORLD/V1", "ESA/WorldCover/v200"),
        "建筑物提取和风险暴露": ("GOOGLE/Research/open-buildings/v3/polygons",),
    }
    failed: list[str] = []
    for query, expected_ids in cases.items():
        found = {dataset.id for _, dataset in find_datasets(query, limit=5)}
        if not any(expected in found for expected in expected_ids):
            failed.append(f"{query!r}: expected one of {expected_ids}, got {sorted(found)}")
    if failed:
        for item in failed:
            print("FAIL " + item)
        return 1
    print(f"search_gee_dataset smoke passed: {len(cases)} cases")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="*", help="Dataset need, task prompt, or analysis goal")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--workflow", action="store_true", help="Print concise workflow hints")
    parser.add_argument("--geemap-ai", action="store_true", help="Also try geemap.ai EarthEngineDatasetIndex")
    parser.add_argument("--no-expanded-catalog", action="store_true", help="Skip official STAC + community catalog expansion")
    parser.add_argument("--smoke", action="store_true", help="Run built-in bilingual smoke tests")
    args = parser.parse_args()

    if args.smoke:
        return smoke()

    query = " ".join(args.query).strip()
    if not query:
        parser.error("provide a dataset search query")

    results = find_datasets(query, args.limit)
    catalog_candidates = [] if args.no_expanded_catalog else expanded_catalog_matches(query, args.limit)
    if args.json:
        payload: dict[str, object] = {"query": query, "candidates": [candidate_record(score, dataset) for score, dataset in results]}
        if catalog_candidates:
            payload["catalog_candidates"] = catalog_candidates
        if args.geemap_ai:
            payload["geemap_ai_candidates"] = geemap_ai_matches(query, args.limit)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text(results, include_workflow=args.workflow)
        print_expanded_catalog(catalog_candidates)
        if args.geemap_ai:
            print("\nGeemap AI candidates:")
            print(json.dumps(geemap_ai_matches(query, args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
