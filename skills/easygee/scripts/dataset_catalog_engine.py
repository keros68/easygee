#!/usr/bin/env python
"""Bilingual discovery, recommendation, comparison, and verification for GEE datasets.

The engine deliberately uses only the Python standard library. It consumes the
official Earth Engine STAC and GEE Community Catalog records already assembled
by ``create_map_console.build_catalog`` and adds a small geospatial ontology,
task-role planning, provenance-aware ranking, and deprecation handling.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


SEARCH_FIELDS = ("id", "label", "tags", "description", "provider", "type", "category", "license")
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._+/-]*|[\u3400-\u9fff]+", re.IGNORECASE)
RESOLUTION_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*(km|m)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Concept:
    aliases: tuple[str, ...]
    preferred_ids: tuple[str, ...] = ()


CONCEPTS: dict[str, Concept] = {
    "terrain-dem": Concept(
        ("dem", "digital elevation", "elevation", "terrain", "slope", "hillshade", "高程", "数字高程", "地形", "坡度", "山地"),
        ("COPERNICUS/DEM/GLO30_2024_1", "USGS/SRTMGL1_003", "JAXA/ALOS/AW3D30/V4_1", "MERIT/DEM/v1_0_3"),
    ),
    "soil-moisture": Concept(
        ("soil moisture", "smap", "root zone moisture", "surface moisture", "土壤湿度", "土壤水分", "墒情"),
        ("NASA/SMAP/SPL4SMGP/008", "NASA/SMAP/SPL3SMP_E/006", "ECMWF/ERA5_LAND/HOURLY"),
    ),
    "precipitation": Concept(
        ("precipitation", "rainfall", "rain", "gpm", "chirps", "era5", "降水", "降雨", "暴雨", "雨量"),
        ("NASA/GPM_L3/IMERG_V07", "UCSB-CHG/CHIRPS/DAILY", "ECMWF/ERA5_LAND/HOURLY"),
    ),
    "flood-water": Concept(
        ("flood", "inundation", "surface water", "water extent", "water occurrence", "洪水", "淹没", "积水", "水体", "洪涝"),
        ("COPERNICUS/S1_GRD", "JRC/GSW1_4/GlobalSurfaceWater", "GLOBAL_FLOOD_DB/MODIS_EVENTS/V1"),
    ),
    "vegetation": Concept(
        ("vegetation", "ndvi", "evi", "greenness", "phenology", "crop", "植被", "长势", "物候", "作物", "农田"),
        ("COPERNICUS/S2_SR_HARMONIZED", "MODIS/061/MOD13Q1", "LANDSAT/LC09/C02/T1_L2"),
    ),
    "optical": Concept(
        ("optical", "sentinel-2", "sentinel 2", "landsat", "rgb", "surface reflectance", "光学", "真彩色", "表面反射率"),
        ("COPERNICUS/S2_SR_HARMONIZED", "LANDSAT/LC09/C02/T1_L2"),
    ),
    "radar": Concept(
        ("radar", "sar", "sentinel-1", "sentinel 1", "backscatter", "雷达", "哨兵1", "后向散射"),
        ("COPERNICUS/S1_GRD",),
    ),
    "land-cover": Concept(
        ("land cover", "landcover", "classification", "dynamic world", "worldcover", "土地覆盖", "地类", "分类"),
        ("GOOGLE/DYNAMICWORLD/V1", "ESA/WorldCover/v200"),
    ),
    "surface-temperature": Concept(
        ("land surface temperature", "surface temperature", "lst", "thermal", "heat island", "地表温度", "热岛", "热红外"),
        ("MODIS/061/MOD11A2", "LANDSAT/LC09/C02/T1_L2"),
    ),
    "population-exposure": Concept(
        ("population", "people", "exposure", "vulnerability", "worldpop", "ghsl", "人口", "暴露", "受灾人口", "脆弱性"),
        ("WorldPop/GP/100m/pop", "JRC/GHSL/P2023A/GHS_POP"),
    ),
    "buildings": Concept(
        ("building", "buildings", "footprint", "settlement", "infrastructure", "建筑", "建筑物", "房屋", "基础设施"),
        ("GOOGLE/Research/open-buildings/v3/polygons",),
    ),
    "night-lights": Concept(
        ("night light", "nighttime light", "viirs", "urbanization", "夜间灯光", "夜光", "城市扩张"),
        ("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG",),
    ),
    "fire": Concept(
        ("fire", "wildfire", "burned area", "active fire", "野火", "火灾", "过火区", "火点"),
        ("MODIS/061/MCD64A1", "FIRMS"),
    ),
    "forest": Concept(
        ("forest", "tree cover", "canopy", "deforestation", "森林", "林地", "树冠", "毁林"),
        ("UMD/hansen/global_forest_change_2023_v1_11",),
    ),
    "snow-ice": Concept(
        ("snow", "ice", "glacier", "snow cover", "积雪", "冰川", "冰雪"),
        ("MODIS/061/MOD10A1",),
    ),
    "climate": Concept(
        ("climate", "weather", "temperature", "wind", "era5", "气候", "气象", "温度", "风速"),
        ("ECMWF/ERA5_LAND/HOURLY",),
    ),
    "air-quality": Concept(
        ("air quality", "pollution", "no2", "aerosol", "空气质量", "污染", "二氧化氮", "气溶胶"),
        ("COPERNICUS/S5P/OFFL/L3_NO2",),
    ),
    "ocean": Concept(
        ("ocean", "sea surface", "sst", "chlorophyll", "marine", "海洋", "海表", "叶绿素"),
    ),
    "hydrology": Concept(
        ("hydrology", "watershed", "river", "runoff", "streamflow", "水文", "流域", "河流", "径流"),
        ("WWF/HydroSHEDS", "MERIT/Hydro/v1_0_1"),
    ),
}


TASK_MARKERS = (
    "map", "mapping", "monitor", "estimate", "analyze", "analysis", "detect", "extract", "assess", "risk",
    "create", "build", "compare", "summarize", "做", "制作", "绘制", "制图", "监测", "估算", "分析", "提取", "识别", "评估", "风险", "变化",
)


TASK_RECIPES: tuple[dict[str, Any], ...] = (
    {
        "id": "flood-risk",
        "markers": ("flood", "inundation", "洪水", "洪涝", "淹没", "积水"),
        "roles": (
            ("event_hazard", "flood water sentinel-1 radar 洪水 淹没 雷达"),
            ("historical_baseline", "surface water occurrence historical baseline 长期水体"),
            ("terrain", "dem elevation terrain slope 高程 地形"),
            ("forcing", "rainfall precipitation storm 降雨 暴雨"),
            ("exposure", "population buildings exposure 人口 建筑 暴露"),
        ),
    },
    {
        "id": "vegetation-monitoring",
        "markers": ("ndvi", "vegetation", "crop", "植被", "长势", "作物", "农田"),
        "roles": (
            ("primary_imagery", "sentinel-2 surface reflectance vegetation ndvi 光学 植被"),
            ("quality_mask", "cloud score cloud probability qa sentinel-2 云掩膜"),
            ("long_term_baseline", "modis vegetation index time series 长时序 植被"),
        ),
    },
    {
        "id": "soil-moisture-monitoring",
        "markers": ("soil moisture", "smap", "土壤湿度", "土壤水分", "墒情"),
        "roles": (
            ("primary_observation", "smap soil moisture 土壤湿度"),
            ("meteorological_context", "era5 precipitation temperature climate 降水 气温"),
        ),
    },
    {
        "id": "land-cover",
        "markers": ("land cover", "classification", "土地覆盖", "地类", "分类"),
        "roles": (
            ("dynamic_product", "dynamic world land cover probability 土地覆盖"),
            ("static_baseline", "worldcover land cover baseline 地类 基准"),
            ("source_imagery", "sentinel-2 surface reflectance optical 光学"),
        ),
    },
)


def normalize(text: Any) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    value = re.sub(r"[_|,，;；:：()（）\[\]{}]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens(text: Any) -> set[str]:
    result: set[str] = set()
    for token in TOKEN_RE.findall(normalize(text)):
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            if len(token) <= 4:
                result.add(token)
            else:
                result.update(token[index : index + 2] for index in range(len(token) - 1))
                result.update(token[index : index + 3] for index in range(len(token) - 2))
        elif len(token) > 1:
            result.add(token)
    return result


def contains_term(text: str, term: str) -> bool:
    """Match CJK by substring and Latin terms on alphanumeric boundaries."""
    normalized_text = normalize(text)
    normalized_term = normalize(term)
    if not normalized_term:
        return False
    if re.search(r"[\u3400-\u9fff]", normalized_term) or " " in normalized_term:
        return normalized_term in normalized_text
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", normalized_text))


def concepts_for_query(query: str) -> list[str]:
    text = normalize(query)
    found: list[str] = []
    for name, concept in CONCEPTS.items():
        if any(contains_term(text, alias) for alias in concept.aliases):
            found.append(name)
    return found


def detect_query_mode(query: str) -> str:
    text = normalize(query)
    if re.search(r"(?:projects/[^\s]+/assets/)?[a-z0-9_.-]+(?:/[a-z0-9_.-]+){1,}", text, re.IGNORECASE):
        return "exact"
    if any(marker in text for marker in TASK_MARKERS) or len(text) >= 28:
        return "task"
    return "theme"


def item_text(item: dict[str, Any], fields: Iterable[str] = SEARCH_FIELDS) -> str:
    return normalize(" ".join(str(item.get(field) or "") for field in fields))


def source_name(item: dict[str, Any]) -> str:
    source = normalize(item.get("source") or "official")
    if source in {"google", "stac", "earth engine", "gee"}:
        return "official"
    return source or "official"


def is_deprecated(item: dict[str, Any]) -> bool:
    value = item.get("deprecated")
    if isinstance(value, bool):
        return value
    return normalize(value) in {"true", "1", "yes", "deprecated"}


def parse_resolution_m(item: dict[str, Any]) -> float | None:
    # Labels and tags are safer than descriptions, which frequently contain soil depths.
    text = " ".join(str(item.get(field) or "") for field in ("label", "tags"))
    values = []
    for raw, unit in RESOLUTION_RE.findall(text):
        value = float(raw) * (1000 if unit.casefold() == "km" else 1)
        if value > 0:
            values.append(value)
    return min(values) if values else None


def load_catalog(
    *, catalog_mode: str = "auto", refresh: bool = False, fetch_seconds: int = 12
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from create_map_console import build_catalog

    return build_catalog(
        [],
        include_remote=True,
        catalog_mode=catalog_mode,
        refresh_catalog=refresh,
        catalog_fetch_seconds=max(1, fetch_seconds),
    )


def _matches_filter(item: dict[str, Any], filters: dict[str, Any]) -> bool:
    if not filters.get("include_deprecated") and is_deprecated(item):
        return False
    for key in ("source", "provider", "category", "kind"):
        expected = normalize(filters.get(key))
        if not expected:
            continue
        item_key = "type" if key == "kind" else key
        actual = source_name(item) if key == "source" else normalize(item.get(item_key))
        if expected not in actual:
            return False
    max_resolution = filters.get("max_resolution_m")
    if max_resolution is not None:
        resolution = parse_resolution_m(item)
        if resolution is None or resolution > float(max_resolution):
            return False
    return True


def _score_item(item: dict[str, Any], query: str, query_concepts: Sequence[str], mode: str) -> tuple[float, list[str]]:
    query_text = normalize(query)
    query_id = query_text.strip("/")
    record_id = normalize(item.get("id"))
    label = normalize(item.get("label"))
    field_text = {
        field: normalize(item.get(field))
        for field in ("tags", "description", "provider", "type", "category")
    }
    query_tokens = tokens(query)
    reasons: list[str] = []
    score = 0.0

    if mode == "exact" and query_id and (record_id == query_id or record_id.endswith("/" + query_id)):
        score += 120
        reasons.append("exact dataset id")
    elif mode == "exact" and query_text and query_text == label:
        score += 90
        reasons.append("exact title")
    elif len(query_text) >= 4 and (query_text in record_id or query_text in label):
        score += 34
        reasons.append("id/title phrase")

    overlaps: Counter[str] = Counter()
    for token in query_tokens:
        if contains_term(record_id, token):
            overlaps["id"] += 1
            score += 8
        if contains_term(label, token):
            overlaps["title"] += 1
            score += 7
        if contains_term(field_text["tags"], token) or contains_term(field_text["category"], token):
            overlaps["tags/category"] += 1
            score += 4
        if contains_term(field_text["provider"], token) or contains_term(field_text["type"], token):
            overlaps["metadata"] += 1
            score += 2
        if contains_term(field_text["description"], token):
            overlaps["description"] += 1
            score += 1
    for field, count in overlaps.most_common():
        reasons.append(f"{field} matched ({count})")

    haystack = item_text(item)
    upper_id = str(item.get("id") or "")
    for concept_name in query_concepts:
        concept = CONCEPTS[concept_name]
        alias_hits = [alias for alias in concept.aliases if contains_term(haystack, alias)]
        if alias_hits:
            score += min(18, 7 + len(alias_hits) * 2)
            reasons.append(f"concept: {concept_name}")
        if upper_id in concept.preferred_ids:
            score += 24
            reasons.append(f"preferred current product for {concept_name}")

    source = source_name(item)
    if source == "official":
        score += 4
        reasons.append("official catalog")
    elif source == "curated":
        score += 2
    if is_deprecated(item):
        score -= 35
        reasons.append("deprecated penalty")
    if mode == "exact" and not (query_text in record_id or query_text in label):
        score -= 10
    return score, reasons


def candidate_record(item: dict[str, Any], score: float, reasons: Sequence[str], role: str | None = None) -> dict[str, Any]:
    confidence = "high" if score >= 55 else "medium" if score >= 24 else "low"
    record: dict[str, Any] = {
        "id": item.get("id"),
        "title": item.get("label") or item.get("id"),
        "score": round(score, 2),
        "confidence": confidence,
        "source": source_name(item),
        "kind": item.get("type"),
        "provider": item.get("provider"),
        "category": item.get("category"),
        "resolution_m": parse_resolution_m(item),
        "start_date": item.get("startDate"),
        "end_date": item.get("endDate"),
        "license": item.get("license"),
        "deprecated": is_deprecated(item),
        "url": item.get("url"),
        "sample_code": item.get("sampleCode"),
        "match_reasons": list(dict.fromkeys(reasons))[:8],
        "verification_rule": (
            "Verify id, bands, units/scale, QA, temporal and AOI coverage, license, and deprecation status before analysis."
            if source_name(item) == "official"
            else "Verify the community asset exists and review its source page, sample code, license, bands, and update status before analysis."
        ),
    }
    if role:
        record["role"] = role
    return record


def search_catalog(
    catalog: Sequence[dict[str, Any]],
    query: str,
    *,
    limit: int = 8,
    mode: str = "auto",
    filters: dict[str, Any] | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    clean_query = query.strip()
    query_mode = detect_query_mode(clean_query) if mode == "auto" else mode
    filters = dict(filters or {})
    query_concepts = concepts_for_query(clean_query)
    ranked: list[tuple[float, str, dict[str, Any], list[str]]] = []
    for item in catalog:
        if not _matches_filter(item, filters):
            continue
        score, reasons = _score_item(item, clean_query, query_concepts, query_mode)
        threshold = 10 if query_mode != "exact" else 20
        if score >= threshold:
            ranked.append((score, str(item.get("id") or ""), item, reasons))
    ranked.sort(key=lambda row: (-row[0], is_deprecated(row[2]), 0 if source_name(row[2]) == "official" else 1, row[1].casefold()))
    candidates = [candidate_record(item, score, reasons, role) for score, _, item, reasons in ranked[: max(1, limit)]]
    return {
        "query": clean_query,
        "query_mode": query_mode,
        "detected_concepts": query_concepts,
        "filters": filters,
        "catalog_count": len(catalog),
        "candidates": candidates,
        "needs_clarification": not candidates or candidates[0]["confidence"] == "low",
        "clarification": (
            "请补充目标变量、研究区、时间范围或所需空间分辨率。 / Add target variable, AOI, dates, or desired resolution."
            if not candidates or candidates[0]["confidence"] == "low"
            else None
        ),
    }


def _recipe_for_task(task: str) -> dict[str, Any] | None:
    text = normalize(task)
    for recipe in TASK_RECIPES:
        if any(normalize(marker) in text for marker in recipe["markers"]):
            return recipe
    return None


def recommend_datasets(catalog: Sequence[dict[str, Any]], task: str, *, limit_per_role: int = 2) -> dict[str, Any]:
    recipe = _recipe_for_task(task)
    if recipe is None:
        result = search_catalog(catalog, task, limit=max(3, limit_per_role), mode="task")
        result.update({"task": task, "recipe": "general", "roles": {"primary": result.pop("candidates")}})
        return result

    roles: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    for role, role_query in recipe["roles"]:
        result = search_catalog(catalog, f"{task} {role_query}", limit=max(4, limit_per_role * 3), mode="task", role=role)
        selected: list[dict[str, Any]] = []
        for candidate in result["candidates"]:
            dataset_id = str(candidate.get("id") or "")
            if dataset_id in seen:
                continue
            selected.append(candidate)
            seen.add(dataset_id)
            if len(selected) >= limit_per_role:
                break
        roles[role] = selected
    missing = [role for role, values in roles.items() if not values]
    return {
        "task": task,
        "query_mode": "task",
        "recipe": recipe["id"],
        "catalog_count": len(catalog),
        "roles": roles,
        "needs_clarification": bool(missing),
        "missing_roles": missing,
        "selection_note": "Roles are a starting bundle, not a mandate to use every dataset. Verify each selected product before coding.",
    }


def compare_datasets(catalog: Sequence[dict[str, Any]], dataset_ids: Sequence[str]) -> dict[str, Any]:
    wanted = {normalize(dataset_id): dataset_id for dataset_id in dataset_ids}
    rows = []
    for item in catalog:
        key = normalize(item.get("id"))
        if key not in wanted:
            continue
        rows.append(candidate_record(item, 100, ["requested for comparison"]))
    found = {normalize(row["id"]) for row in rows}
    missing = [original for key, original in wanted.items() if key not in found]
    return {
        "requested": list(dataset_ids),
        "datasets": rows,
        "missing": missing,
        "comparison_fields": ["source", "kind", "provider", "category", "resolution_m", "start_date", "end_date", "license", "deprecated"],
    }


def verify_dataset(catalog: Sequence[dict[str, Any]], dataset_id: str, *, live: bool = False, project: str | None = None) -> dict[str, Any]:
    matches = [item for item in catalog if normalize(item.get("id")) == normalize(dataset_id)]
    result: dict[str, Any] = {
        "id": dataset_id,
        "catalog_found": bool(matches),
        "catalog_record": candidate_record(matches[0], 100, ["exact catalog record"]) if matches else None,
        "live_checked": False,
        "live_exists": None,
    }
    if live:
        try:
            import ee  # type: ignore

            ee.Initialize(project=project) if project else ee.Initialize()
            result["live_checked"] = True
            result["live_asset"] = ee.data.getAsset(dataset_id)
            result["live_exists"] = bool(result["live_asset"])
        except Exception as exc:  # pragma: no cover - depends on local credentials/network
            result["live_checked"] = True
            result["live_exists"] = False
            result["live_error"] = str(exc)
    result["status"] = "verified" if result["catalog_found"] and (not live or result["live_exists"]) else "catalog-only" if result["catalog_found"] else "not-found"
    return result


def catalog_stats(catalog: Sequence[dict[str, Any]], source_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    sources = Counter(source_name(item) for item in catalog)
    return {
        "total": len(catalog),
        "unique_ids": len({normalize(item.get("id")) for item in catalog}),
        "sources": dict(sorted(sources.items())),
        "deprecated": sum(is_deprecated(item) for item in catalog),
        "source_metadata": source_meta or {},
    }


def _filters_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "source": getattr(args, "source", None),
            "provider": getattr(args, "provider", None),
            "category": getattr(args, "category", None),
            "kind": getattr(args, "kind", None),
            "max_resolution_m": getattr(args, "max_resolution_m", None),
            "include_deprecated": getattr(args, "include_deprecated", False),
        }.items()
        if value not in (None, "", False)
    }


def _add_catalog_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--catalog-mode", choices=("auto", "official", "community", "all", "giswqs", "curated"), default="auto")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--fetch-seconds", type=int, default=12)


def _add_filter_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source")
    parser.add_argument("--provider")
    parser.add_argument("--category")
    parser.add_argument("--kind")
    parser.add_argument("--max-resolution-m", type=float)
    parser.add_argument("--include-deprecated", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search by id, name, theme, or task")
    search.add_argument("query", nargs="+")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--mode", choices=("auto", "exact", "theme", "task"), default="auto")
    _add_catalog_options(search)
    _add_filter_options(search)

    recommend = subparsers.add_parser("recommend", help="Recommend a role-based dataset bundle for a task")
    recommend.add_argument("task", nargs="+")
    recommend.add_argument("--limit-per-role", type=int, default=2)
    _add_catalog_options(recommend)

    compare = subparsers.add_parser("compare", help="Compare catalog metadata for dataset ids")
    compare.add_argument("ids", nargs="+")
    _add_catalog_options(compare)

    verify = subparsers.add_parser("verify", help="Verify an id in the catalog and optionally against the live EE API")
    verify.add_argument("id")
    verify.add_argument("--live", action="store_true")
    verify.add_argument("--project")
    _add_catalog_options(verify)

    stats = subparsers.add_parser("stats", help="Report catalog coverage by source")
    _add_catalog_options(stats)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    catalog, source_meta = load_catalog(catalog_mode=args.catalog_mode, refresh=args.refresh, fetch_seconds=args.fetch_seconds)
    if args.command == "search":
        payload = search_catalog(catalog, " ".join(args.query), limit=args.limit, mode=args.mode, filters=_filters_from_args(args))
    elif args.command == "recommend":
        payload = recommend_datasets(catalog, " ".join(args.task), limit_per_role=max(1, args.limit_per_role))
    elif args.command == "compare":
        payload = compare_datasets(catalog, args.ids)
    elif args.command == "verify":
        payload = verify_dataset(catalog, args.id, live=args.live, project=args.project)
    else:
        payload = catalog_stats(catalog, source_meta)
    payload["catalog_source"] = source_meta
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
