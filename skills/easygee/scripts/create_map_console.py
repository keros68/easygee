#!/usr/bin/env python
"""Create a fixed EasyGEE Map Console HTML page.

The console is a lightweight local browser interface for Earth Engine map
preview work. It uses ee only to create short-lived tile URLs and writes a
standalone HTML page with a stable EasyGEE shell: layer list, map, inspector,
and compact quota/project-state details. It does not read credential files or
print tile URLs.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import csv
import hashlib
import html
import json
import math
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import easygee_project


DEFAULT_PROJECT = easygee_project.DEFAULT_PROJECT
DEFAULT_EMPTY_CENTER = [20.0, 0.0]
DEFAULT_EMPTY_ZOOM = 2
UNLIMITED_QUOTA_THRESHOLD = 9_000_000_000_000_000_000
LEAFLET_CDN = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
LEAFLET_LOCAL = "leaflet-1.9.4.js"
PMTILES_VERSION = "4.5.0"
PMTILES_CDN = f"https://unpkg.com/pmtiles@{PMTILES_VERSION}/dist/pmtiles.js"
PMTILES_LOCAL = f"pmtiles-{PMTILES_VERSION}.js"
MAPLIBRE_VERSION = "5.6.1"
MAPLIBRE_JS_CDN = f"https://unpkg.com/maplibre-gl@{MAPLIBRE_VERSION}/dist/maplibre-gl.js"
MAPLIBRE_CSS_CDN = f"https://unpkg.com/maplibre-gl@{MAPLIBRE_VERSION}/dist/maplibre-gl.css"
MAPLIBRE_JS_LOCAL = f"maplibre-gl-{MAPLIBRE_VERSION}.js"
MAPLIBRE_CSS_LOCAL = f"maplibre-gl-{MAPLIBRE_VERSION}.css"
MAPLIBRE_LEAFLET_VERSION = "0.1.4"
MAPLIBRE_LEAFLET_CDN = (
    f"https://unpkg.com/@maplibre/maplibre-gl-leaflet@{MAPLIBRE_LEAFLET_VERSION}/dist/leaflet-maplibre-gl.js"
)
MAPLIBRE_LEAFLET_LOCAL = f"maplibre-gl-leaflet-{MAPLIBRE_LEAFLET_VERSION}.js"
COG_PROTOCOL_VERSION = "0.9.2"
COG_PROTOCOL_CDN = (
    f"https://unpkg.com/@geomatico/maplibre-cog-protocol@{COG_PROTOCOL_VERSION}/dist/index.js"
)
COG_PROTOCOL_LOCAL = f"maplibre-cog-protocol-{COG_PROTOCOL_VERSION}.js"
GEE_CATALOG_INDEX_URL = "https://raw.githubusercontent.com/giswqs/Earth-Engine-Catalog/master/gee_catalog.json"
GEE_STAC_ROOT_URL = "https://storage.googleapis.com/earthengine-stac/catalog/catalog.json"
GEE_COMMUNITY_DATASETS_CSV_URL = "https://raw.githubusercontent.com/sadassimov/geemu-skill/main/awesome-gee-community-datasets/community_datasets.csv"
GEE_CATALOG_URL_BASE = "https://developers.google.com/earth-engine/datasets/catalog/"
CATALOG_FETCH_TIMEOUT = 20
CATALOG_CACHE_VERSION = 3
CATALOG_CACHE_MAX_AGE_HOURS = 168
CATALOG_FETCH_SECONDS = 45
CATALOG_MAX_URLS = 5000
CATALOG_MAX_WORKERS = 32
S2_NDVI_DERIVED_IDS = {"EASYGEE/S2_NDVI", "easygee:s2-ndvi", "s2-ndvi", "ndvi"}
SKILL_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = SKILL_DIR / "assets"
EASYGEE_LOGO = ASSETS_DIR / "easygee-logo-square-simple-256.png"
NONCOMMERCIAL_TIER_LIMITS = {
    540_000: ("Community", "Community（非商业）", "Community (noncommercial)"),
    3_600_000: ("Contributor", "Contributor（非商业）", "Contributor (noncommercial)"),
    360_000_000: ("Partner", "Partner（非商业）", "Partner (noncommercial)"),
}
QUOTA_LABELS = {
    "Average concurrent batch tasks": ("平均批任务", "Average concurrent batch tasks"),
    "BigQuery slot-time per day in seconds (consumed on Earth Engine)": (
        "BigQuery 槽时",
        "BigQuery slot-time per day in seconds (consumed on Earth Engine)",
    ),
    "BigQuery raster function slot-time per day": (
        "BigQuery 槽时",
        "BigQuery raster function slot-time per day",
    ),
    "EECU-seconds per day": ("每日 EECU", "EECU-seconds per day"),
    "Earth Engine compute time (EECU-time) per day": (
        "每日 EECU",
        "Earth Engine compute time (EECU-time) per day",
    ),
    "Noncommercial EECU-seconds per month": (
        "非商业月度 EECU",
        "Noncommercial EECU-seconds per month",
    ),
    "ReadsPerMinutePerProject": ("项目读取/分钟", "ReadsPerMinutePerProject"),
    "ReadsPerMinutePerUser": ("用户读取/分钟", "ReadsPerMinutePerUser"),
    "Large aggregation result size": ("大型聚合结果", "Large aggregation result size"),
    "Max asset storage space": ("资产存储", "Max asset storage space"),
    "Max concurrent requests (high-volume endpoint)": (
        "高容量并发请求",
        "Max concurrent requests (high-volume endpoint)",
    ),
    "Max concurrent requests (standard endpoint)": (
        "标准并发请求",
        "Max concurrent requests (standard endpoint)",
    ),
    "Max number of assets": ("资产数量", "Max number of assets"),
    "Max rate of requests (per account)": (
        "账号请求速率",
        "Max rate of requests (per account)",
    ),
    "Max rate of requests (per project)": (
        "项目请求速率",
        "Max rate of requests (per project)",
    ),
    "Request payload size": ("请求大小", "Request payload size"),
    "Task queue length": ("任务队列", "Task queue length"),
}


def easygee_logo_data_uri() -> str:
    if not EASYGEE_LOGO.exists():
        return ""
    encoded = base64.b64encode(EASYGEE_LOGO.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@dataclass(frozen=True)
class ConsolePlan:
    output: str
    project: str
    project_source: str
    title: str
    center: tuple[float, float]
    layer_count: int
    uses_live_ee: bool
    quota_source: str
    quota_usage_source: str


def default_output() -> Path:
    if Path("D:/Scratch").exists() or Path("D:/").exists():
        return Path("D:/Scratch/easygee-interactive-map/index.html")
    return Path(tempfile.gettempdir()) / "easygee-interactive-map" / "index.html"


def parse_float(value: str | None) -> float | None:
    if not value:
        return None
    text = str(value).replace(",", "").strip()
    if not text or is_unlimited_quota_value(text) or ";" in text:
        return None
    number = ""
    for char in text:
        if char.isdigit() or char in ".-":
            number += char
        elif number:
            break
    try:
        return float(number) if number else None
    except ValueError:
        return None


def is_unlimited_quota_value(value: Any) -> bool:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return False
    lowered = text.lower()
    if "unlimited" in lowered or lowered in {"inf", "infinity", "∞"}:
        return True
    try:
        return int(text) >= UNLIMITED_QUOTA_THRESHOLD
    except ValueError:
        return False


def compact_value(value: str | None, unit: str | None = None) -> str:
    text = str(value or "").strip()
    suffix = str(unit or "").strip()
    if not text:
        return "N/A"
    if is_unlimited_quota_value(text):
        return "Unlimited"
    if ";" in text:
        return text
    if suffix and suffix != "-" and suffix.lower() not in text.lower():
        return f"{text} {suffix}"
    return text


def quota_label_pair(name: str) -> tuple[str, str]:
    return QUOTA_LABELS.get(name, (name, name))


def catalog_url_for_id(dataset_id: str) -> str:
    return GEE_CATALOG_URL_BASE + dataset_id.replace("/", "_")


def catalog_entry(
    dataset_id: str,
    label: str,
    tags: str = "",
    scale: str = "catalog",
    url: str | None = None,
    provider: str = "",
    kind: str = "",
    category: str = "",
    thumbnail: str = "",
    start_date: str = "",
    end_date: str = "",
    deprecated: bool = False,
    license_name: str = "",
    description: str = "",
    source_name: str = "official",
    sample_code: str = "",
) -> dict[str, Any]:
    return {
        "id": dataset_id,
        "label": label or dataset_id,
        "tags": tags,
        "scale": scale or "catalog",
        "url": url or catalog_url_for_id(dataset_id),
        "provider": provider,
        "type": kind,
        "category": category,
        "thumbnail": thumbnail,
        "startDate": start_date,
        "endDate": end_date,
        "deprecated": deprecated,
        "license": license_name,
        "description": description,
        "source": source_name,
        "sampleCode": sample_code,
    }


def catalog_cache_dir() -> Path:
    explicit = os.environ.get("EASYGEE_CACHE_DIR")
    if explicit:
        return Path(explicit)
    if Path("D:/Dev").exists():
        return Path("D:/Dev/cache/easygee")
    return Path(tempfile.gettempdir()) / "easygee-cache"


def official_stac_cache_path() -> Path:
    return catalog_cache_dir() / "official-stac-catalog.json"


def community_catalog_cache_path() -> Path:
    return catalog_cache_dir() / "community-catalog.json"


def cached_official_catalog(max_age_hours: int) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    path = official_stac_cache_path()
    if not path.exists():
        return None
    try:
        age_seconds = time.time() - path.stat().st_mtime
        if max_age_hours > 0 and age_seconds > max_age_hours * 3600:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != CATALOG_CACHE_VERSION:
            return None
        entries = payload.get("catalog")
        if not isinstance(entries, list) or not entries:
            return None
        source = {
            "source": "Google Earth Engine STAC cache",
            "url": GEE_STAC_ROOT_URL,
            "officialRoot": GEE_STAC_ROOT_URL,
            "cachePath": str(path),
            "fetchedAt": payload.get("fetchedAt") or "",
            "cached": True,
        }
        return entries, source
    except Exception:
        return None


def write_official_catalog_cache(entries: list[dict[str, Any]], source: dict[str, Any]) -> None:
    if not entries:
        return
    path = official_stac_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CATALOG_CACHE_VERSION,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "catalog": entries,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def cached_community_catalog(max_age_hours: int) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    path = community_catalog_cache_path()
    if not path.exists():
        return None
    try:
        age_seconds = time.time() - path.stat().st_mtime
        if max_age_hours > 0 and age_seconds > max_age_hours * 3600:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != CATALOG_CACHE_VERSION:
            return None
        entries = payload.get("catalog")
        if not isinstance(entries, list) or not entries:
            return None
        source = {
            "source": "GEE Community Catalog cache",
            "url": GEE_COMMUNITY_DATASETS_CSV_URL,
            "cachePath": str(path),
            "fetchedAt": payload.get("fetchedAt") or "",
            "cached": True,
            "count": len(entries),
        }
        return entries, source
    except Exception:
        return None


def write_community_catalog_cache(entries: list[dict[str, Any]], source: dict[str, Any]) -> None:
    if not entries:
        return
    path = community_catalog_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CATALOG_CACHE_VERSION,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "catalog": entries,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def fetch_json_url(url: str) -> tuple[str, dict[str, Any]]:
    with urllib.request.urlopen(url, timeout=CATALOG_FETCH_TIMEOUT) as response:
        payload = json.load(response)
    return url, payload


def stac_provider_text(collection: dict[str, Any]) -> str:
    providers = collection.get("providers") or []
    if not isinstance(providers, list):
        return ""
    names = []
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        name = str(provider.get("name") or "").strip()
        if name and name != "Google Earth Engine":
            names.append(name)
    return " / ".join(names[:3])


def stac_link(collection: dict[str, Any], rel: str) -> str:
    links = collection.get("links") or []
    if not isinstance(links, list):
        return ""
    for link in links:
        if isinstance(link, dict) and link.get("rel") == rel and link.get("href"):
            return str(link["href"])
    return ""


def stac_date_range(collection: dict[str, Any]) -> tuple[str, str]:
    interval = (((collection.get("extent") or {}).get("temporal") or {}).get("interval") or [])
    if not interval or not isinstance(interval, list) or not isinstance(interval[0], list):
        return "", ""

    def compact_date(value: Any) -> str:
        text = str(value or "")
        return text[:10] if len(text) >= 10 else text

    return compact_date(interval[0][0] if interval[0] else ""), compact_date(interval[0][1] if len(interval[0]) > 1 else "")


def stac_collection_entry(collection: dict[str, Any]) -> dict[str, Any] | None:
    dataset_id = str(collection.get("id") or "").strip()
    if not dataset_id:
        return None
    keywords = collection.get("keywords") or []
    if not isinstance(keywords, list):
        keywords = [str(keywords)]
    categories = collection.get("gee:categories") or []
    if not isinstance(categories, list):
        categories = [str(categories)]
    start_date, end_date = stac_date_range(collection)
    description = str(collection.get("description") or "").replace("\n", " ")[:700]
    tags = " ".join(
        str(value)
        for value in [
            " ".join(str(keyword) for keyword in keywords),
            " ".join(str(category) for category in categories),
            start_date,
            end_date,
        ]
        if value
    )
    license_name = str(collection.get("license") or "")
    return catalog_entry(
        dataset_id,
        str(collection.get("title") or dataset_id),
        tags,
        str(collection.get("gee:type") or "official catalog").replace("_", " "),
        catalog_url_for_id(dataset_id),
        provider=stac_provider_text(collection),
        kind=str(collection.get("gee:type") or ""),
        category=", ".join(str(category) for category in categories if category),
        thumbnail=stac_link(collection, "preview"),
        start_date=start_date,
        end_date=end_date,
        deprecated=bool(collection.get("deprecated") or False),
        license_name=license_name,
        description=description,
    )


def official_stac_catalog_entries(
    *,
    refresh: bool = False,
    max_age_hours: int = CATALOG_CACHE_MAX_AGE_HOURS,
    max_seconds: int = CATALOG_FETCH_SECONDS,
    max_urls: int = CATALOG_MAX_URLS,
    max_workers: int = CATALOG_MAX_WORKERS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cached = None if refresh else cached_official_catalog(max_age_hours)
    if cached:
        return cached

    deadline = time.time() + max(1, max_seconds)
    seen: set[str] = set()
    frontier = [GEE_STAC_ROOT_URL]
    entries: dict[str, dict[str, Any]] = {}
    catalog_count = 0
    errors: list[str] = []

    while frontier and time.time() < deadline and len(seen) < max_urls:
        batch = []
        for url in frontier:
            if url not in seen:
                seen.add(url)
                batch.append(url)
        frontier = []
        if not batch:
            break
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
            futures = {executor.submit(fetch_json_url, url): url for url in batch}
            for future in concurrent.futures.as_completed(futures):
                url = futures[future]
                try:
                    _, payload = future.result()
                except Exception as exc:
                    errors.append(f"{url}: {exc}")
                    continue
                if payload.get("type") == "Collection":
                    entry = stac_collection_entry(payload)
                    if entry:
                        entries[entry["id"]] = entry
                    continue
                catalog_count += 1
                for link in payload.get("links") or []:
                    if isinstance(link, dict) and link.get("rel") == "child" and link.get("href"):
                        frontier.append(str(link["href"]))

    warnings: list[str] = []
    if frontier:
        warnings.append(
            f"Official STAC catalog refresh stopped after {max_seconds}s; using {len(entries)} collections found so far."
        )
    if errors:
        warnings.append(f"Official STAC catalog skipped {len(errors)} URLs; first error: {errors[0]}")
    catalog = sorted(entries.values(), key=lambda item: (str(item.get("label") or item["id"]).casefold(), item["id"]))
    source = {
        "source": "Google Earth Engine STAC",
        "url": GEE_STAC_ROOT_URL,
        "officialRoot": GEE_STAC_ROOT_URL,
        "count": len(catalog),
        "visited": len(seen),
        "catalogs": catalog_count,
        "cached": False,
        "warnings": warnings,
    }
    if catalog:
        write_official_catalog_cache(catalog, source)
    return catalog, source


def curated_catalog_entries() -> list[dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    seeds = [
        catalog_entry(
            "EASYGEE/S2_NDVI",
            "Sentinel-2 NDVI (Cloud Score+)",
            "ndvi vegetation sentinel cloud score plus easygee derived 植被 归一化差异植被指数",
            "10 m",
            catalog_url_for_id("COPERNICUS/S2_SR_HARMONIZED"),
            provider="EasyGEE",
            kind="derived",
            source_name="derived",
        ),
        catalog_entry("COPERNICUS/S2_SR_HARMONIZED", "Sentinel-2 SR", "optical rgb ndvi vegetation 哨兵 光学 植被", "10 m"),
        catalog_entry("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED", "Cloud Score+", "sentinel cloud mask qa 云 掩膜", "10 m"),
        catalog_entry("COPERNICUS/S2_CLOUD_PROBABILITY", "Sentinel-2 Cloud Probability", "sentinel cloud probability s2cloudless 云概率", "10 m"),
        catalog_entry("COPERNICUS/S1_GRD", "Sentinel-1 GRD", "sar radar flood water all weather 洪水 雷达", "10 m"),
        catalog_entry("GOOGLE/DYNAMICWORLD/V1", "Dynamic World", "land cover classes probability 土地覆盖 分类", "10 m"),
        catalog_entry("JRC/GSW1_4/GlobalSurfaceWater", "JRC Global Surface Water", "water occurrence seasonality surface water 水体 地表水", "30 m"),
        catalog_entry("USGS/SRTMGL1_003", "SRTM elevation", "terrain dem elevation 高程 地形", "30 m"),
        catalog_entry("ESA/WorldCover/v200", "ESA WorldCover 2021", "land cover worldcover 土地覆盖", "10 m"),
        catalog_entry("MODIS/061/MOD13Q1", "MODIS Vegetation Indices", "modis ndvi evi vegetation time series 植被", "250 m"),
        catalog_entry("MODIS/061/MOD11A2", "MODIS Land Surface Temperature", "modis lst temperature heat 温度 地表温度", "1 km"),
        catalog_entry("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG", "VIIRS Nighttime Lights", "nighttime lights viirs radiance 夜光", "500 m"),
        catalog_entry("WorldPop/GP/100m/pop", "WorldPop Population", "population exposure people 人口", "100 m"),
        catalog_entry("JRC/GHSL/P2023A/GHS_POP", "GHSL Population", "population ghsl built exposure 人口", "100 m"),
        catalog_entry("GOOGLE/Research/open-buildings/v3/polygons", "Open Buildings V3", "buildings footprints exposure 建筑 建筑物", "vector"),
        catalog_entry("COPERNICUS/DEM/GLO30", "Copernicus DEM GLO-30", "dem terrain elevation 高程 地形", "30 m"),
        catalog_entry("ECMWF/ERA5_LAND/DAILY_AGGR", "ERA5-Land Daily Aggregates", "climate temperature precipitation wind 气候 降水 温度", "0.1 deg"),
        catalog_entry("UCSB-CHG/CHIRPS/DAILY", "CHIRPS Daily Precipitation", "rain precipitation drought rainfall 降水 雨量 干旱", "0.05 deg"),
    ]
    for entry in seeds:
        entries[entry["id"]] = entry
    try:
        from search_gee_dataset import DATASETS

        for dataset in DATASETS:
            keywords = " ".join([*dataset.tasks, *dataset.keywords, *dataset.bands])
            dataset_ids = [value.strip() for value in dataset.id.split(" and ") if value.strip()]
            for dataset_id in dataset_ids:
                entries.setdefault(
                    dataset_id,
                    catalog_entry(dataset_id, dataset.title, keywords, dataset.scale, catalog_url_for_id(dataset_id), kind=dataset.kind),
                )
    except Exception:
        pass
    for entry in entries.values():
        entry["source"] = "curated"
    return list(entries.values())


def remote_catalog_entries() -> list[dict[str, Any]]:
    with urllib.request.urlopen(GEE_CATALOG_INDEX_URL, timeout=CATALOG_FETCH_TIMEOUT) as response:
        payload = json.load(response)
    entries: list[dict[str, Any]] = []
    if not isinstance(payload, list):
        return entries
    for item in payload:
        if not isinstance(item, dict):
            continue
        dataset_id = str(item.get("id") or "").strip()
        if not dataset_id:
            continue
        keywords = item.get("keywords") or ""
        if isinstance(keywords, list):
            keywords = " ".join(str(value) for value in keywords)
        tags = " ".join(
            str(value)
            for value in [
                keywords,
                item.get("category"),
                item.get("provider"),
                item.get("type"),
                item.get("start_date") or item.get("state_date"),
                item.get("end_date"),
            ]
            if value
        )
        scale = str(item.get("type") or item.get("category") or "catalog").replace("_", " ")
        entries.append(
            catalog_entry(
                dataset_id,
                str(item.get("title") or dataset_id),
                tags,
                scale,
                str(item.get("url") or "") or catalog_url_for_id(dataset_id),
                provider=str(item.get("provider") or ""),
                kind=str(item.get("type") or ""),
                category=str(item.get("category") or ""),
                thumbnail=str(item.get("thumbnail") or ""),
                start_date=str(item.get("start_date") or item.get("state_date") or ""),
                end_date=str(item.get("end_date") or ""),
                deprecated=bool(item.get("deprecated") or False),
                license_name=str(item.get("license") or ""),
            )
        )
    return entries


def community_catalog_entries(
    *,
    refresh: bool = False,
    max_age_hours: int = CATALOG_CACHE_MAX_AGE_HOURS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cached = None if refresh else cached_community_catalog(max_age_hours)
    if cached:
        return cached

    with urllib.request.urlopen(GEE_COMMUNITY_DATASETS_CSV_URL, timeout=CATALOG_FETCH_TIMEOUT) as response:
        text = response.read().decode("utf-8-sig")

    entries: dict[str, dict[str, Any]] = {}
    for row in csv.DictReader(text.splitlines()):
        dataset_id = str(row.get("id") or "").strip()
        if not dataset_id:
            continue
        title = str(row.get("title") or dataset_id).strip()
        thematic_group = str(row.get("thematic_group") or "").strip()
        provider = str(row.get("provider") or "").strip()
        kind = str(row.get("type") or "").strip().lower()
        tags = " ".join(
            value
            for value in [
                "community catalog",
                thematic_group,
                str(row.get("tags") or "").strip(),
                provider,
                kind,
            ]
            if value
        )
        entry = catalog_entry(
            dataset_id,
            title,
            tags,
            kind.replace("_", " ") or "community catalog",
            str(row.get("docs_page") or "") or catalog_url_for_id(dataset_id),
            provider=provider,
            kind=kind,
            category=thematic_group,
            thumbnail=str(row.get("thumbnail") or "").strip(),
            license_name=str(row.get("license") or "").strip(),
            description=str(row.get("license_text") or "").strip(),
            source_name="community",
            sample_code=str(row.get("sample_code") or "").strip(),
        )
        entries[dataset_id] = entry

    catalog = sorted(entries.values(), key=lambda item: (str(item.get("label") or item["id"]).casefold(), item["id"]))
    source = {
        "source": "GEE Community Catalog",
        "url": GEE_COMMUNITY_DATASETS_CSV_URL,
        "count": len(catalog),
        "cached": False,
    }
    write_community_catalog_cache(catalog, source)
    return catalog, source


def build_catalog(
    layers: list[dict[str, Any]],
    include_remote: bool,
    catalog_mode: str = "auto",
    refresh_catalog: bool = False,
    catalog_cache_hours: int = CATALOG_CACHE_MAX_AGE_HOURS,
    catalog_fetch_seconds: int = CATALOG_FETCH_SECONDS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {entry["id"]: entry for entry in curated_catalog_entries()}
    source = "curated fallback"
    source_url = GEE_STAC_ROOT_URL
    source_extra: dict[str, Any] = {}
    warnings: list[str] = []
    source_counts: dict[str, int] = {"curated": len(entries)}
    mode = (catalog_mode or "auto").lower()
    if include_remote and mode != "curated":
        if mode in {"auto", "official", "all"}:
            try:
                official_entries, official_source = official_stac_catalog_entries(
                    refresh=refresh_catalog,
                    max_age_hours=catalog_cache_hours,
                    max_seconds=catalog_fetch_seconds,
                )
                if official_entries:
                    entries.update({entry["id"]: entry for entry in official_entries})
                    source_counts["official"] = len(official_entries)
                    source = str(official_source.get("source") or "Google Earth Engine STAC")
                    source_url = str(official_source.get("url") or GEE_STAC_ROOT_URL)
                    source_extra = {
                        key: value
                        for key, value in official_source.items()
                        if key not in {"source", "url", "officialRoot", "warnings"}
                    }
                warnings.extend(str(warning) for warning in official_source.get("warnings") or [])
            except Exception as exc:
                warnings.append(f"Official STAC catalog fetch failed: {exc}")
        if mode in {"auto", "all", "community"}:
            try:
                community_entries, community_source = community_catalog_entries(
                    refresh=refresh_catalog,
                    max_age_hours=catalog_cache_hours,
                )
                if community_entries:
                    for entry in community_entries:
                        if entry["id"] in entries:
                            entries[entry["id"]].setdefault("source", "official")
                            entries[entry["id"]]["communityUrl"] = entry.get("url") or ""
                            entries[entry["id"]]["sampleCode"] = entry.get("sampleCode") or entries[entry["id"]].get("sampleCode", "")
                        else:
                            entries[entry["id"]] = entry
                    source_counts["community"] = len(community_entries)
                    if source == "curated fallback":
                        source = str(community_source.get("source") or "GEE Community Catalog")
                        source_url = str(community_source.get("url") or GEE_COMMUNITY_DATASETS_CSV_URL)
                    else:
                        source = f"{source} + GEE Community Catalog"
                if community_source.get("cached"):
                    source_extra["communityCachePath"] = community_source.get("cachePath")
            except Exception as exc:
                warnings.append(f"Community catalog fetch failed: {exc}")
        if mode in {"auto", "giswqs"} and source == "curated fallback":
            try:
                remote_entries = remote_catalog_entries()
                if remote_entries:
                    entries.update({entry["id"]: entry for entry in remote_entries})
                    source_counts["giswqs"] = len(remote_entries)
                    source = "Earth Engine Catalog index"
                    source_url = GEE_CATALOG_INDEX_URL
            except Exception as exc:
                warnings.append(f"Catalog index fetch failed: {exc}")
        elif mode == "giswqs":
            warnings.append("Catalog mode giswqs was requested but did not return entries.")
    elif include_remote:
        source = "curated fallback"
    if include_remote and mode not in {"auto", "official", "giswqs", "curated", "community", "all"}:
        try:
            remote_entries = remote_catalog_entries()
            if remote_entries:
                entries.update({entry["id"]: entry for entry in remote_entries})
                source_counts["giswqs"] = len(remote_entries)
                source = "Earth Engine Catalog index"
                source_url = GEE_CATALOG_INDEX_URL
        except Exception as exc:
            warnings.append(f"Catalog index fetch failed: {exc}")
    for layer in layers:
        dataset_id = str(layer.get("dataset") or "")
        if not dataset_id:
            continue
        ready_entry = catalog_entry(
            dataset_id,
            str(layer.get("name") or dataset_id),
            f"map-ready layer {layer.get('type') or ''}",
            "ready layer",
        )
        entries.setdefault(dataset_id, ready_entry)
        entries[dataset_id]["ready"] = True
    ready_ids = {str(layer.get("dataset") or "") for layer in layers}
    catalog = sorted(
        entries.values(),
        key=lambda item: (
            0 if item["id"] in ready_ids else 1,
            str(item.get("label") or item["id"]).casefold(),
            item["id"],
        ),
    )
    return catalog, {
        "source": source,
        "url": source_url,
        "officialRoot": GEE_STAC_ROOT_URL,
        "count": len(catalog),
        "warnings": warnings,
        "counts": source_counts,
        **source_extra,
    }


def layer_id_for_dataset(dataset_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", dataset_id.lower()).strip("-")
    slug = slug[:34] or "catalog-layer"
    digest = hashlib.sha1(dataset_id.encode("utf-8")).hexdigest()[:8]
    return f"gee-{slug}-{digest}"


def normalize_bounds(bounds: Any) -> tuple[float, float, float, float]:
    """Return west, south, east, north from Leaflet-style bounds."""
    try:
        south = float(bounds[0][0])
        west = float(bounds[0][1])
        north = float(bounds[1][0])
        east = float(bounds[1][1])
    except Exception as exc:
        raise ValueError("bounds must be [[south, west], [north, east]]") from exc
    if south >= north or west >= east:
        raise ValueError("bounds must have south < north and west < east")
    if not (-90 <= south <= 90 and -90 <= north <= 90 and -180 <= west <= 180 and -180 <= east <= 180):
        raise ValueError("bounds are outside valid longitude/latitude ranges")
    return west, south, east, north


def normalize_latlng_pair(pair: Any) -> tuple[float, float]:
    try:
        lat = float(pair[0])
        lon = float(pair[1])
    except Exception as exc:
        raise ValueError("AOI coordinates must be [lat, lon] pairs") from exc
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("AOI coordinates are outside valid longitude/latitude ranges")
    return lat, lon


def normalize_lonlat_pair(pair: Any) -> tuple[float, float]:
    try:
        lon = float(pair[0])
        lat = float(pair[1])
    except Exception as exc:
        raise ValueError("GeoJSON AOI coordinates must be [lon, lat] pairs") from exc
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("AOI coordinates are outside valid longitude/latitude ranges")
    return lat, lon


def aoi_bounds_from_coordinates(coordinates: list[list[float]]) -> tuple[float, float, float, float]:
    if len(coordinates) < 3:
        raise ValueError("polygon AOI must contain at least three vertices")
    lats = [point[0] for point in coordinates]
    lons = [point[1] for point in coordinates]
    south, north = min(lats), max(lats)
    west, east = min(lons), max(lons)
    if south >= north or west >= east:
        raise ValueError("AOI bounds must have south < north and west < east")
    return west, south, east, north


def normalize_polygon_coordinates(aoi: dict[str, Any]) -> list[list[float]]:
    raw = aoi.get("coordinates") or aoi.get("latLngs") or aoi.get("points")
    if raw is None and isinstance(aoi.get("geometry"), dict):
        return normalize_polygon_coordinates(aoi["geometry"])
    if not isinstance(raw, list) or not raw:
        raise ValueError("polygon AOI must include coordinates")
    coordinate_order = str(aoi.get("coordinateOrder") or "").lower()
    if raw and isinstance(raw[0], list) and raw[0] and isinstance(raw[0][0], list):
        ring = raw[0]
        points = [normalize_lonlat_pair(point) for point in ring]
    elif coordinate_order == "lonlat":
        points = [normalize_lonlat_pair(point) for point in raw]
    else:
        points = [normalize_latlng_pair(point) for point in raw]

    deduped: list[list[float]] = []
    for lat, lon in points:
        if deduped and abs(deduped[-1][0] - lat) < 1e-12 and abs(deduped[-1][1] - lon) < 1e-12:
            continue
        deduped.append([lat, lon])
    if len(deduped) > 3 and abs(deduped[0][0] - deduped[-1][0]) < 1e-12 and abs(deduped[0][1] - deduped[-1][1]) < 1e-12:
        deduped.pop()
    if len(deduped) < 3:
        raise ValueError("polygon AOI must contain at least three distinct vertices")
    aoi_bounds_from_coordinates(deduped)
    return deduped


def normalize_aoi(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a stable AOI dict from a new AOI payload or legacy bounds."""
    raw_aoi = payload.get("aoi") if isinstance(payload.get("aoi"), dict) else None
    if not raw_aoi:
        west, south, east, north = normalize_bounds(payload.get("bounds"))
        return {
            "type": "rectangle",
            "bounds": [[south, west], [north, east]],
            "coordinates": [[south, west], [south, east], [north, east], [north, west]],
            "coordinateOrder": "latlng",
        }

    if str(raw_aoi.get("type") or "").lower() == "feature" and isinstance(raw_aoi.get("geometry"), dict):
        raw_aoi = raw_aoi["geometry"]
    aoi_type = str(raw_aoi.get("type") or "").lower()
    if aoi_type in {"polygon", "multipolygon"}:
        coordinates = normalize_polygon_coordinates(raw_aoi)
        west, south, east, north = aoi_bounds_from_coordinates(coordinates)
        return {
            "type": "polygon",
            "bounds": [[south, west], [north, east]],
            "coordinates": coordinates,
            "coordinateOrder": "latlng",
        }

    bounds = raw_aoi.get("bounds") or raw_aoi.get("bbox") or payload.get("bounds")
    west, south, east, north = normalize_bounds(bounds)
    return {
        "type": "rectangle",
        "bounds": [[south, west], [north, east]],
        "coordinates": [[south, west], [south, east], [north, east], [north, west]],
        "coordinateOrder": "latlng",
    }


def ee_geometry_from_aoi(ee: Any, aoi: dict[str, Any]) -> Any:
    if aoi.get("type") == "polygon":
        ring = [[lon, lat] for lat, lon in aoi["coordinates"]]
        return ee.Geometry.Polygon([ring], None, False)
    west, south, east, north = normalize_bounds(aoi["bounds"])
    return ee.Geometry.Rectangle([west, south, east, north], None, False)


def sentinel2_ndvi_image(
    ee: Any,
    roi: Any,
    start_date: str,
    end_date: str,
    cloud_pct: float,
    warnings: list[str],
    cloud_score_min: float = 0.60,
) -> tuple[Any, Any, str]:
    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(roi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_pct))
    )
    method = "sentinel-2-ndvi"
    try:
        collection = collection.linkCollection(
            ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"),
            ["cs_cdf"],
        ).map(lambda image: image.updateMask(image.select("cs_cdf").gte(cloud_score_min)))
        method = "sentinel-2-ndvi-cloud-score"
    except Exception:
        warnings.append("Cloud Score+ masking was unavailable; using CLOUDY_PIXEL_PERCENTAGE only.")
    image = collection.median().normalizedDifference(["B8", "B4"]).rename("NDVI").clip(roi)
    return image, collection, method


def sanitize_drive_folder(value: Any, default: str = "EasyGEE") -> str:
    text = str(value or "").strip() or default
    text = re.sub(r"[\\/]+", "_", text)
    return text[:120].strip() or default


def sanitize_export_token(value: Any, default: str, max_len: int = 90) -> str:
    text = str(value or "").strip() or default
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    return (text[:max_len].strip("_") or default)


def truthy_export_flag(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"0", "false", "no", "off"}:
        return False
    if text in {"1", "true", "yes", "on"}:
        return True
    return default


def build_ndvi_drive_export(payload: dict[str, Any]) -> dict[str, Any]:
    import ee

    resolved_project = easygee_project.resolve_project(payload.get("project"), remember_discovered=True)
    project = resolved_project.project
    if not project or project == DEFAULT_PROJECT:
        raise ValueError("A concrete Earth Engine project id is required")
    aoi = normalize_aoi(payload)
    start_date = str(payload.get("startDate") or "2024-01-01")
    end_date = str(payload.get("endDate") or datetime.now(timezone.utc).date().isoformat())
    try:
        cloud_pct = float(payload.get("cloudPct") or 80)
    except Exception:
        cloud_pct = 80.0
    try:
        scale = float(payload.get("scale") or 10)
    except Exception:
        scale = 10.0
    if scale <= 0:
        raise ValueError("scale must be greater than 0")
    try:
        max_pixels = int(float(payload.get("maxPixels") or 1_000_000_000))
    except Exception:
        max_pixels = 1_000_000_000
    max_pixels = max(1, max_pixels)

    ee.Initialize(project=project)
    roi = ee_geometry_from_aoi(ee, aoi)
    warnings: list[str] = []
    ndvi, collection, method = sentinel2_ndvi_image(ee, roi, start_date, end_date, cloud_pct, warnings)
    aoi_digest = hashlib.sha1(json.dumps(aoi, sort_keys=True).encode("utf-8")).hexdigest()[:8]
    date_token = sanitize_export_token(f"{start_date}_{end_date}", "date_range", max_len=32)
    default_prefix = f"easygee_ndvi_{date_token}_{aoi_digest}"
    folder = sanitize_drive_folder(payload.get("folder"), "EasyGEE")
    file_name_prefix = sanitize_export_token(payload.get("fileNamePrefix"), default_prefix)
    description = sanitize_export_token(payload.get("description"), file_name_prefix, max_len=100)
    file_format = str(payload.get("fileFormat") or "GeoTIFF").strip() or "GeoTIFF"
    cloud_optimized = truthy_export_flag(payload.get("cloudOptimized"), True)
    start_task = truthy_export_flag(payload.get("start"), True)
    crs = str(payload.get("crs") or "").strip()

    export_kwargs: dict[str, Any] = {
        "image": ndvi.rename("NDVI").toFloat(),
        "description": description,
        "folder": folder,
        "fileNamePrefix": file_name_prefix,
        "region": roi,
        "scale": scale,
        "maxPixels": max_pixels,
        "fileFormat": file_format,
    }
    if crs:
        export_kwargs["crs"] = crs
    if file_format.lower() == "geotiff" and cloud_optimized:
        export_kwargs["formatOptions"] = {"cloudOptimized": True}

    task = ee.batch.Export.image.toDrive(**export_kwargs)
    if start_task:
        task.start()
    try:
        status = task.status()
    except Exception:
        status = {}
    try:
        scene_count = int(collection.size().getInfo())
    except Exception:
        scene_count = None
    task_id = str(status.get("id") or getattr(task, "id", "") or "")
    state = str(status.get("state") or ("STARTED" if start_task else "READY"))
    created_at = datetime.now(timezone.utc).isoformat()
    drive_search_url = "https://drive.google.com/drive/search?q=" + urllib.parse.quote(file_name_prefix)
    task_record = {
        "id": task_id or f"drive-{description}-{aoi_digest}",
        "type": "drive-export",
        "analysis": "ndvi",
        "title": "NDVI export to Google Drive",
        "status": state,
        "destination": "Google Drive",
        "folder": folder,
        "fileNamePrefix": file_name_prefix,
        "taskId": task_id,
        "taskName": description,
        "driveSearchUrl": drive_search_url,
        "createdAt": created_at,
        "updatedAt": created_at,
        "params": {
            "dataset": "COPERNICUS/S2_SR_HARMONIZED",
            "index": "NDVI",
            "method": method,
            "startDate": start_date,
            "endDate": end_date,
            "cloudPct": cloud_pct,
            "scale": scale,
            "fileFormat": file_format,
            "cloudOptimized": cloud_optimized if file_format.lower() == "geotiff" else False,
            "maxPixels": max_pixels,
            "sceneCount": scene_count,
            "aoi": aoi,
        },
        "notes": [
            "Drive file URLs are only available after the Earth Engine task finishes; search Drive by fileNamePrefix.",
        ],
        "warnings": warnings,
    }
    return {"ok": True, "task": task_record, "export": task_record, "warnings": warnings}


def safe_band_names(image: Any, limit: int = 16) -> list[str]:
    try:
        bands = image.bandNames().getInfo()
        if isinstance(bands, list):
            return [str(band) for band in bands[:limit]]
    except Exception:
        pass
    return []


def collection_with_fallback(collection: Any, roi: Any, start_date: str, end_date: str, warnings: list[str]) -> Any:
    filtered = collection.filterBounds(roi)
    if start_date and end_date:
        dated = filtered.filterDate(start_date, end_date)
        try:
            if int(dated.limit(1).size().getInfo()) > 0:
                return dated
            warnings.append("No images matched the selected date range; using recent nearby images.")
        except Exception:
            return dated
    try:
        return filtered.sort("system:time_start", False).limit(24)
    except Exception:
        return filtered


def percentile_vis(image: Any, roi: Any, band: str) -> dict[str, Any]:
    try:
        import ee

        stats = (
            image.select(band)
            .reduceRegion(
                reducer=ee.Reducer.percentile([2, 98]),
                geometry=roi,
                scale=1000,
                bestEffort=True,
                maxPixels=100000,
                tileScale=2,
            )
            .getInfo()
        )
        values = [float(value) for value in stats.values() if value is not None]
        if len(values) >= 2 and min(values) < max(values):
            return {"min": min(values), "max": max(values), "palette": ["#132b43", "#2c7fb8", "#7fcdbb", "#ffffcc"]}
    except Exception:
        pass
    return {"min": 0, "max": 1, "palette": ["#132b43", "#2c7fb8", "#7fcdbb", "#ffffcc"]}


def generic_vis_for_image(image: Any, roi: Any, dataset_id: str) -> tuple[dict[str, Any], list[list[str]], str]:
    bands = safe_band_names(image)
    band_set = set(bands)
    rgb_candidates = [
        (["B4", "B3", "B2"], {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000, "gamma": 1.15}),
        (["SR_B4", "SR_B3", "SR_B2"], {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 5000, "max": 18000, "gamma": 1.2}),
        (["red", "green", "blue"], {"bands": ["red", "green", "blue"], "min": 0, "max": 1}),
        (["Red", "Green", "Blue"], {"bands": ["Red", "Green", "Blue"], "min": 0, "max": 1}),
    ]
    for required, vis in rgb_candidates:
        if set(required).issubset(band_set):
            return vis, [["#6f9fcf", "Auto RGB composite"]], "auto-rgb"
    if not bands:
        return {"min": 0, "max": 1}, [["#7fcdbb", "Default visualization"]], "default"
    band = bands[0]
    lowered = f"{dataset_id} {band}".lower()
    if "ndvi" in lowered or band.upper() in {"NDVI", "EVI"}:
        return (
            {"bands": [band], "min": 0, "max": 0.8, "palette": ["#2c105c", "#4856a5", "#31a354", "#addd8e", "#f7fcb9"]},
            [["#2c105c", "Low"], ["#31a354", "Medium"], ["#f7fcb9", "High"]],
            "auto-index",
        )
    if any(term in lowered for term in ["temperature", "lst", "thermal"]):
        return (
            {"bands": [band], "min": 0, "max": 45, "palette": ["#313695", "#74add1", "#ffffbf", "#f46d43", "#a50026"]},
            [["#313695", "Cool"], ["#ffffbf", "Moderate"], ["#a50026", "Hot"]],
            "auto-temperature",
        )
    vis = percentile_vis(image, roi, band)
    vis["bands"] = [band]
    return vis, [["#132b43", "Low"], ["#7fcdbb", "Mid"], ["#ffffcc", "High"]], "auto-percentile"


def sanitize_color(value: Any) -> str | None:
    text = str(value or "").strip()
    if len(text) in {4, 7} and text.startswith("#") and all(ch in "0123456789abcdefABCDEF" for ch in text[1:]):
        return text
    return None


def sanitize_vis_params(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return dict(fallback)
    vis = dict(fallback)
    for key in ("min", "max", "gamma"):
        if key in value:
            try:
                number = float(value[key])
            except Exception:
                continue
            if math.isfinite(number):
                vis[key] = number
    if isinstance(value.get("bands"), list):
        bands = [str(item) for item in value["bands"] if str(item).strip()]
        if bands:
            vis["bands"] = bands[:4]
    if isinstance(value.get("palette"), list):
        palette = [color for color in (sanitize_color(item) for item in value["palette"]) if color]
        if len(palette) >= 2:
            vis["palette"] = palette[:32]
    return vis


def sanitize_legend(value: Any, fallback: list[list[str]]) -> list[list[str]]:
    if not isinstance(value, list):
        return fallback
    rows: list[list[str]] = []
    for item in value[:32]:
        if not isinstance(item, list) or len(item) < 2:
            continue
        color = sanitize_color(item[0])
        label = str(item[1] or "").strip()
        if color and label:
            rows.append([color, label[:80]])
    return rows or fallback


def parse_recipe_float(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except Exception:
        return fallback
    return number if math.isfinite(number) else fallback


def parse_months(value: Any) -> list[int]:
    if value is None:
        return []
    raw_items: list[Any]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if "-" in text and "," not in text:
            start, end = text.split("-", 1)
            try:
                start_i = int(start)
                end_i = int(end)
            except Exception:
                return []
            raw_items = list(range(min(start_i, end_i), max(start_i, end_i) + 1))
        else:
            raw_items = re.split(r"[\s,;]+", text)
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]
    months: list[int] = []
    for item in raw_items:
        try:
            month = int(item)
        except Exception:
            continue
        if 1 <= month <= 12 and month not in months:
            months.append(month)
    return sorted(months)


def recipe_date_range(recipe: dict[str, Any], fallback_start: str, fallback_end: str) -> tuple[str, str, list[int]]:
    months = parse_months(recipe.get("months") or recipe.get("calendarMonths"))
    year: int | None = None
    try:
        if recipe.get("year") not in (None, ""):
            year = int(recipe["year"])
    except Exception:
        year = None
    if year and months:
        start_month = min(months)
        end_month = max(months)
        start_date = f"{year:04d}-{start_month:02d}-01"
        if end_month == 12:
            end_date = f"{year + 1:04d}-01-01"
        else:
            end_date = f"{year:04d}-{end_month + 1:02d}-01"
        return start_date, end_date, months
    start_date = str(recipe.get("startDate") or fallback_start)
    end_date = str(recipe.get("endDate") or fallback_end)
    return start_date, end_date, months


def default_recipe_scale(dataset_id: str, band: str, recipe: dict[str, Any]) -> tuple[float, float]:
    if recipe.get("scaleFactor") not in (None, "") or recipe.get("offset") not in (None, ""):
        return parse_recipe_float(recipe.get("scaleFactor"), 1.0), parse_recipe_float(recipe.get("offset"), 0.0)
    band_upper = band.upper()
    if dataset_id == "MODIS/061/MOD13Q1" and band_upper in {"NDVI", "EVI"}:
        return 0.0001, 0.0
    if dataset_id == "MODIS/061/MOD11A2" and band_upper.startswith("LST_"):
        return 0.02, -273.15
    return 1.0, 0.0


def normalize_layer_recipe(payload: dict[str, Any], dataset_id: str, start_date: str, end_date: str) -> dict[str, Any] | None:
    raw = payload.get("recipe") if isinstance(payload.get("recipe"), dict) else None
    if not raw:
        return None
    if str(raw.get("kind") or "").lower() == "preview":
        return None
    recipe = dict(raw)
    recipe_dataset = str(recipe.get("datasetId") or dataset_id).strip()
    if recipe_dataset and recipe_dataset != dataset_id:
        raise ValueError("recipe.datasetId must match datasetId")
    band = str(recipe.get("band") or recipe.get("index") or "").strip()
    if not band:
        raise ValueError("recipe.band is required for ImageCollection recipes")
    reducer = str(recipe.get("temporalReducer") or recipe.get("reducer") or "median").strip().lower()
    aliases = {"maximum": "max", "minimum": "min", "avg": "mean", "average": "mean"}
    reducer = aliases.get(reducer, reducer)
    if reducer not in {"median", "mean", "max", "min", "mode", "mosaic"}:
        raise ValueError("recipe.temporalReducer must be one of median, mean, max, min, mode, or mosaic")
    recipe_start, recipe_end, months = recipe_date_range(recipe, start_date, end_date)
    scale_factor, offset = default_recipe_scale(dataset_id, band, recipe)
    normalized: dict[str, Any] = {
        "kind": str(recipe.get("kind") or "imageCollection").strip() or "imageCollection",
        "source": str(recipe.get("source") or "agent-recipe"),
        "datasetId": dataset_id,
        "band": band,
        "outputBand": str(recipe.get("outputBand") or band).strip() or band,
        "temporalReducer": reducer,
        "startDate": recipe_start,
        "endDate": recipe_end,
        "scaleFactor": scale_factor,
        "offset": offset,
        "aoi": "currentAOI",
    }
    if recipe.get("year") not in (None, ""):
        try:
            normalized["year"] = int(recipe["year"])
        except Exception:
            pass
    if months:
        normalized["months"] = months
    if recipe.get("name"):
        normalized["name"] = str(recipe["name"])[:120]
    if recipe.get("description"):
        normalized["description"] = str(recipe["description"])[:500]
    if isinstance(recipe.get("visParams"), dict):
        normalized["visParams"] = recipe["visParams"]
    if isinstance(recipe.get("legend"), list):
        normalized["legend"] = recipe["legend"]
    return normalized


def recipe_default_vis(dataset_id: str, band: str) -> tuple[dict[str, Any], list[list[str]], str]:
    text = f"{dataset_id} {band}".lower()
    if "ndvi" in text or band.upper() in {"NDVI", "EVI"}:
        return (
            {"bands": [band], "min": 0, "max": 0.9, "palette": ["#2c105c", "#4856a5", "#31a354", "#addd8e", "#f7fcb9"]},
            [["#2c105c", "Low"], ["#31a354", "Medium"], ["#f7fcb9", "High"]],
            "ndvi",
        )
    if any(term in text for term in ["lst", "temperature", "thermal"]):
        return (
            {"bands": [band], "min": 0, "max": 45, "palette": ["#313695", "#74add1", "#ffffbf", "#f46d43", "#a50026"]},
            [["#313695", "Cool"], ["#ffffbf", "Moderate"], ["#a50026", "Hot"]],
            "temperature",
        )
    return (
        {"bands": [band], "min": 0, "max": 1, "palette": ["#132b43", "#2c7fb8", "#7fcdbb", "#ffffcc"]},
        [["#132b43", "Low"], ["#7fcdbb", "Mid"], ["#ffffcc", "High"]],
        "raster",
    )


def recipe_period_label(recipe: dict[str, Any]) -> str:
    if recipe.get("year") and recipe.get("months"):
        months = recipe["months"]
        if isinstance(months, list) and months:
            if len(months) > 1 and months == list(range(min(months), max(months) + 1)):
                return f"{recipe['year']} months {min(months)}-{max(months)}"
            return f"{recipe['year']} months {','.join(str(item) for item in months)}"
    return f"{recipe.get('startDate')}..{recipe.get('endDate')}"


def recipe_layer_name(catalog_item: dict[str, Any], recipe: dict[str, Any]) -> str:
    if recipe.get("name"):
        return str(recipe["name"])
    label = str(catalog_item.get("label") or recipe.get("datasetId") or "GEE layer")
    reducer = str(recipe.get("temporalReducer") or "").upper()
    band = str(recipe.get("outputBand") or recipe.get("band") or "")
    return f"{label} {band} {reducer}".strip()


def preview_recipe(dataset_id: str, catalog_item: dict[str, Any], start_date: str, end_date: str, method: str) -> dict[str, Any]:
    label = str(catalog_item.get("label") or dataset_id)
    return {
        "kind": "preview",
        "source": "map-console-default-preview",
        "datasetId": dataset_id,
        "label": label,
        "operation": method,
        "startDate": start_date,
        "endDate": end_date,
        "aoi": "currentAOI",
        "description": "Default quick-preview recipe. Use an explicit recipe for analytical requests.",
    }


def build_recipe_image(
    ee: Any,
    dataset_id: str,
    catalog_item: dict[str, Any],
    roi: Any,
    recipe: dict[str, Any],
    warnings: list[str],
) -> tuple[Any, dict[str, Any], str, str, list[list[str]], str, dict[str, Any]]:
    collection = (
        ee.ImageCollection(dataset_id)
        .filterBounds(roi)
        .filterDate(str(recipe["startDate"]), str(recipe["endDate"]))
    )
    months = recipe.get("months")
    if isinstance(months, list) and months:
        month_values = [int(month) for month in months]
        if month_values == list(range(min(month_values), max(month_values) + 1)):
            collection = collection.filter(ee.Filter.calendarRange(min(month_values), max(month_values), "month"))
        else:
            collection = collection.map(lambda image: image.set("easygee_month", ee.Date(image.get("system:time_start")).get("month")))
            collection = collection.filter(ee.Filter.inList("easygee_month", month_values))
    band = str(recipe["band"])
    output_band = str(recipe.get("outputBand") or band)
    scale_factor = float(recipe.get("scaleFactor") or 1)
    offset = float(recipe.get("offset") or 0)

    def transform(image: Any) -> Any:
        selected = image.select(band)
        if scale_factor != 1:
            selected = selected.multiply(scale_factor)
        if offset:
            selected = selected.add(offset)
        return selected.rename(output_band).copyProperties(image, ["system:time_start"])

    prepared = collection.map(transform)
    reducer = str(recipe["temporalReducer"])
    if reducer == "max":
        image = prepared.max()
    elif reducer == "min":
        image = prepared.min()
    elif reducer == "mean":
        image = prepared.mean()
    elif reducer == "mode":
        image = prepared.mode()
    elif reducer == "mosaic":
        image = prepared.mosaic()
    else:
        image = prepared.median()
    image = image.rename(output_band).clip(roi)
    vis, legend, profile = recipe_default_vis(dataset_id, output_band)
    method = f"recipe:{reducer}:{band}"
    recipe["periodLabel"] = recipe_period_label(recipe)
    recipe["styleProfile"] = profile
    recipe["label"] = recipe_layer_name(catalog_item, recipe)
    return image, vis, recipe["label"], "ee-derived", legend, method, recipe


def style_profile_for_layer(dataset_id: str, layer_type: str, method: str, name: str) -> str:
    text = f"{dataset_id} {layer_type} {method} {name}".lower()
    if "ndvi" in text or "vegetation" in text:
        return "ndvi"
    if "jrc" in text or "water" in text or "gsw" in text:
        return "water"
    if "lst" in text or "temperature" in text or "thermal" in text:
        return "temperature"
    if "dem" in text or "elevation" in text or "terrain" in text:
        return "terrain"
    if "viirs" in text or "night" in text:
        return "nightlights"
    if "population" in text or "worldpop" in text or "ghsl" in text:
        return "population"
    if "categorical" in layer_type:
        return "categorical"
    if "vector" in layer_type:
        return "vector"
    return "raster"


def known_catalog_image(
    ee: Any,
    dataset_id: str,
    roi: Any,
    start_date: str,
    end_date: str,
    cloud_pct: float,
    warnings: list[str],
) -> tuple[Any, dict[str, Any], str, str, list[list[str]], str] | None:
    if dataset_id in S2_NDVI_DERIVED_IDS:
        image, _, method = sentinel2_ndvi_image(ee, roi, start_date, end_date, cloud_pct, warnings)
        return image, {"min": 0, "max": 0.8, "palette": ["#2c105c", "#4856a5", "#31a354", "#addd8e", "#f7fcb9"]}, "Sentinel-2 NDVI", "ee-derived", [["#2c105c", "Low"], ["#31a354", "Medium"], ["#f7fcb9", "High"]], method
    if dataset_id == "COPERNICUS/S2_SR_HARMONIZED":
        image = (
            ee.ImageCollection(dataset_id)
            .filterBounds(roi)
            .filterDate(start_date, end_date)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_pct))
            .median()
            .clip(roi)
        )
        return image, {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000, "gamma": 1.15}, "Sentinel-2 RGB", "ee-raster", [["#6f9fcf", "Median RGB composite"]], "sentinel-2-rgb"
    if dataset_id == "COPERNICUS/S1_GRD":
        image = (
            ee.ImageCollection(dataset_id)
            .filterBounds(roi)
            .filterDate(start_date, end_date)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            .select("VV")
            .median()
            .clip(roi)
        )
        return image, {"min": -25, "max": 0, "palette": ["#0b132b", "#1c7293", "#f4f1de"]}, "Sentinel-1 VV", "ee-raster", [["#0b132b", "Low backscatter"], ["#f4f1de", "High backscatter"]], "sentinel-1-vv"
    if dataset_id == "GOOGLE/DYNAMICWORLD/V1":
        image = (
            ee.ImageCollection(dataset_id)
            .filterBounds(roi)
            .filterDate(start_date, end_date)
            .select("label")
            .mode()
            .clip(roi)
        )
        return (
            image,
            {
                "min": 0,
                "max": 8,
                "palette": ["#419bdf", "#397d49", "#88b053", "#7a87c6", "#e49635", "#dfc35a", "#c4281b", "#a59b8f", "#b39fe1"],
            },
            "Dynamic World mode",
            "ee-categorical",
            [["#419bdf", "Water"], ["#397d49", "Trees"], ["#c4281b", "Built"]],
            "dynamic-world-mode",
        )
    if dataset_id == "JRC/GSW1_4/GlobalSurfaceWater":
        image = ee.Image(dataset_id).select("occurrence").clip(roi)
        return image, {"min": 0, "max": 100, "palette": ["#f7fbff", "#6baed6", "#08306b"]}, "JRC water occurrence", "ee-raster", [["#f7fbff", "Rare"], ["#6baed6", "Seasonal"], ["#08306b", "Persistent"]], "jrc-water-occurrence"
    if dataset_id in {"USGS/SRTMGL1_003", "COPERNICUS/DEM/GLO30"}:
        band = "elevation" if dataset_id == "USGS/SRTMGL1_003" else "DEM"
        image = ee.Image(dataset_id).select(band).clip(roi)
        return image, {"min": 0, "max": 1000, "palette": ["#0f3b2e", "#3f7d3f", "#c9b96d", "#a2673f", "#f4f1e8"]}, "Elevation", "ee-raster", [["#0f3b2e", "Low"], ["#c9b96d", "Mid"], ["#f4f1e8", "High"]], "dem"
    if dataset_id == "ESA/WorldCover/v200":
        image = ee.ImageCollection(dataset_id).first().select("Map").clip(roi)
        return image, {"min": 10, "max": 100, "palette": ["#006400", "#ffbb22", "#ffff4c", "#f096ff", "#fa0000", "#b4b4b4", "#f0f0f0", "#0064c8", "#0096a0", "#00cf75", "#fae6a0"]}, "ESA WorldCover", "ee-categorical", [["#006400", "Trees"], ["#fa0000", "Built"], ["#0064c8", "Water"]], "worldcover"
    if dataset_id == "MODIS/061/MOD13Q1":
        coll = collection_with_fallback(ee.ImageCollection(dataset_id), roi, start_date, end_date, warnings)
        image = coll.select("NDVI").median().multiply(0.0001).clip(roi)
        return image, {"min": 0, "max": 0.9, "palette": ["#2c105c", "#4856a5", "#31a354", "#addd8e", "#f7fcb9"]}, "MODIS NDVI", "ee-derived", [["#2c105c", "Low"], ["#31a354", "Medium"], ["#f7fcb9", "High"]], "modis-ndvi"
    if dataset_id == "MODIS/061/MOD11A2":
        coll = collection_with_fallback(ee.ImageCollection(dataset_id), roi, start_date, end_date, warnings)
        image = coll.select("LST_Day_1km").median().multiply(0.02).subtract(273.15).clip(roi)
        return image, {"min": 0, "max": 45, "palette": ["#313695", "#74add1", "#ffffbf", "#f46d43", "#a50026"]}, "MODIS LST Day", "ee-derived", [["#313695", "Cool"], ["#ffffbf", "Moderate"], ["#a50026", "Hot"]], "modis-lst"
    if dataset_id == "NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG":
        coll = collection_with_fallback(ee.ImageCollection(dataset_id), roi, start_date, end_date, warnings)
        image = coll.select("avg_rad").median().clip(roi)
        return image, {"min": 0, "max": 60, "palette": ["#03071e", "#370617", "#f48c06", "#ffba08"]}, "VIIRS nighttime lights", "ee-raster", [["#03071e", "Low"], ["#f48c06", "Medium"], ["#ffba08", "High"]], "viirs-nightlights"
    if dataset_id == "WorldPop/GP/100m/pop":
        coll = collection_with_fallback(ee.ImageCollection(dataset_id), roi, start_date, end_date, warnings)
        image = coll.select("population").mosaic().clip(roi)
        return image, {"min": 0, "max": 100, "palette": ["#fff7ec", "#fdbb84", "#e34a33", "#7f0000"]}, "WorldPop population", "ee-raster", [["#fff7ec", "Sparse"], ["#e34a33", "Dense"]], "worldpop"
    return None


def build_catalog_layer(payload: dict[str, Any]) -> dict[str, Any]:
    import ee

    resolved_project = easygee_project.resolve_project(payload.get("project"), remember_discovered=True)
    project = resolved_project.project
    dataset_id = str(payload.get("datasetId") or payload.get("dataset") or "").strip()
    if not dataset_id:
        raise ValueError("datasetId is required")
    if not project or project == DEFAULT_PROJECT:
        raise ValueError("A concrete Earth Engine project id is required")
    aoi = normalize_aoi(payload)
    west, south, east, north = normalize_bounds(aoi["bounds"])
    start_date = str(payload.get("startDate") or "2024-01-01")
    end_date = str(payload.get("endDate") or datetime.now(timezone.utc).date().isoformat())
    try:
        cloud_pct = float(payload.get("cloudPct") or 80)
    except Exception:
        cloud_pct = 80.0
    catalog_item = payload.get("catalogItem") if isinstance(payload.get("catalogItem"), dict) else {}
    style_profile_hint = str(payload.get("styleProfile") or "").strip().lower()
    explicit_recipe = normalize_layer_recipe(payload, dataset_id, start_date, end_date)

    ee.Initialize(project=project)
    roi = ee_geometry_from_aoi(ee, aoi)
    warnings: list[str] = []

    def tile_url(image: Any, vis: dict[str, Any]) -> str:
        return image.getMapId(vis)["tile_fetcher"].url_format

    asset: dict[str, Any] = {}
    try:
        asset = ee.data.getAsset(dataset_id) or {}
    except Exception:
        asset = {}
    asset_type = str(asset.get("type") or catalog_item.get("type") or "").upper()
    known = None if explicit_recipe else known_catalog_image(ee, dataset_id, roi, start_date, end_date, cloud_pct, warnings)
    if not explicit_recipe and style_profile_hint == "ndvi" and dataset_id == "COPERNICUS/S2_SR_HARMONIZED":
        ndvi_image, _, ndvi_method = sentinel2_ndvi_image(ee, roi, start_date, end_date, cloud_pct, warnings)
        known = (
            ndvi_image,
            {"min": 0, "max": 0.8, "palette": ["#2c105c", "#4856a5", "#31a354", "#addd8e", "#f7fcb9"]},
            "Sentinel-2 NDVI",
            "ee-derived",
            [["#2c105c", "Low"], ["#31a354", "Medium"], ["#f7fcb9", "High"]],
            ndvi_method,
        )
    image: Any
    vis: dict[str, Any]
    name: str
    layer_type: str
    legend: list[list[str]]
    method: str
    layer_recipe: dict[str, Any]
    if explicit_recipe:
        image, vis, name, layer_type, legend, method, layer_recipe = build_recipe_image(
            ee,
            dataset_id,
            catalog_item,
            roi,
            explicit_recipe,
            warnings,
        )
    elif known:
        image, vis, name, layer_type, legend, method = known
        layer_recipe = preview_recipe(dataset_id, catalog_item, start_date, end_date, method)
    else:
        attempts: list[str] = []
        if "TABLE" in asset_type or str(catalog_item.get("type") or "").lower() == "table":
            try:
                fc = ee.FeatureCollection(dataset_id).filterBounds(roi)
                image = fc.style(color="#16734d", fillColor="#16734d33", width=2).clip(roi)
                vis = {}
                name = str(catalog_item.get("label") or dataset_id)
                layer_type = "ee-vector"
                legend = [["#16734d", "Styled features"]]
                method = "featurecollection-style"
                layer_recipe = preview_recipe(dataset_id, catalog_item, start_date, end_date, method)
            except Exception as exc:
                attempts.append(f"FeatureCollection failed: {exc}")
                raise ValueError("; ".join(attempts) or "Could not render FeatureCollection") from exc
        else:
            try:
                if "IMAGE_COLLECTION" in asset_type or str(catalog_item.get("type") or "").lower() == "image_collection":
                    coll = collection_with_fallback(ee.ImageCollection(dataset_id), roi, start_date, end_date, warnings)
                    image = coll.median().clip(roi)
                    method = "imagecollection-median"
                elif "IMAGE" in asset_type or str(catalog_item.get("type") or "").lower() == "image":
                    image = ee.Image(dataset_id).clip(roi)
                    method = "image"
                else:
                    try:
                        coll = collection_with_fallback(ee.ImageCollection(dataset_id), roi, start_date, end_date, warnings)
                        image = coll.median().clip(roi)
                        method = "imagecollection-median"
                    except Exception as exc:
                        attempts.append(f"ImageCollection failed: {exc}")
                        image = ee.Image(dataset_id).clip(roi)
                        method = "image"
                vis, legend, vis_method = generic_vis_for_image(image, roi, dataset_id)
                method = f"{method}:{vis_method}"
                name = str(catalog_item.get("label") or dataset_id)
                layer_type = "ee-raster"
                layer_recipe = preview_recipe(dataset_id, catalog_item, start_date, end_date, method)
            except Exception as exc:
                attempts.append(f"Image failed: {exc}")
                try:
                    fc = ee.FeatureCollection(dataset_id).filterBounds(roi)
                    image = fc.style(color="#16734d", fillColor="#16734d33", width=2).clip(roi)
                    vis = {}
                    name = str(catalog_item.get("label") or dataset_id)
                    layer_type = "ee-vector"
                    legend = [["#16734d", "Styled features"]]
                    method = "featurecollection-style"
                    layer_recipe = preview_recipe(dataset_id, catalog_item, start_date, end_date, method)
                except Exception as vector_exc:
                    attempts.append(f"FeatureCollection failed: {vector_exc}")
                    raise ValueError("; ".join(attempts)) from vector_exc

    requested_name = str(payload.get("name") or "").strip()
    if requested_name:
        name = requested_name[:120]
        layer_recipe["name"] = name
        layer_recipe["label"] = name
    style_profile = style_profile_for_layer(dataset_id, layer_type, method, name)
    default_style_preset = str(payload.get("stylePreset") or "default")
    vis_override = payload.get("visParams") if isinstance(payload.get("visParams"), dict) else layer_recipe.get("visParams")
    if isinstance(vis_override, dict):
        vis = sanitize_vis_params(vis_override, vis)
        default_style_preset = default_style_preset if default_style_preset != "default" else "custom"
    legend_override = payload.get("legend") if isinstance(payload.get("legend"), list) else layer_recipe.get("legend")
    legend = sanitize_legend(legend_override, legend)
    layer_recipe["visParams"] = vis
    layer_recipe["legend"] = legend
    layer = {
        "id": layer_id_for_dataset(f"{dataset_id}:{hashlib.sha1(json.dumps({'aoi': aoi, 'recipe': layer_recipe}, sort_keys=True).encode('utf-8')).hexdigest()[:12]}"),
        "name": name,
        "dataset": dataset_id,
        "type": layer_type,
        "shown": True,
        "opacity": 0.78 if layer_type == "ee-vector" else 0.82,
        "tileUrl": tile_url(image, vis),
        "legend": legend,
        "visParams": vis,
        "styleProfile": style_profile,
        "stylePreset": default_style_preset,
        "method": method,
        "recipe": layer_recipe,
        "summary": {
            "startDate": layer_recipe.get("startDate", start_date),
            "endDate": layer_recipe.get("endDate", end_date),
            "band": layer_recipe.get("band"),
            "temporalReducer": layer_recipe.get("temporalReducer") or layer_recipe.get("operation"),
            "periodLabel": layer_recipe.get("periodLabel"),
            "cloudPct": cloud_pct,
        },
        "aoi": aoi,
        "bounds": aoi["bounds"],
        "warnings": warnings,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    return {"ok": True, "layer": layer, "warnings": warnings}


def build_ndvi_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    import ee

    resolved_project = easygee_project.resolve_project(payload.get("project"), remember_discovered=True)
    project = resolved_project.project
    if not project or project == DEFAULT_PROJECT:
        raise ValueError("A concrete Earth Engine project id is required")
    aoi = normalize_aoi(payload)
    start_date = str(payload.get("startDate") or "2024-01-01")
    end_date = str(payload.get("endDate") or datetime.now(timezone.utc).date().isoformat())
    try:
        cloud_pct = float(payload.get("cloudPct") or 80)
    except Exception:
        cloud_pct = 80.0
    try:
        scale = float(payload.get("scale") or 10)
    except Exception:
        scale = 10.0

    ee.Initialize(project=project)
    roi = ee_geometry_from_aoi(ee, aoi)
    warnings: list[str] = []
    ndvi, collection, method = sentinel2_ndvi_image(ee, roi, start_date, end_date, cloud_pct, warnings)
    vis = {"min": 0, "max": 0.8, "palette": ["#2c105c", "#4856a5", "#31a354", "#addd8e", "#f7fcb9"]}
    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.median(), sharedInputs=True)
        .combine(ee.Reducer.minMax(), sharedInputs=True)
        .combine(ee.Reducer.stdDev(), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=True)
    )
    stats = ndvi.reduceRegion(
        reducer=reducer,
        geometry=roi,
        scale=scale,
        bestEffort=True,
        maxPixels=1_000_000_000,
        tileScale=4,
    ).getInfo()
    valid_area = (
        ee.Image.pixelArea()
        .updateMask(ndvi.mask())
        .rename("valid_ndvi_area_m2")
        .reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=roi,
            scale=scale,
            bestEffort=True,
            maxPixels=1_000_000_000,
            tileScale=4,
        )
        .getInfo()
    )
    try:
        scene_count = int(collection.size().getInfo())
    except Exception:
        scene_count = None
    summary = {
        "dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "index": "NDVI",
        "method": method,
        "project": project,
        "startDate": start_date,
        "endDate": end_date,
        "cloudPct": cloud_pct,
        "scale": scale,
        "aoi": aoi,
        "aoiAreaM2": roi.area(maxError=1).getInfo(),
        "validNdviAreaM2": valid_area.get("valid_ndvi_area_m2"),
        "sceneCount": scene_count,
        "mean": stats.get("NDVI_mean"),
        "median": stats.get("NDVI_median"),
        "min": stats.get("NDVI_min"),
        "max": stats.get("NDVI_max"),
        "stdDev": stats.get("NDVI_stdDev"),
        "count": stats.get("NDVI_count"),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    layer = {
        "id": layer_id_for_dataset(
            "easygee-s2-ndvi:"
            + start_date
            + ":"
            + end_date
            + ":"
            + hashlib.sha1(json.dumps(aoi, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        ),
        "name": "Sentinel-2 NDVI",
        "dataset": "EASYGEE/S2_NDVI",
        "type": "ee-derived",
        "shown": True,
        "opacity": 0.86,
        "tileUrl": ndvi.getMapId(vis)["tile_fetcher"].url_format,
        "legend": [["#2c105c", "Low"], ["#31a354", "Medium"], ["#f7fcb9", "High"]],
        "visParams": vis,
        "styleProfile": "ndvi",
        "stylePreset": "default",
        "method": method,
        "aoi": aoi,
        "bounds": aoi["bounds"],
        "summary": summary,
        "warnings": warnings,
        "generatedAt": summary["generatedAt"],
    }
    return {"ok": True, "layer": layer, "summary": summary, "warnings": warnings}


def sample_quota_state(project: str) -> dict[str, Any]:
    return {
        "project": project,
        "service": "earthengine.googleapis.com",
        "consoleUrl": f"https://console.cloud.google.com/iam-admin/quotas?service=earthengine.googleapis.com&project={project}",
        "source": "official Earth Engine default",
        "usageSource": None,
        "refreshedAt": datetime.now(timezone.utc).isoformat(),
        "status": "default-only",
        "indicator": "warn",
        "warnings": ["Live quota lookup was not run."],
        "rows": [
            {
                "name": "Daily EECU time",
                "nameZh": "每日 EECU 计算时间",
                "nameEn": "Daily EECU time",
                "metric": "earthengine.googleapis.com/daily_eecu_usage_time",
                "limit": "Unlimited by default",
                "used": "N/A",
                "remaining": "N/A",
                "unit": "seconds/day",
                "status": "unknown",
                "source": "official Earth Engine default",
                "note": "Usage requires Cloud Monitoring.",
                "percent": None,
            },
            {
                "name": "Average batch tasks",
                "nameZh": "平均批处理任务",
                "nameEn": "Average batch tasks",
                "metric": "earthengine.googleapis.com",
                "limit": "2 tasks on average",
                "used": "N/A",
                "remaining": "N/A",
                "unit": "tasks",
                "status": "unknown",
                "source": "official Earth Engine default",
                "note": "Usage requires Cloud Monitoring.",
                "percent": None,
            },
            {
                "name": "Asset storage",
                "nameZh": "资产存储",
                "nameEn": "Asset storage",
                "metric": "earthengine.googleapis.com",
                "limit": "250 GB",
                "used": "N/A",
                "remaining": "N/A",
                "unit": "GB",
                "status": "unknown",
                "source": "official Earth Engine default",
                "note": "Usage requires Cloud Monitoring.",
                "percent": None,
            },
        ],
    }


def is_user_read_quota(quota: dict[str, Any]) -> bool:
    quota_name = str(quota.get("quota") or quota.get("name") or "").lower()
    squashed = "".join(char for char in quota_name if char.isalnum())
    return "read" in quota_name and (
        "peruser" in squashed or "peraccount" in squashed or "per user" in quota_name or "per account" in quota_name
    )


def quota_allows_inferred_zero(quota: dict[str, Any]) -> bool:
    metric = str(quota.get("metric") or "").lower()
    quota_name = str(quota.get("quota") or quota.get("name") or "").lower()
    return "bigquery_slot_usage_time" in metric or "bigquery slot" in quota_name


def quota_usage_unit(quota: dict[str, Any]) -> str | None:
    unit = str(quota.get("unit") or "").strip()
    metric = str(quota.get("metric") or "").lower()
    quota_name = str(quota.get("quota") or quota.get("name") or "").lower()
    if unit == "s{CPU}" or "eecu" in metric or "eecu" in quota_name or "slot" in metric or "slot" in quota_name:
        return unit
    return None


def quota_limit_unit(quota: dict[str, Any]) -> str:
    unit = str(quota.get("unit") or "").strip()
    return "" if unit == "-" else unit


def infer_noncommercial_tier(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        quota_name = str(row.get("quota") or row.get("name") or "").lower()
        if not ("noncommercial" in quota_name and "eecu" in quota_name and "month" in quota_name):
            continue
        limit = parse_float(row.get("value"))
        if limit is None:
            continue
        rounded = int(round(limit))
        for known_limit, (name, name_zh, name_en) in NONCOMMERCIAL_TIER_LIMITS.items():
            if abs(rounded - known_limit) <= max(1, known_limit * 0.001):
                return {
                    "name": name,
                    "nameZh": name_zh,
                    "nameEn": name_en,
                    "kind": "noncommercial",
                    "source": "monthly_eecu_system_limit",
                    "limit": compact_value(row.get("value"), row.get("unit")),
                    "inferred": True,
                }
        return {
            "name": "Custom / Unknown",
            "nameZh": "自定义（非商业）",
            "nameEn": "Custom (noncommercial)",
            "kind": "noncommercial",
            "source": "monthly_eecu_system_limit",
            "limit": compact_value(row.get("value"), row.get("unit")),
            "inferred": True,
        }
    return None


def infer_commercial_tier(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Best-effort usage tier inference from quota-like commercial plan limits."""

    by_name = {str(row.get("quota") or row.get("name") or "").lower(): row for row in rows}

    def find_value(*needles: str) -> float | None:
        for name, row in by_name.items():
            if all(needle in name for needle in needles):
                return parse_float(row.get("value"))
        return None

    storage_gb = find_value("asset", "storage")
    high_volume = find_value("high-volume", "concurrent")
    batch_tasks = find_value("batch", "tasks")
    if storage_gb is not None and storage_gb >= 1000:
        return {
            "name": "Professional",
            "nameZh": "Professional（商业）",
            "nameEn": "Professional (commercial)",
            "kind": "commercial",
            "source": "storage_or_high_volume_quota",
            "inferred": True,
        }
    if high_volume is not None and high_volume >= 100:
        return {
            "name": "Professional",
            "nameZh": "Professional（商业）",
            "nameEn": "Professional (commercial)",
            "kind": "commercial",
            "source": "high_volume_quota",
            "inferred": True,
        }
    if batch_tasks is not None and batch_tasks >= 8:
        return {
            "name": "Basic",
            "nameZh": "Basic（商业）",
            "nameEn": "Basic (commercial)",
            "kind": "commercial",
            "source": "batch_task_quota",
            "inferred": True,
        }
    return None


def usage_matches_quota(quota: dict[str, Any], usage_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metric = str(quota.get("metric") or "").lower()
    metric_tail = metric.rsplit("/", 1)[-1] if "/" in metric else ""
    quota_name = str(quota.get("quota") or quota.get("name") or "").lower()
    matches: list[dict[str, Any]] = []
    if is_user_read_quota(quota):
        for usage in usage_rows:
            haystack = f"{usage.get('quota_metric', '')} {usage.get('limit_name', '')} {usage.get('labels', '')}".lower()
            squashed = "".join(char for char in haystack if char.isalnum())
            if "read" in haystack and (
                "peruser" in squashed or "peraccount" in squashed or "user" in haystack or "account" in haystack
            ):
                matches.append(usage)
        return matches
    for usage in usage_rows:
        haystack = f"{usage.get('quota_metric', '')} {usage.get('limit_name', '')}".lower()
        if metric and metric != "earthengine.googleapis.com" and (metric in haystack or metric_tail in haystack):
            matches.append(usage)
            continue
        if "asset" in quota_name and "asset" in haystack:
            matches.append(usage)
            continue
        if "batch" in quota_name and ("task" in haystack or "batch" in haystack):
            matches.append(usage)
    return matches


def usage_for_quota(quota: dict[str, Any], usage_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = usage_matches_quota(quota, usage_rows)
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    values = [parse_float(str(usage.get("value") or "")) for usage in matches]
    numeric_values = [value for value in values if value is not None]
    if not numeric_values:
        return matches[0]
    latest = max(str(usage.get("end_time") or "") for usage in matches)
    return {
        "quota_metric": matches[0].get("quota_metric") or "",
        "limit_name": matches[0].get("limit_name") or "",
        "metric_type": matches[0].get("metric_type") or "",
        "value": f"{sum(numeric_values):g}",
        "end_time": latest,
        "labels": f"{len(numeric_values)} series",
    }


def is_nonblocking_quota_fallback_warning(warning: Any) -> bool:
    text = str(warning or "").lower()
    return (
        "skipping gcloud quota command groups" in text
        and "local components" in text
        and ("alpha" in text or "beta" in text)
    )


def report_warnings_for_console(report_json: dict[str, Any]) -> list[str]:
    warnings = [str(item) for item in (report_json.get("warnings") or []) if str(item).strip()]
    if report_json.get("live_source"):
        warnings = [item for item in warnings if not is_nonblocking_quota_fallback_warning(item)]
    return warnings


def quota_state_from_report(report: Any) -> dict[str, Any]:
    report_json = report_to_plain_json(report)
    source_rows = report_json.get("live_quotas") or report_json.get("default_quotas") or []
    source = report_json.get("live_source") or "official Earth Engine default"
    usage_source = report_json.get("usage_source")
    usage_rows = report_json.get("usage_rows") or []
    source_is_default = "default" in str(source).lower()
    tier = infer_noncommercial_tier(source_rows)
    if tier is None and not source_is_default:
        tier = infer_commercial_tier(source_rows)
    rows: list[dict[str, Any]] = []
    preferred_terms = ("eecu", "batch", "asset", "request", "slot")
    ordered_rows = sorted(
        source_rows,
        key=lambda row: (
            0 if any(term in str(row.get("quota", "")).lower() for term in preferred_terms) else 1,
            str(row.get("quota", "")).lower(),
        ),
    )
    for row in ordered_rows[:8]:
        row_name = row.get("quota") or row.get("name") or "quota"
        name_zh, name_en = quota_label_pair(str(row_name))
        usage = usage_for_quota(row, usage_rows)
        unlimited_limit = is_unlimited_quota_value(row.get("value"))
        limit_number = parse_float(row.get("value"))
        used_number = parse_float(usage.get("value") if usage else None)
        inferred_zero_usage = False
        if usage_source and usage is None and limit_number is not None and quota_allows_inferred_zero(row):
            used_number = 0.0
            inferred_zero_usage = True
        percent = None
        remaining = "N/A"
        status = "unknown"
        note = ""
        usage_known = used_number is not None
        if not usage:
            note = (
                "No usage time series in the selected Monitoring window; displayed as zero."
                if inferred_zero_usage
                else "Usage time series is not provided for this quota dimension."
                if usage_source
                else "Usage requires Cloud Monitoring."
            )
        if unlimited_limit:
            remaining = "Unlimited"
            status = "ok" if usage_known else "unknown"
        elif limit_number is not None and used_number is not None:
            remaining_number = max(0.0, limit_number - used_number)
            remaining = f"{remaining_number:g} {quota_limit_unit(row)}".strip()
            percent = round(min(100.0, max(0.0, (used_number / limit_number) * 100.0)), 1) if limit_number else None
            status = "warn" if percent is not None and percent >= 80 else "ok"
        usage_unit = quota_usage_unit(row)
        rows.append(
            {
                "name": row_name,
                "nameZh": name_zh,
                "nameEn": name_en,
                "metric": row.get("metric") or "",
                "limit": compact_value(row.get("value"), row.get("unit")),
                "used": compact_value(
                    "0" if inferred_zero_usage else (usage.get("value") if usage else None),
                    usage_unit if (inferred_zero_usage or usage) else None,
                ),
                "remaining": remaining,
                "unit": row.get("unit") or "",
                "status": status,
                "source": row.get("source") or source,
                "note": note,
                "percent": percent,
                "unlimited": unlimited_limit,
                "usageKnown": usage_known,
                "inferredZeroUsage": inferred_zero_usage,
            }
        )
    status = "default-only"
    indicator = "warn"
    if report_json.get("live_source") and usage_source and any(item.get("percent") is not None for item in rows):
        status = "live-with-usage"
        indicator = "warn" if any(item.get("status") == "warn" for item in rows) else "ok"
    elif report_json.get("live_source"):
        status = "live-limit-only"
        indicator = "warn"
    return {
        "project": report_json.get("project"),
        "service": report_json.get("service"),
        "consoleUrl": report_json.get("console_url"),
        "source": source,
        "usageSource": usage_source,
        "refreshedAt": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "indicator": indicator,
        "warnings": report_warnings_for_console(report_json),
        "tier": tier,
        "rows": rows,
    }


def report_to_plain_json(report: Any) -> dict[str, Any]:
    try:
        from show_ee_quotas import report_to_json

        return report_to_json(report)
    except Exception:
        return json.loads(json.dumps(asdict(report), ensure_ascii=False))


def build_quota_state(project: str, include_usage: bool, no_live: bool, minutes: int) -> dict[str, Any]:
    try:
        from show_ee_quotas import build_report

        args = argparse.Namespace(
            project=project,
            console_url=None,
            service=None,
            no_live=no_live,
            include_usage=include_usage,
            minutes=minutes,
        )
        return quota_state_from_report(build_report(args))
    except Exception as exc:
        state = sample_quota_state(project)
        state["warnings"] = [f"Quota lookup failed: {exc}"]
        return state


def leaflet_css() -> str:
    return """
    .leaflet-container { overflow: hidden; outline: 0; font: 12px/1.5 Inter, "Segoe UI", Arial, sans-serif; background: #dfe7e2; }
    .leaflet-pane, .leaflet-map-pane, .leaflet-tile, .leaflet-marker-icon, .leaflet-marker-shadow,
    .leaflet-tile-container, .leaflet-pane > svg, .leaflet-pane > canvas, .leaflet-zoom-box,
    .leaflet-image-layer, .leaflet-layer { position: absolute; left: 0; top: 0; }
    .leaflet-tile, .leaflet-marker-icon, .leaflet-marker-shadow { user-select: none; -webkit-user-drag: none; }
    .leaflet-tile { width: 256px; height: 256px; max-width: none !important; max-height: none !important; border: 0; }
    .leaflet-container img { max-width: none !important; }
    .leaflet-pane { z-index: 400; }
    .leaflet-tile-pane { z-index: 200; }
    .leaflet-overlay-pane { z-index: 400; }
    .leaflet-shadow-pane { z-index: 500; }
    .leaflet-marker-pane { z-index: 600; }
    .leaflet-tooltip-pane { z-index: 650; }
    .leaflet-popup-pane { z-index: 700; }
    .leaflet-zoom-animated { transform-origin: 0 0; }
    .leaflet-interactive { cursor: pointer; }
    .leaflet-control { position: relative; z-index: 800; pointer-events: auto; }
    .leaflet-top, .leaflet-bottom { position: absolute; z-index: 1000; pointer-events: none; }
    .leaflet-top { top: 0; }
    .leaflet-right { right: 0; }
    .leaflet-bottom { bottom: 0; }
    .leaflet-left { left: 0; }
    .leaflet-control { float: left; clear: both; margin: 10px; }
    .leaflet-right .leaflet-control { float: right; }
    .leaflet-bottom .leaflet-control { margin-bottom: 10px; }
    .leaflet-control a { text-decoration: none; }
    .leaflet-control-zoom a {
      display: block; width: 28px; height: 28px; line-height: 28px; text-align: center;
      background: #fff; color: #17202a; border-bottom: 1px solid #cfd8d3; font-size: 18px; font-weight: 700;
    }
    .leaflet-control-zoom a:first-child { border-radius: 4px 4px 0 0; }
    .leaflet-control-zoom a:last-child { border-bottom: 0; border-radius: 0 0 4px 4px; }
    .leaflet-control-attribution { background: rgba(255,255,255,0.86); padding: 2px 6px; font-size: 11px; }
    """


def shell_css() -> str:
    return """
    :root {
      color-scheme: light;
      --bg: #eef3f1;
      --panel: #ffffff;
      --panel-2: #f7faf8;
      --line: #d7dfda;
      --line-strong: #b7c5bf;
      --text: #17202a;
      --muted: #5d6d66;
      --accent: #16734d;
      --accent-soft: #e0f2ea;
      --warn: #a05a00;
      --shadow: 0 8px 26px rgba(16, 24, 40, 0.10);
      --rail-left: 8px;
      --rail-pad: 6px;
      --rail-border: 1px;
      --rail-button: 30px;
      --rail-button-half: 15px;
      --logo-size: 36px;
      --logo-half: 18px;
      --rail-center-x: calc(var(--rail-left) + var(--rail-border) + var(--rail-pad) + var(--rail-button-half));
      --logo-left: calc(var(--rail-center-x) - var(--logo-half));
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; overflow: hidden; }
    body { font-family: Inter, "Segoe UI", Arial, sans-serif; color: var(--text); background: var(--bg); letter-spacing: 0; }
    button, input, select, textarea { font: inherit; letter-spacing: 0; }
    .app {
      height: 100vh;
      display: block;
      min-width: 0;
      min-height: 0;
    }
    .topbar {
      position: fixed;
      left: var(--logo-left);
      right: auto;
      top: 8px;
      height: var(--logo-size);
      width: auto;
      z-index: 1700;
      overflow: visible;
      pointer-events: auto;
    }
    .logo-layer {
      height: var(--logo-size);
      width: min(280px, calc(100vw - 52px));
      max-width: min(280px, calc(100vw - 52px));
      min-width: var(--logo-size);
      display: flex;
      align-items: center;
      justify-content: flex-start;
      gap: 8px;
      padding: 3px 9px 3px 3px;
      background: rgba(251, 253, 252, 0.78);
      border: 1px solid rgba(215, 223, 218, 0.86);
      border-radius: 7px;
      box-shadow: 0 3px 12px rgba(16, 24, 40, 0.10);
      backdrop-filter: blur(12px);
      color: var(--text);
      cursor: pointer;
      appearance: none;
      text-align: left;
      overflow: hidden;
      position: relative;
      transition: width 160ms ease, max-width 160ms ease, padding 160ms ease, background 160ms ease;
    }
    .logo-layer:hover, .logo-layer:focus { background: rgba(251, 253, 252, 0.92); }
    .logo-layer:focus { outline: 2px solid rgba(22, 115, 77, 0.35); outline-offset: 2px; }
    .logo-layer.collapsed { width: var(--logo-size); max-width: var(--logo-size); justify-content: center; gap: 0; padding: 0; background: transparent; border-color: transparent; box-shadow: none; backdrop-filter: none; }
    .mark {
      width: 32px; height: 32px; border-radius: 8px;
      display: grid; place-items: center;
      background: transparent;
      position: relative;
      flex: 0 0 32px;
      overflow: hidden;
      box-shadow: 0 3px 10px rgba(16, 24, 40, 0.18), 0 0 0 1px rgba(255, 255, 255, 0.72);
    }
    .mark img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
    .logo-layer-copy {
      min-width: 0;
      width: 228px;
      display: grid;
      gap: 1px;
      opacity: 1;
      transition: width 150ms ease, opacity 120ms ease;
    }
    .logo-layer-copy strong {
      min-width: 0;
      color: var(--text);
      font-size: 12px;
      font-weight: 760;
      line-height: 1.15;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .logo-layer-copy span {
      min-width: 0;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .logo-layer.collapsed .logo-layer-copy {
      width: 0;
      opacity: 0;
      pointer-events: none;
    }
    .logo-layer.collapsed:hover,
    .logo-layer.collapsed:focus-visible,
    .logo-layer.collapsed.source-open {
      width: min(280px, calc(100vw - 52px));
      max-width: min(280px, calc(100vw - 52px));
      justify-content: flex-start;
      gap: 8px;
      padding: 3px 9px 3px 3px;
      background: rgba(251, 253, 252, 0.94);
      border-color: rgba(194, 213, 202, 0.96);
      box-shadow: 0 7px 22px rgba(16, 24, 40, 0.14);
      backdrop-filter: blur(12px);
    }
    .logo-layer.collapsed:hover .logo-layer-copy,
    .logo-layer.collapsed:focus-visible .logo-layer-copy,
    .logo-layer.collapsed.source-open .logo-layer-copy {
      width: 228px;
      opacity: 1;
    }
    .mark::after {
      content: "i";
      position: absolute;
      right: 2px;
      bottom: 2px;
      z-index: 5;
      width: 12px;
      height: 12px;
      display: grid;
      place-items: center;
      border: 1px solid rgba(255,255,255,0.9);
      border-radius: 50%;
      background: rgba(20, 54, 42, 0.92);
      color: #fff;
      font-size: 8px;
      font-weight: 820;
      line-height: 1;
      box-shadow: 0 1px 4px rgba(16,24,40,0.28);
    }
    .logo-layer.measure-active .mark {
      filter: saturate(1.32) hue-rotate(24deg) brightness(1.06);
      animation: easygee-measure-breathe 1.8s ease-in-out infinite;
    }
    .logo-layer.measure-active .mark::before {
      content: "";
      position: absolute;
      inset: 0;
      z-index: 2;
      border-radius: inherit;
      background: rgba(40, 205, 132, 0.26);
      mix-blend-mode: screen;
      pointer-events: none;
    }
    .logo-layer.measure-active .mark::after {
      background: #0f8a5c;
      box-shadow: 0 0 0 2px rgba(40, 205, 132, 0.18), 0 1px 5px rgba(16,24,40,0.30);
    }
    .logo-layer.measure-active::after {
      content: "";
      position: absolute;
      inset: -1px;
      border: 1px solid rgba(40, 205, 132, 0.38);
      border-radius: inherit;
      pointer-events: none;
      animation: easygee-measure-ring 1.8s ease-in-out infinite;
    }
    .icon-btn.measurement-ready {
      border-color: rgba(22, 115, 77, 0.55);
      color: var(--accent);
    }
    .icon-btn.measurement-prompt {
      border-color: rgba(22, 115, 77, 0.62);
      background: var(--accent-soft);
      color: var(--accent);
      animation: easygee-layer-prompt 1.8s ease-in-out infinite;
    }
    .icon-btn.measurement-ready::after {
      content: "";
      position: absolute;
      top: 3px;
      right: 3px;
      width: 7px;
      height: 7px;
      border: 1px solid #fff;
      border-radius: 50%;
      background: #d99724;
      box-shadow: 0 0 0 1px rgba(217,151,36,0.18);
      animation: easygee-measure-notice 1.35s ease-in-out infinite;
    }
    @keyframes easygee-measure-breathe {
      0%, 100% { box-shadow: 0 0 0 2px rgba(40,205,132,0.28), 0 0 10px rgba(40,205,132,0.24), 0 3px 10px rgba(16,24,40,0.18); }
      50% { box-shadow: 0 0 0 4px rgba(40,205,132,0.42), 0 0 20px rgba(40,205,132,0.42), 0 3px 10px rgba(16,24,40,0.18); }
    }
    @keyframes easygee-measure-ring {
      0%, 100% { opacity: 0.32; transform: scale(1); }
      50% { opacity: 0.82; transform: scale(1.035); }
    }
    @keyframes easygee-measure-notice {
      0%, 100% { opacity: 0.58; transform: scale(0.86); }
      50% { opacity: 1; transform: scale(1.12); }
    }
    @keyframes easygee-layer-prompt {
      0%, 100% { box-shadow: 0 0 0 2px rgba(40,205,132,0.16), 0 3px 12px rgba(16,24,40,0.08); }
      50% { box-shadow: 0 0 0 5px rgba(40,205,132,0.28), 0 0 18px rgba(40,205,132,0.26), 0 3px 12px rgba(16,24,40,0.08); }
    }
    @media (prefers-reduced-motion: reduce) {
      .logo-layer.measure-active .mark,
      .logo-layer.measure-active::after,
      .icon-btn.measurement-ready::after,
      .icon-btn.measurement-prompt { animation: none; }
    }
    .basemap-source-card {
      position: fixed;
      left: var(--logo-left);
      top: 52px;
      z-index: 1708;
      width: min(344px, calc(100vw - 16px));
      overflow: hidden;
      border: 1px solid rgba(194, 213, 202, 0.96);
      border-radius: 13px;
      background: rgba(250, 253, 251, 0.97);
      box-shadow: 0 18px 48px rgba(16, 24, 40, 0.20);
      backdrop-filter: blur(16px);
      opacity: 0;
      pointer-events: none;
      transform: translateY(-7px) scale(0.985);
      transform-origin: 18px 0;
      transition: opacity 140ms ease, transform 160ms ease;
    }
    .basemap-source-card.open {
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0) scale(1);
    }
    .basemap-source-card::before {
      content: "";
      position: absolute;
      left: 16px;
      top: 0;
      width: 38px;
      height: 3px;
      border-radius: 0 0 3px 3px;
      background: var(--accent);
    }
    .basemap-source-head {
      min-height: 42px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 0 10px 0 14px;
      border-bottom: 1px solid var(--line);
    }
    .basemap-source-kicker {
      color: #3d5148;
      font-size: 11px;
      font-weight: 820;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .basemap-source-hero {
      display: grid;
      grid-template-columns: 92px minmax(0, 1fr);
      gap: 12px;
      align-items: center;
      padding: 13px 14px 11px;
    }
    .basemap-source-visual.basemap-thumb {
      width: 92px;
      height: 66px;
      border-radius: 10px;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.45), 0 5px 15px rgba(16,24,40,0.14);
    }
    .basemap-source-name {
      color: var(--text);
      font-size: 16px;
      font-weight: 820;
      line-height: 1.18;
    }
    .basemap-source-service {
      margin-top: 5px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .basemap-source-grid {
      margin: 0 14px;
      padding: 9px 0;
      display: grid;
      gap: 7px;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }
    .basemap-source-row {
      display: grid;
      grid-template-columns: 72px minmax(0, 1fr);
      gap: 9px;
      align-items: start;
    }
    .basemap-source-row dt {
      margin: 0;
      color: #718078;
      font-size: 10px;
      line-height: 1.35;
    }
    .basemap-source-row dd {
      margin: 0;
      color: #25322d;
      font-size: 10px;
      font-weight: 680;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .basemap-source-link {
      min-height: 38px;
      margin: 7px 9px 9px;
      padding: 0 9px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      border-radius: 8px;
      color: #145e42;
      font-size: 11px;
      font-weight: 780;
      text-decoration: none;
    }
    .basemap-source-link:hover,
    .basemap-source-link:focus-visible { background: var(--accent-soft); }
    .basemap-source-link svg {
      width: 15px;
      height: 15px;
      fill: none;
      stroke: currentColor;
      stroke-width: 1.8;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    h1 {
      position: absolute;
      width: 1px;
      height: 1px;
      margin: -1px;
      padding: 0;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
      border: 0;
    }
    .top-meta { display: flex; align-items: center; gap: 4px; color: var(--muted); font-size: 11px; min-width: 0; flex: 0 0 auto; }
    .topbar .top-meta { display: none; }
    .pill {
      height: 22px; display: inline-flex; align-items: center; gap: 4px;
      padding: 0 6px; border: 1px solid rgba(215, 223, 218, 0.9); background: rgba(255,255,255,0.78); border-radius: 999px;
      white-space: nowrap;
    }
    .top-meta .hide-small { display: none; }
    .status-dot { width: 7px; height: 7px; border-radius: 999px; background: var(--accent); flex: 0 0 auto; }
    .toolbar { display: flex; align-items: center; gap: 4px; }
    .mobile-only { display: grid; }
    .wide-only { display: none !important; }
    .icon-btn {
      width: 26px; height: 26px; display: grid; place-items: center;
      border: 1px solid rgba(215, 223, 218, 0.95); background: rgba(255,255,255,0.82); color: var(--text);
      border-radius: 6px; cursor: pointer;
      font-size: 12px;
      line-height: 1;
      position: relative;
    }
    .icon-btn svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linecap: round; stroke-linejoin: round; }
    .icon-btn .drive-mark { width: 18px; height: 18px; }
    .icon-btn .drive-mark path { stroke: none; }
    .icon-btn > svg { display: block; }
    .icon-btn:hover { border-color: var(--line-strong); background: var(--panel-2); }
    .icon-btn.active { border-color: rgba(22, 115, 77, 0.55); background: var(--accent-soft); color: var(--accent); box-shadow: 0 0 0 2px rgba(22, 115, 77, 0.14), 0 3px 12px rgba(16, 24, 40, 0.10); }
    .icon-btn[disabled] { cursor: default; opacity: 0.42; box-shadow: none; }
    .icon-btn[disabled]:hover { border-color: rgba(215, 223, 218, 0.95); background: rgba(255,255,255,0.82); }
    .tool-rail .icon-btn[disabled]:hover { border-color: rgba(215, 223, 218, 0.86); background: rgba(255,255,255,0.9); }
    .panel-close { width: 26px; height: 26px; flex: 0 0 26px; padding: 0; margin-left: auto; align-self: center; font-size: 12px; display: grid !important; place-items: center; }
    .panel-close svg { width: 14px; height: 14px; }
    .tool-rail {
      position: fixed;
      left: var(--rail-left);
      top: 50px;
      z-index: 1650;
      display: grid;
      gap: 6px;
      padding: var(--rail-pad);
      background: transparent;
      border: 0;
      box-shadow: none;
      backdrop-filter: none;
    }
    .tool-rail .icon-btn {
      width: var(--rail-button);
      height: var(--rail-button);
      background: rgba(255,255,255,0.9);
      border-color: rgba(215, 223, 218, 0.86);
      box-shadow: 0 3px 12px rgba(16, 24, 40, 0.08);
      backdrop-filter: blur(10px);
    }
    .tool-rail .icon-btn:hover { border-color: var(--line-strong); background: #fff; }
    .tool-rail .rail-break { width: 20px; height: 1px; margin: 2px auto; background: transparent; }
    .quota-indicator {
      position: absolute;
      right: 4px;
      top: 4px;
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--accent);
      border: 1px solid #fff;
      box-shadow: 0 0 0 1px rgba(22, 115, 77, 0.14);
    }
    .quota-indicator.ok { background: var(--accent); }
    .quota-indicator.warn { background: var(--warn); box-shadow: 0 0 0 1px rgba(160, 90, 0, 0.18); }
    .quota-indicator.muted { background: #7b8781; box-shadow: 0 0 0 1px rgba(76, 86, 81, 0.16); }
    .lang-code {
      position: absolute;
      right: 3px;
      bottom: 2px;
      font-size: 8px;
      font-weight: 800;
      line-height: 1;
      color: var(--accent);
      background: rgba(255,255,255,0.82);
      border-radius: 3px;
      padding: 1px 2px;
    }
    .panel {
      min-width: 0; min-height: 0; background: var(--panel);
      border-color: var(--line); overflow: hidden; display: flex; flex-direction: column;
    }
    .left, .right {
      position: fixed;
      top: 50px;
      bottom: 10px;
      width: min(340px, 92vw);
      z-index: 1600;
      box-shadow: var(--shadow);
      transition: transform 150ms ease;
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .left { left: 52px; transform: translateX(calc(-100% - 64px)); }
    .right { right: 8px; transform: translateX(calc(100% + 18px)); }
    .left.open, .right.open { transform: translateX(0); }
    .data-panel {
      bottom: auto;
      width: min(820px, calc(100vw - 66px));
      max-height: min(574px, calc(100vh - 62px));
      min-width: min(420px, calc(100vw - 66px));
      min-height: 240px;
      border-radius: 10px;
      background: rgba(255,255,255,0.95);
      backdrop-filter: blur(12px);
    }
    .data-panel.detail-open .catalog-main { padding-right: min(430px, 46%); }
    .basemap-panel {
      position: fixed;
      left: 52px;
      top: 72px;
      z-index: 1606;
      width: min(356px, calc(100vw - 66px));
      overflow: hidden;
      background: rgba(255,255,255,0.95);
      border: 1px solid var(--line);
      border-radius: 10px;
      box-shadow: var(--shadow);
      transform: translateX(calc(-100% - 64px));
      transition: transform 150ms ease;
      backdrop-filter: blur(12px);
      min-width: 220px;
      min-height: 132px;
      max-height: calc(100vh - 86px);
      display: flex;
      flex-direction: column;
    }
    .basemap-panel.open { transform: translateX(0); }
    .basemap-body { padding: 10px; display: grid; grid-auto-rows: max-content; gap: 9px; min-height: 0; overflow-y: auto; }
    .upload-panel {
      position: fixed;
      left: 52px;
      top: 88px;
      z-index: 1680;
      width: min(430px, calc(100vw - 66px));
      overflow: hidden;
      background: rgba(255,255,255,0.97);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      transform: translateX(calc(-100% - 64px));
      transition: transform 150ms ease;
      backdrop-filter: blur(12px);
      display: flex;
      flex-direction: column;
      max-height: calc(100vh - 104px);
    }
    .upload-panel.open { transform: translateX(0); }
    .upload-panel .panel-head { min-height: 46px; background: rgba(255,255,255,0.98); }
    .upload-title { font-size: 16px; font-weight: 720; color: #172033; letter-spacing: 0; }
    .upload-body { padding: 14px 16px 16px; display: grid; gap: 12px; min-height: 0; overflow-y: auto; }
    .upload-field-label { color: #172033; font-size: 13px; font-weight: 720; }
    .upload-note { margin: -7px 0 0; color: #61708a; font-size: 12px; line-height: 1.35; }
    .upload-select {
      width: 100%;
      height: 38px;
      border: 2px solid #243b5a;
      border-radius: 0;
      background: #fff;
      color: #243047;
      padding: 0 12px;
      font-size: 14px;
    }
    .upload-row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 10px; align-items: center; }
    .upload-file-button {
      height: 32px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0 12px;
      border: 1px solid #8792a3;
      background: #f7f8fb;
      color: #172033;
      font-size: 13px;
      border-radius: 4px;
      cursor: pointer;
      white-space: nowrap;
    }
    .upload-file-name {
      height: 34px;
      min-width: 0;
      display: flex;
      align-items: center;
      border: 1px dashed #9aa9bf;
      color: #172033;
      padding: 0 10px;
      font-size: 13px;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      background: #fff;
    }
    .upload-submit {
      height: 34px;
      border: 1px solid #243b5a;
      background: #243b5a;
      color: #fff;
      border-radius: 0;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 0 12px;
      font-size: 13px;
      font-weight: 720;
      cursor: pointer;
    }
    .upload-submit svg { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linecap: round; stroke-linejoin: round; }
    .upload-submit[disabled] { opacity: 0.5; cursor: default; }
    .upload-formats { color: #61708a; font-size: 12px; line-height: 1.3; }
    .upload-status { min-height: 18px; color: var(--muted); font-size: 11px; line-height: 1.35; }
    .upload-status.error { color: #a32929; }
    .upload-list { display: grid; gap: 7px; }
    .upload-item {
      border: 1px solid #e0e8e4;
      border-radius: 7px;
      background: rgba(247,250,248,0.82);
      padding: 8px;
      display: grid;
      gap: 4px;
      min-width: 0;
    }
    .upload-item-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; }
    .upload-item-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; font-weight: 760; color: var(--text); }
    .upload-item-tag { flex: 0 0 auto; border-radius: 4px; padding: 2px 5px; font-size: 10px; font-weight: 760; color: #243b5a; background: #e9eef6; }
    .upload-item-actions { flex: 0 0 auto; display: inline-flex; align-items: center; gap: 5px; }
    .upload-remove {
      width: 26px;
      height: 26px;
      border-radius: 6px;
      color: #a32929;
      background: rgba(255,255,255,0.88);
      border: 1px solid #e3cbc8;
      box-shadow: none;
    }
    .upload-remove svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linecap: round; stroke-linejoin: round; }
    .upload-remove:hover { background: #fff5f3; border-color: #d9a5a0; color: #8f1d1d; }
    .upload-item-meta { color: var(--muted); font-size: 10px; line-height: 1.35; overflow-wrap: anywhere; }
    .basemap-toolbar { display: flex; align-items: center; gap: 8px; }
    .basemap-add {
      min-height: 32px; flex: 1; border: 1px solid rgba(22,115,77,0.32); border-radius: 7px;
      background: linear-gradient(180deg, #f8fffb, #eef8f2); color: var(--accent); cursor: pointer;
      display: inline-flex; align-items: center; justify-content: center; gap: 7px; font-size: 11px; font-weight: 760;
    }
    .basemap-add:hover { border-color: rgba(22,115,77,0.58); background: #e8f5ee; }
    .basemap-add svg, .basemap-entry-action svg, .basemap-form-button svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linecap: round; stroke-linejoin: round; }
    .basemap-custom-count { flex: 0 0 auto; color: var(--muted); font-size: 10px; white-space: nowrap; }
    .basemap-provider-auth {
      min-height: 38px; border: 1px solid #cfe0d7; border-radius: 8px; background: rgba(248,251,249,0.96); overflow: hidden;
    }
    .basemap-provider-auth-toggle {
      width: 100%; min-height: 38px; padding: 0 10px; border: 0; background: transparent;
      display: flex; align-items: center; justify-content: space-between; gap: 8px;
      color: #30473b; cursor: pointer; font-size: 10px; font-weight: 760; text-align: left;
    }
    .basemap-provider-auth-toggle:hover { background: #edf7f1; }
    .basemap-provider-auth-title { min-width: 0; display: inline-flex; align-items: center; gap: 7px; }
    .basemap-provider-auth-mark { min-width: 24px; height: 20px; padding: 0 5px; border-radius: 5px; display: inline-grid; place-items: center; background: var(--accent); color: #fff; font-size: 8px; letter-spacing: 0.06em; }
    .basemap-provider-auth-toggle::after { content: "+"; color: var(--accent); font-size: 16px; font-weight: 500; }
    .basemap-provider-auth.open .basemap-provider-auth-toggle::after { content: "−"; }
    .basemap-provider-auth-state { margin-left: auto; color: var(--muted); font-size: 9px; font-weight: 650; }
    .basemap-provider-auth.configured .basemap-provider-auth-state { color: var(--accent); }
    .basemap-provider-auth-body[hidden] { display: none !important; }
    .basemap-provider-auth-body { padding: 0 10px 10px; display: grid; gap: 7px; }
    .basemap-provider-auth-summary[hidden], .basemap-provider-auth-editor[hidden] { display: none !important; }
    .basemap-provider-auth-summary { display: flex; align-items: center; justify-content: space-between; gap: 9px; }
    .basemap-provider-auth-summary-copy { min-width: 0; display: inline-flex; align-items: center; gap: 7px; color: #52635b; font-size: 9px; line-height: 1.4; }
    .basemap-provider-auth-summary-copy::before { content: ""; width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 3px rgba(22,115,77,0.12); }
    .basemap-provider-auth-actions { display: inline-flex; align-items: center; gap: 5px; }
    .basemap-provider-auth-editor { display: grid; gap: 7px; }
    .basemap-provider-auth-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 7px; }
    .basemap-provider-auth-remember { display: inline-flex; align-items: center; gap: 6px; color: #52635b; font-size: 9px; cursor: pointer; }
    .basemap-provider-auth-remember input { width: 13px; height: 13px; margin: 0; accent-color: var(--accent); }
    .basemap-provider-auth-remember:has(input:disabled) { cursor: default; opacity: 0.55; }
    .basemap-provider-auth-help { color: var(--muted); font-size: 9px; line-height: 1.45; }
    .basemap-provider-auth-help a { color: var(--accent); font-weight: 700; text-decoration: none; }
    .basemap-provider-auth-help a:hover { text-decoration: underline; }
    .basemap-editor {
      border: 1px solid #d5e2db; border-radius: 9px; padding: 10px; display: grid; gap: 9px;
      background: linear-gradient(145deg, rgba(245,250,247,0.98), rgba(255,255,255,0.98));
      box-shadow: inset 3px 0 0 rgba(22,115,77,0.42), 0 4px 14px rgba(16,24,40,0.06);
    }
    .basemap-editor[hidden], .basemap-type-field[hidden] { display: none !important; }
    .basemap-editor-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .basemap-editor-title { font-size: 12px; font-weight: 780; color: #263a31; }
    .basemap-editor-kind { color: var(--muted); font-size: 9px; text-transform: uppercase; letter-spacing: 0.08em; }
    .basemap-editor-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .basemap-field { display: grid; gap: 4px; min-width: 0; color: #52635b; font-size: 10px; font-weight: 650; }
    .basemap-field.wide { grid-column: 1 / -1; }
    .basemap-input, .basemap-select {
      width: 100%; min-width: 0; height: 31px; border: 1px solid #ccd9d2; border-radius: 6px;
      padding: 0 8px; background: rgba(255,255,255,0.96); color: var(--text); font-size: 11px; outline: none;
    }
    .basemap-input:focus, .basemap-select:focus { border-color: rgba(22,115,77,0.64); box-shadow: 0 0 0 2px rgba(22,115,77,0.10); }
    .basemap-input.code { font-family: "Cascadia Mono", Consolas, monospace; font-size: 10px; }
    .basemap-editor details { grid-column: 1 / -1; border-top: 1px solid #dce6e0; padding-top: 7px; }
    .basemap-editor summary { cursor: pointer; color: #53645c; font-size: 10px; font-weight: 720; }
    .basemap-advanced-grid { margin-top: 8px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
    .basemap-default-toggle { grid-column: 1 / -1; display: flex; align-items: center; gap: 7px; color: #42564c; font-size: 10px; cursor: pointer; }
    .basemap-default-toggle input { accent-color: var(--accent); }
    .basemap-form-status { min-height: 16px; color: var(--muted); font-size: 10px; line-height: 1.35; }
    .basemap-form-status.success { color: #12633f; }
    .basemap-form-status.error { color: #9e2929; }
    .basemap-form-actions { display: flex; align-items: center; justify-content: flex-end; gap: 7px; }
    .basemap-form-button {
      min-height: 29px; border: 1px solid #ccd9d2; border-radius: 6px; padding: 0 9px; cursor: pointer;
      display: inline-flex; align-items: center; justify-content: center; gap: 6px; background: #fff; color: #34483e; font-size: 10px; font-weight: 730;
    }
    .basemap-form-button:hover { border-color: #9bb4a7; background: #f6faf8; }
    .basemap-form-button.primary { border-color: #16734d; background: #16734d; color: #fff; }
    .basemap-form-button.primary:hover { background: #105f3e; }
    .basemap-form-button[disabled] { cursor: default; opacity: 0.46; }
    .basemap-list { display: grid; gap: 8px; }
    .basemap-entry {
      position: relative; overflow: hidden; border: 1px solid #e0e8e4; border-radius: 8px;
      background: rgba(255,255,255,0.9); transition: border-color 140ms ease, background 140ms ease, transform 140ms ease;
    }
    .basemap-entry:hover { transform: translateY(-1px); }
    .basemap-entry:hover, .basemap-entry.active { border-color: rgba(22,115,77,0.5); background: var(--accent-soft); }
    .basemap-choice {
      width: 100%; border: 0; border-radius: 8px; background: transparent;
      padding: 8px;
      display: grid;
      grid-template-columns: 56px minmax(0, 1fr);
      gap: 10px;
      align-items: center;
      cursor: pointer;
      color: var(--text);
      text-align: left;
      transition: background 140ms ease;
    }
    .basemap-choice:hover { background: rgba(255,255,255,0.34); }
    .basemap-entry-default {
      position: absolute; top: 7px; right: 7px; z-index: 4; width: 23px; height: 23px; padding: 0;
      border: 1px solid transparent; border-radius: 6px; background: rgba(255,255,255,0.7); color: #7b897f;
      display: grid; place-items: center; cursor: pointer;
    }
    .basemap-entry-default:hover { border-color: #d0dbd5; background: #fff; color: #8b650a; }
    .basemap-entry-default.active { color: #9a6200; background: #fff7df; border-color: #e8cc82; }
    .basemap-entry-default.active svg { fill: currentColor; }
    .basemap-entry-default svg { width: 13px; height: 13px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    .basemap-entry .basemap-copy { padding-right: 24px; }
    .basemap-entry-footer { min-height: 36px; display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 5px 7px; border-top: 1px solid rgba(205,219,211,0.86); }
    .basemap-overlay-add { min-width: 0; min-height: 25px; padding: 0 7px; border: 1px solid transparent; border-radius: 6px; display: inline-flex; align-items: center; gap: 6px; color: var(--accent); background: transparent; cursor: pointer; font-size: 10px; font-weight: 760; }
    .basemap-overlay-add:hover { border-color: rgba(22,115,77,0.3); background: rgba(238,248,242,0.92); }
    .basemap-overlay-add[disabled] { color: #7b897f; cursor: default; opacity: 0.72; }
    .basemap-overlay-add svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linecap: round; stroke-linejoin: round; }
    .basemap-custom-actions { display: flex; align-items: center; justify-content: flex-end; gap: 4px; }
    .basemap-entry-action { width: 25px; height: 25px; padding: 0; border: 1px solid transparent; border-radius: 6px; display: grid; place-items: center; color: #5c6b63; background: transparent; cursor: pointer; }
    .basemap-entry-action:hover { border-color: #d0dbd5; background: rgba(255,255,255,0.82); color: #174d36; }
    .basemap-entry-action.danger:hover { color: #a32929; border-color: #e3cbc8; background: #fff6f5; }
    .basemap-entry-action[disabled] { opacity: 0.28; cursor: default; }
    .basemap-type-chip { display: inline-flex; margin-top: 4px; padding: 2px 5px; border-radius: 999px; background: rgba(22,115,77,0.09); color: #35604c; font-size: 8px; font-weight: 760; letter-spacing: 0.06em; text-transform: uppercase; }
    .basemap-thumb {
      width: 56px;
      height: 42px;
      border-radius: 9px;
      border: 1px solid rgba(27,44,37,0.14);
      overflow: hidden;
      background: #edf2ee;
      position: relative;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.44), 0 2px 6px rgba(16,24,40,0.08);
    }
    .basemap-thumb svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      display: block;
      transform: scale(1.01);
      transition: transform 180ms ease;
    }
    .basemap-choice:hover .basemap-thumb svg { transform: scale(1.055); }
    .basemap-thumb::after {
      content: "";
      position: absolute;
      inset: 0;
      z-index: 3;
      pointer-events: none;
      border-radius: inherit;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.22);
    }
    .basemap-thumb.osm { background: #eef0dd; }
    .basemap-thumb.light { background: #f3f5f2; }
    .basemap-thumb.dark { background: #182525; }
    .basemap-thumb.voyager { background: #efe4cb; }
    .basemap-thumb.topo { background: #e9e5c8; }
    .basemap-thumb.imagery { background: #294638; }
    .basemap-thumb.clarity { background: #89916c; }
    .basemap-thumb.tianditu-vector { background: #edf2de; }
    .basemap-thumb.tianditu-imagery { background: #315342; }
    .basemap-thumb.tianditu-terrain { background: #ded8b7; }
    .basemap-thumb.custom-xyz { background: #dcece3; }
    .basemap-thumb.custom-tms { background: #e9e2cf; }
    .basemap-thumb.custom-arcgis { background: #dbe7ef; }
    .basemap-thumb.custom-wms { background: #dce8dc; }
    .basemap-thumb.custom-wmts { background: #e6e0ee; }
    .basemap-thumb.custom-pmtiles { background: #193342; }
    .basemap-thumb.custom-cog { background: #153b3f; }
    .basemap-copy { min-width: 0; }
    .basemap-name { font-size: 12px; font-weight: 760; line-height: 1.2; }
    .basemap-note { margin-top: 3px; color: var(--muted); font-size: 10px; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .panel-head {
      min-height: 42px; display: flex; align-items: center; justify-content: space-between;
      gap: 10px; padding: 0 12px; border-bottom: 1px solid var(--line); background: var(--panel-2);
    }
    .panel-title { font-size: 12px; font-weight: 760; text-transform: uppercase; color: #405049; }
    .panel-heading { min-width: 0; }
    .panel-subtitle { margin-top: 2px; font-size: 10px; color: var(--muted); line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .panel-body { min-height: 0; overflow-y: auto; overflow-x: hidden; padding: 10px; }
    .resizable-panel { position: fixed; }
    .panel-resize-handle {
      position: absolute;
      z-index: 6;
      background: transparent;
      touch-action: none;
    }
    .panel-resize-handle.edge-e { top: 42px; right: 0; bottom: 0; width: 8px; cursor: ew-resize; }
    .panel-resize-handle.edge-w { top: 42px; left: 0; bottom: 0; width: 8px; cursor: ew-resize; }
    .panel-resize-handle.edge-s { left: 0; right: 0; bottom: 0; height: 8px; cursor: ns-resize; }
    .panel-resize-handle.corner-se { right: 0; bottom: 0; width: 14px; height: 14px; cursor: nwse-resize; }
    .panel-resize-handle.corner-sw { left: 0; bottom: 0; width: 14px; height: 14px; cursor: nesw-resize; }
    .panel-resize-handle:hover { background: rgba(22, 115, 77, 0.10); }
    .section-title { margin: 12px 0 7px; font-size: 11px; font-weight: 760; color: var(--muted); text-transform: uppercase; }
    .section-title:first-child { margin-top: 0; }
    .search {
      width: 100%; height: 30px; border: 1px solid var(--line); border-radius: 6px;
      padding: 0 9px; color: var(--text); background: #fff;
      font-size: 12px;
    }
    .catalog-shell {
      display: grid;
      grid-template-columns: 216px minmax(0, 1fr);
      gap: 10px;
      min-height: 0;
    }
    .catalog-sidebar {
      min-width: 0;
      border: 1px solid #e3ebe6;
      border-radius: 8px;
      background: rgba(250,252,251,0.88);
      padding: 9px;
      display: grid;
      gap: 8px;
      align-content: start;
    }
    .catalog-main { min-width: 0; display: grid; gap: 8px; align-content: start; }
    .catalog-search-row {
      display: grid;
      grid-template-columns: minmax(190px, 0.86fr) minmax(0, 1.14fr);
      gap: 8px;
      align-items: center;
    }
    .catalog-filter-title {
      margin-top: 1px;
      font-size: 11px;
      font-weight: 760;
      color: #405049;
      text-transform: uppercase;
    }
    .category-list { display: grid; gap: 5px; min-width: 0; }
    .type-chip-list { display: flex; flex-wrap: wrap; gap: 5px; min-width: 0; justify-content: flex-start; align-items: center; }
    .category-list {
      max-height: min(392px, calc(100vh - 180px));
      overflow: auto;
      padding-right: 2px;
    }
    .category-button, .type-chip {
      min-width: 0;
      border: 1px solid transparent;
      background: transparent;
      color: var(--text);
      cursor: pointer;
      text-align: left;
    }
    .category-button {
      height: 28px;
      border-radius: 6px;
      padding: 0 7px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 7px;
      align-items: center;
      font-size: 11px;
    }
    .category-button span:first-child {
      min-width: 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .category-count { color: var(--muted); font-size: 10px; }
    .category-button:hover, .category-button.active {
      border-color: rgba(22,115,77,0.28);
      background: var(--accent-soft);
      color: var(--accent);
    }
    .type-chip {
      height: 28px;
      border-color: #e3ebe6;
      border-radius: 999px;
      padding: 0 9px;
      background: rgba(255,255,255,0.82);
      font-size: 10.5px;
      white-space: nowrap;
    }
    .type-chip:hover, .type-chip.active {
      border-color: rgba(22,115,77,0.42);
      background: var(--accent-soft);
      color: var(--accent);
    }
    .dataset-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin: 0;
      min-width: 0;
    }
    .dataset-toolbar .tag { flex: 0 0 auto; }
    .dataset-hint { color: var(--muted); font-size: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .layer-list, .dataset-list, .kv, .log-list, .task-list { display: grid; gap: 8px; }
    .layer-stack-group { display: grid; gap: 8px; }
    .layer-stack-group + .layer-stack-group { margin-top: 13px; padding-top: 11px; border-top: 1px solid #dfe8e3; }
    .layer-group-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; color: #40554a; font-size: 11px; font-weight: 780; letter-spacing: 0.02em; }
    .layer-group-heading span { color: var(--muted); font-size: 9px; font-weight: 620; letter-spacing: 0; }
    .layer-item, .dataset-item, .stat-row, .task-row {
      border: 1px solid var(--line); background: #fff; border-radius: 6px;
    }
    .task-row { padding: 9px; min-width: 0; }
    .task-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; min-width: 0; }
    .task-title { font-size: 12px; font-weight: 760; line-height: 1.25; min-width: 0; overflow-wrap: anywhere; }
    .task-status { flex: 0 0 auto; border: 1px solid rgba(22,115,77,0.18); border-radius: 999px; padding: 2px 7px; color: var(--accent); background: var(--accent-soft); font-size: 10px; line-height: 1.2; max-width: 92px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .task-row.status-failed .task-status, .task-row.status-cancelled .task-status { color: #a32929; background: #fff1f1; border-color: rgba(163,41,41,0.2); }
    .task-row.status-completed .task-status, .task-row.status-done .task-status { color: #16734d; background: #eef8f2; }
    .task-meta { margin-top: 6px; display: grid; gap: 3px; color: var(--muted); font-size: 11px; line-height: 1.3; overflow-wrap: anywhere; }
    .task-actions { margin-top: 7px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .task-link { color: var(--accent); text-decoration: none; font-size: 11px; font-weight: 700; }
    .task-link:hover { text-decoration: underline; }
    .layer-item { padding: 9px; min-width: 0; }
    .layer-item[data-reorderable="true"] { cursor: default; }
    .layer-item.dragging { opacity: 0.56; }
    .layer-item.drag-over { border-color: var(--accent); box-shadow: inset 0 0 0 2px rgba(22,115,77,0.18); }
    .layer-item.active { border-color: var(--accent); background: var(--accent-soft); }
    .layer-item.primary-basemap { border-color: #c9d9d0; background: linear-gradient(145deg, #f7faf8, #eef5f1); box-shadow: inset 3px 0 0 rgba(22,115,77,0.52); }
    .layer-item.basemap-overlay { box-shadow: inset 3px 0 0 rgba(49,92,116,0.45); }
    .layer-item.primary-basemap.active, .layer-item.basemap-overlay.active { border-color: var(--accent); background: var(--accent-soft); }
    .layer-top { display: flex; align-items: flex-start; gap: 8px; }
    .layer-top input { margin-top: 3px; }
    .layer-copy { min-width: 0; flex: 1 1 auto; }
    .layer-title-row { display: flex; align-items: center; gap: 6px; min-width: 0; }
    .layer-drag-handle { width: 15px; height: 22px; display: grid; place-items: center; flex: 0 0 15px; color: #819189; }
    .layer-drag-handle[draggable="true"] { cursor: grab; }
    .layer-drag-handle[draggable="true"]:active { cursor: grabbing; }
    .layer-drag-handle svg { width: 15px; height: 15px; stroke: currentColor; fill: none; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    .layer-drag-handle:not([draggable="true"]) { visibility: hidden; cursor: default; }
    .layer-item[data-reorderable="true"]:hover .layer-drag-handle, .layer-item.dragging .layer-drag-handle { color: var(--accent); }
    .layer-name { font-size: 13px; font-weight: 700; line-height: 1.25; }
    .type-dot { width: 18px; height: 18px; border-radius: 4px; display: grid; place-items: center; color: #fff; font-size: 10px; font-weight: 800; flex: 0 0 auto; }
    .type-dot.aoi { background: #c2410c; }
    .type-dot.measurements { background: #0f766e; }
    .type-dot.basemap { background: #315c74; }
    .type-dot.basemap-overlay { background: #4f7182; }
    .type-dot.raster { background: #2f7d55; }
    .type-dot.derived { background: #7a58a8; }
    .type-dot.categorical { background: #2f6fa3; }
    .type-dot.vector { background: #b45309; }
    .layer-dataset { margin-top: 2px; color: var(--muted); font-size: 11px; line-height: 1.25; overflow-wrap: anywhere; }
    .layer-actions { display: flex; gap: 4px; align-items: center; flex: 0 0 auto; }
    .layer-action { width: 26px; height: 26px; border-radius: 7px; background: #fff; border-color: var(--line); }
    .layer-action.danger { color: #a32929; }
    .layer-style-row { display: grid; grid-template-columns: 46px minmax(0, 1fr); gap: 7px; align-items: center; margin-top: 8px; color: var(--muted); font-size: 11px; }
    .layer-style-row select, .layer-style-row input[type="color"] { min-width: 0; width: 100%; height: 28px; border: 1px solid var(--line); border-radius: 7px; background: #fff; color: var(--text); font: inherit; }
    .layer-style-row input[type="color"] { padding: 2px; }
    .palette-preview { display: flex; height: 8px; margin-top: 6px; border: 1px solid rgba(21,35,28,0.12); border-radius: 999px; overflow: hidden; }
    .palette-preview span { flex: 1 1 0; }
    .opacity-row { display: grid; grid-template-columns: 46px minmax(0, 1fr) 34px; gap: 7px; align-items: center; margin-top: 8px; color: var(--muted); font-size: 11px; }
    input[type="range"] { width: 100%; min-width: 0; accent-color: var(--accent); }
    .dataset-list { gap: 0; border: 1px solid #e3ebe6; border-radius: 8px; overflow: auto; max-height: min(430px, calc(100vh - 170px)); background: rgba(255,255,255,0.78); }
    .dataset-item { padding: 10px; cursor: pointer; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 9px; align-items: center; min-width: 0; border-radius: 8px; box-shadow: 0 1px 0 rgba(16,24,40,0.03); }
    .dataset-list .dataset-item { border: 0; border-bottom: 1px solid #e3ebe6; border-radius: 0; box-shadow: none; }
    .dataset-list .dataset-item:last-child { border-bottom: 0; }
    .dataset-item:hover, .dataset-item.active { border-color: rgba(22, 115, 77, 0.45); background: var(--accent-soft); }
    .dataset-name { font-size: 12px; font-weight: 760; line-height: 1.25; }
    .dataset-meta { margin-top: 3px; font-size: 11px; color: var(--muted); line-height: 1.25; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .dataset-attrs { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 5px; }
    .dataset-attr { max-width: 100%; border: 1px solid #dce8e2; border-radius: 999px; padding: 2px 7px; background: #f8fbf9; color: #46564f; font-size: 10.5px; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .dataset-attr strong { color: #21342b; font-weight: 760; }
    .dataset-tags { margin-top: 3px; font-size: 10px; color: var(--muted); line-height: 1.25; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .dataset-provider { margin-top: 3px; font-size: 10px; color: #718078; line-height: 1.25; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .dataset-status { margin-top: 6px; width: fit-content; max-width: 100%; border: 1px solid rgba(22,115,77,0.18); border-radius: 999px; padding: 2px 7px; background: rgba(232,244,238,0.65); font-size: 10px; color: var(--accent); line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .dataset-status.muted { color: var(--muted); }
    .dataset-status.pending { color: #8a5a00; border-color: rgba(160,90,0,0.22); background: #fff6df; }
    .dataset-status.error { color: #9f1239; border-color: rgba(159,18,57,0.24); background: #fff1f2; }
    .dataset-actions { display: grid; grid-auto-flow: column; gap: 6px; align-items: center; }
    .dataset-add, .dataset-favorite { width: 28px; height: 28px; border-color: var(--line); background: #fff; border-radius: 8px; }
    .dataset-add[disabled] { cursor: progress; opacity: 0.62; }
    .dataset-favorite.active { border-color: rgba(181, 127, 26, 0.42); background: #fff7df; color: #9a6200; }
    .dataset-favorite.active svg { fill: currentColor; stroke-width: 1.55; }
    .dataset-empty, .dataset-loading { padding: 12px; border: 1px solid var(--line); border-radius: 7px; background: #fff; color: var(--muted); font-size: 12px; }
    .dataset-loading { border-width: 0; border-top: 1px solid #e3ebe6; border-radius: 0; text-align: center; background: rgba(255,255,255,0.64); }
    .dataset-detail-popover {
      position: absolute;
      top: 52px;
      right: 10px;
      bottom: 10px;
      width: min(410px, calc(100% - 302px));
      z-index: 8;
      display: none;
      min-width: 280px;
      border: 1px solid #d9e5df;
      border-radius: 10px;
      background: rgba(255,255,255,0.97);
      box-shadow: 0 14px 34px rgba(16,24,40,0.16);
      overflow: hidden;
    }
    .dataset-detail-popover.open { display: flex; flex-direction: column; }
    .dataset-detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding: 12px 12px 10px; border-bottom: 1px solid #e3ebe6; }
    .dataset-detail-title { min-width: 0; font-size: 14px; line-height: 1.24; font-weight: 780; color: var(--text); }
    .dataset-detail-id { margin-top: 5px; color: var(--muted); font-size: 11px; line-height: 1.25; overflow-wrap: anywhere; }
    .dataset-detail-close { flex: 0 0 auto; width: 30px; height: 30px; border: 1px solid #dce8e2; border-radius: 8px; background: #fff; color: var(--text); display: grid; place-items: center; font-size: 20px; line-height: 1; cursor: pointer; }
    .dataset-detail-close:hover { background: #f6faf8; }
    .dataset-detail-body { padding: 12px; overflow: auto; display: grid; gap: 11px; min-height: 0; }
    .dataset-detail-thumb { width: 100%; aspect-ratio: 16 / 9; border: 1px solid #e3ebe6; border-radius: 8px; object-fit: cover; background: #eef3f0; }
    .dataset-detail-badges { display: flex; flex-wrap: wrap; gap: 6px; }
    .dataset-detail-badge { border: 1px solid #dce8e2; border-radius: 999px; padding: 3px 7px; background: #f8fbf9; color: #405049; font-size: 10.5px; line-height: 1.15; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .dataset-detail-section { display: grid; gap: 5px; min-width: 0; }
    .dataset-detail-label { color: var(--muted); font-size: 10px; font-weight: 760; text-transform: uppercase; }
    .dataset-detail-text { color: var(--text); font-size: 12px; line-height: 1.45; overflow-wrap: anywhere; }
    .dataset-detail-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
    .dataset-detail-link, .dataset-detail-command {
      min-height: 30px;
      border: 1px solid #dce8e2;
      border-radius: 7px;
      background: #fff;
      color: var(--accent);
      display: grid;
      place-items: center;
      text-decoration: none;
      font-size: 11px;
      font-weight: 720;
      cursor: pointer;
    }
    .dataset-detail-command.primary { color: #fff; background: var(--accent); border-color: var(--accent); }
    .dataset-detail-link:hover, .dataset-detail-command:hover { filter: brightness(0.98); }
    .map-wrap { position: fixed; inset: 0; min-width: 0; min-height: 0; background: #dfe7e2; }
    #map { position: absolute; inset: 0; width: 100%; height: 100%; }
    #map.draw-aoi, #map.draw-polygon { cursor: crosshair; }
    .leaflet-tooltip.measure-label {
      border: 1px solid rgba(22, 115, 77, 0.26);
      border-radius: 6px;
      background: rgba(255,255,255,0.92);
      color: var(--accent);
      box-shadow: 0 2px 10px rgba(16,24,40,0.10);
      font-size: 11px;
      font-weight: 760;
      padding: 2px 6px;
    }
    .mode-chip {
      position: absolute;
      left: 58px;
      bottom: 30px;
      z-index: 1200;
      display: none;
      align-items: center;
      gap: 6px;
      max-width: min(320px, calc(100% - 76px));
      padding: 5px 8px;
      border: 1px solid rgba(215, 223, 218, 0.86);
      border-radius: 6px;
      background: rgba(251, 253, 252, 0.9);
      box-shadow: 0 3px 14px rgba(16, 24, 40, 0.08);
      color: var(--text);
      font-size: 11px;
      backdrop-filter: blur(8px);
    }
    .mode-chip.show { display: flex; }
    .measure-undo-btn {
      position: absolute;
      left: 58px;
      bottom: 62px;
      z-index: 1200;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      min-height: 28px;
      padding: 4px 9px;
      border: 1px solid rgba(22, 115, 77, 0.42);
      border-radius: 7px;
      background: rgba(251, 253, 252, 0.94);
      box-shadow: 0 3px 14px rgba(16, 24, 40, 0.1);
      color: var(--accent);
      font: inherit;
      font-size: 11px;
      font-weight: 720;
      cursor: pointer;
      backdrop-filter: blur(8px);
    }
    .measure-undo-btn:hover:not(:disabled), .measure-undo-btn:focus-visible {
      border-color: var(--accent);
      background: var(--accent-soft);
    }
    .measure-undo-btn:disabled { opacity: 0.46; cursor: not-allowed; }
    .measure-undo-btn svg { width: 15px; height: 15px; stroke: currentColor; fill: none; stroke-width: 1.9; stroke-linecap: round; stroke-linejoin: round; }
    .measure-undo-btn[hidden] { display: none; }
    .simple-scale {
      position: absolute;
      left: 58px;
      bottom: 8px;
      z-index: 1200;
      display: grid;
      gap: 3px;
      color: #17202a;
      font-size: 11px;
      line-height: 1;
      text-shadow: 0 1px 2px rgba(255,255,255,0.95);
      pointer-events: none;
    }
    .scale-label { font-weight: 650; text-align: center; min-width: 34px; }
    .scale-track {
      width: 72px;
      height: 7px;
      border-left: 2px solid #17202a;
      border-right: 2px solid #17202a;
      border-bottom: 2px solid #17202a;
      filter: drop-shadow(0 1px 1px rgba(255,255,255,0.85));
    }
    .right-card { border: 1px solid var(--line); border-radius: 6px; background: #fff; padding: 10px; margin-bottom: 10px; }
    .right-card h2 { margin: 0 0 8px; font-size: 13px; line-height: 1.2; }
    .kv-row { display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 8px; padding: 6px 0; border-top: 1px solid #eef2ef; font-size: 12px; }
    .kv-row:first-child { border-top: 0; padding-top: 0; }
    .kv-key { color: var(--muted); }
    .kv-value { overflow-wrap: anywhere; }
    .legend { display: grid; gap: 5px; font-size: 12px; }
    .legend-row { display: flex; align-items: center; gap: 7px; }
    .swatch { width: 18px; height: 12px; border: 1px solid rgba(0,0,0,0.18); flex: 0 0 auto; }
    .empty-list {
      min-height: 72px;
      display: grid;
      align-content: center;
      justify-items: center;
      text-align: center;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,0.62);
      padding: 12px;
    }
    .bottom {
      position: fixed;
      top: 52px;
      right: 10px;
      bottom: 10px;
      width: min(420px, calc(100vw - 76px));
      max-height: none;
      z-index: 1600;
      min-height: 0;
      display: block;
      overflow: hidden;
      background: rgba(255,255,255,0.94);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      transform: translateX(calc(100% + 18px));
      transition: transform 150ms ease;
      backdrop-filter: blur(12px);
    }
    .bottom.open {
      transform: translateX(0);
    }
    .bottom-section { min-width: 0; height: 100%; overflow: hidden; padding: 12px; display: flex; flex-direction: column; }
    .bottom-title { margin: 0; font-size: 11px; color: var(--muted); font-weight: 760; text-transform: uppercase; }
    .tag { font-size: 11px; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 1px 7px; background: #fff; white-space: nowrap; }
    .quota-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; margin-bottom: 9px; }
    .quota-project, .quota-tier { margin-top: 3px; font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .quota-tier { color: #395247; }
    .quota-link-mini { color: var(--accent); text-decoration: none; font-size: 11px; font-weight: 720; white-space: nowrap; }
    .quota-link-mini:hover { text-decoration: underline; }
    .quota-stat-grid { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
    .quota-stat { border: 1px solid #e3ebe6; border-radius: 999px; background: rgba(255,255,255,0.76); padding: 4px 8px; min-width: 0; display: inline-flex; align-items: baseline; gap: 5px; }
    .quota-stat span { display: block; font-size: 10px; color: var(--muted); line-height: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .quota-stat strong { display: block; font-size: 12px; line-height: 1; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .quota-summary {
      margin-bottom: 10px;
      padding: 7px 8px;
      border-radius: 7px;
      background: #f6faf8;
      border: 1px solid #e3ebe6;
      font-size: 11px;
      font-weight: 650;
      color: #46564f;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .quota-list { display: grid; gap: 9px; flex: 1 1 auto; min-height: 0; overflow: auto; padding-right: 2px; align-content: start; }
    .quota-row {
      border: 1px solid #e0e9e4;
      border-radius: 8px;
      background: rgba(255,255,255,0.86);
      padding: 10px 10px 9px;
      min-width: 0;
      box-shadow: 0 1px 0 rgba(16, 24, 40, 0.03);
    }
    .quota-row.warn { border-color: rgba(160, 90, 0, 0.28); background: #fffaf0; }
    .quota-row-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; min-width: 0; }
    .quota-name { min-width: 0; font-size: 12px; font-weight: 740; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #1f2d27; }
    .quota-usage { flex: 0 0 auto; max-width: 48%; font-size: 12px; font-weight: 760; line-height: 1.15; color: #111827; text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .quota-meter { margin: 9px 0 6px; height: 6px; border-radius: 999px; background: #eef3f0; overflow: hidden; }
    .quota-meter span { display: block; height: 100%; width: 0; border-radius: inherit; background: #111; }
    .quota-row.warn .quota-meter span { background: var(--warn); }
    .quota-row.unknown .quota-meter span { background: #aeb9b3; }
    .quota-row-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-width: 0; font-size: 10px; color: var(--muted); line-height: 1.2; }
    .quota-row-foot span { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .quota-note { font-size: 10px; color: var(--warn); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    @media (max-width: 1120px) {
      .top-meta .hide-medium { display: none; }
    }
    @media (max-width: 760px) {
      :root {
        --rail-left: 6px;
        --rail-pad: 5px;
        --rail-button: 29px;
        --rail-button-half: 14.5px;
        --logo-size: 34px;
        --logo-half: 17px;
      }
      .topbar { right: auto; top: 6px; height: var(--logo-size); }
      .logo-layer { max-width: calc(100vw - 46px); width: calc(100vw - 46px); }
      .logo-layer.collapsed { width: var(--logo-size); max-width: var(--logo-size); }
      .tool-rail { top: 46px; gap: 5px; }
      .left { left: 48px; }
      .left, .right { top: 46px; bottom: 8px; width: min(322px, calc(100vw - 58px)); }
      .data-panel { bottom: auto; max-height: min(520px, calc(100vh - 54px)); width: min(322px, calc(100vw - 58px)); min-width: min(280px, calc(100vw - 58px)); }
      .catalog-shell { grid-template-columns: 1fr; }
      .catalog-sidebar { display: none; }
      .catalog-search-row { grid-template-columns: 1fr; }
      .type-chip-list { justify-content: start; }
      .dataset-list { max-height: min(394px, calc(100vh - 154px)); }
      .data-panel.detail-open .catalog-main { padding-right: 0; }
      .dataset-detail-popover { left: 8px; right: 8px; top: 52px; bottom: 8px; width: auto; min-width: 0; }
      .basemap-panel { left: 48px; top: 64px; width: min(350px, calc(100vw - 58px)); max-height: calc(100vh - 76px); }
      .basemap-editor-grid { grid-template-columns: 1fr; }
      .basemap-field.wide { grid-column: 1; }
      .basemap-advanced-grid { grid-template-columns: 1fr 1fr; }
      .upload-panel { left: 48px; top: 64px; width: min(322px, calc(100vw - 58px)); max-height: calc(100vh - 76px); }
      .upload-row { grid-template-columns: 1fr; }
      .upload-submit { justify-content: center; }
      .bottom { top: 46px; left: 48px; right: 6px; bottom: 8px; width: auto; max-height: none; overflow: hidden; transform: translateX(calc(100% + 12px)); }
      .mode-chip { left: 48px; max-width: calc(100% - 56px); }
      .measure-undo-btn { left: 48px; max-width: calc(100% - 56px); }
      .simple-scale { left: 48px; }
    }
    """


def sample_state(project: str, title: str) -> dict:
    layers: list[dict[str, object]] = []
    catalog, catalog_source = build_catalog(layers, include_remote=False)
    return {
        "title": title,
        "project": project,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "center": [30.25, 120.16],
        "zoom": 10,
        "bounds": [[29.9954, 119.8684], [30.5044, 120.4522]],
        "startDate": "2024-01-01",
        "endDate": datetime.now(timezone.utc).date().isoformat(),
        "cloudPct": 80,
        "layers": layers,
        "catalog": catalog,
        "catalogSource": catalog_source,
        "tasks": [
            {"name": "Generate console", "status": "done"},
            {"name": "Load EE tiles", "status": "waiting"},
            {"name": "Inspect map clicks", "status": "ready"},
        ],
        "quota": sample_quota_state(project),
    }


def empty_state(args: argparse.Namespace) -> dict:
    catalog, catalog_source = build_catalog(
        [],
        include_remote=True,
        catalog_mode=args.catalog_mode,
        refresh_catalog=args.refresh_catalog,
        catalog_cache_hours=args.catalog_cache_hours,
        catalog_fetch_seconds=args.catalog_fetch_seconds,
    )
    return {
        "title": args.title,
        "project": args.project,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "center": [args.lat, args.lon],
        "zoom": args.zoom,
        "bounds": None,
        "startDate": args.start_date,
        "endDate": args.end_date,
        "cloudPct": args.cloud_pct,
        "layers": [],
        "catalog": catalog,
        "catalogSource": catalog_source,
        "tasks": [
            {"name": "Open map console", "status": "done"},
            {"name": "Choose dataset or draw AOI", "status": "ready"},
            {"name": "Add first layer", "status": "ready"},
        ],
    }


def live_state(args: argparse.Namespace) -> dict:
    import ee

    ee.Initialize(project=args.project)
    roi = ee.Geometry.Point([args.lon, args.lat]).buffer(args.buffer_m).bounds()
    bounds_coords = roi.coordinates().getInfo()[0]
    lons = [pt[0] for pt in bounds_coords]
    lats = [pt[1] for pt in bounds_coords]
    bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

    s2 = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(roi)
        .filterDate(args.start_date, args.end_date)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", args.cloud_pct))
        .median()
        .clip(roi)
    )
    rgb = s2.visualize(bands=["B4", "B3", "B2"], min=0, max=3000, gamma=1.15)
    ndvi = s2.normalizedDifference(["B8", "B4"]).rename("NDVI").clip(roi)
    dem = ee.Image("USGS/SRTMGL1_003").select("elevation").unmask(0).clip(roi)
    dynamic_world = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(roi)
        .filterDate(args.start_date, args.end_date)
        .select("label")
        .mode()
        .clip(roi)
    )
    water = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").clip(roi)

    def tile_url(image: object, vis: dict) -> str:
        return image.getMapId(vis)["tile_fetcher"].url_format

    layers = [
        {
                "id": "srtm",
                "name": "SRTM elevation",
                "dataset": "USGS/SRTMGL1_003",
                "type": "ee-raster",
                "shown": True,
                "opacity": 0.58,
                "tileUrl": tile_url(
                    dem,
                    {
                        "min": 0,
                        "max": 600,
                        "palette": ["#0f3b2e", "#3f7d3f", "#c9b96d", "#a2673f", "#f4f1e8"],
                    },
                ),
                "legend": [
                    ["#0f3b2e", "Lower elevation"],
                    ["#c9b96d", "Mid elevation"],
                    ["#f4f1e8", "Higher elevation"],
                ],
                "visParams": {"min": 0, "max": 600, "palette": ["#0f3b2e", "#3f7d3f", "#c9b96d", "#a2673f", "#f4f1e8"]},
                "styleProfile": "terrain",
                "stylePreset": "default",
            },
            {
                "id": "s2-rgb",
                "name": "Sentinel-2 RGB",
                "dataset": "COPERNICUS/S2_SR_HARMONIZED",
                "type": "ee-raster",
                "shown": False,
                "opacity": 0.74,
                "tileUrl": tile_url(rgb, {}),
                "legend": [["#6f9fcf", "Median RGB composite"]],
            },
            {
                "id": "ndvi",
                "name": "NDVI",
                "dataset": "COPERNICUS/S2_SR_HARMONIZED",
                "type": "ee-derived",
                "shown": False,
                "opacity": 0.86,
                "tileUrl": tile_url(
                    ndvi,
                    {
                        "min": 0,
                        "max": 0.8,
                        "palette": ["#2c105c", "#4856a5", "#31a354", "#addd8e", "#f7fcb9"],
                    },
                ),
                "legend": [["#2c105c", "Low"], ["#31a354", "Medium"], ["#f7fcb9", "High"]],
                "visParams": {"min": 0, "max": 0.8, "palette": ["#2c105c", "#4856a5", "#31a354", "#addd8e", "#f7fcb9"]},
                "styleProfile": "ndvi",
                "stylePreset": "default",
            },
            {
                "id": "dynamic-world",
                "name": "Dynamic World mode",
                "dataset": "GOOGLE/DYNAMICWORLD/V1",
                "type": "ee-categorical",
                "shown": False,
                "opacity": 0.72,
                "tileUrl": tile_url(
                    dynamic_world,
                    {
                        "min": 0,
                        "max": 8,
                        "palette": [
                            "#419bdf",
                            "#397d49",
                            "#88b053",
                            "#7a87c6",
                            "#e49635",
                            "#dfc35a",
                            "#c4281b",
                            "#a59b8f",
                            "#b39fe1",
                        ],
                    },
                ),
                "legend": [["#419bdf", "Water"], ["#397d49", "Trees"], ["#e49635", "Built"]],
                "visParams": {"min": 0, "max": 8, "palette": ["#419bdf", "#397d49", "#88b053", "#7a87c6", "#e49635", "#dfc35a", "#c4281b", "#a59b8f", "#b39fe1"]},
                "styleProfile": "categorical",
                "stylePreset": "default",
            },
            {
                "id": "jrc-water",
                "name": "JRC water occurrence",
                "dataset": "JRC/GSW1_4/GlobalSurfaceWater",
                "type": "ee-raster",
                "shown": False,
                "opacity": 0.76,
                "tileUrl": tile_url(water, {"min": 0, "max": 100, "palette": ["#f7fbff", "#6baed6", "#08306b"]}),
                "legend": [["#f7fbff", "Rare"], ["#6baed6", "Seasonal"], ["#08306b", "Persistent"]],
                "visParams": {"min": 0, "max": 100, "palette": ["#f7fbff", "#6baed6", "#08306b"]},
                "styleProfile": "water",
                "stylePreset": "default",
            },
    ]
    if getattr(args, "default_layer", None):
        layer_ids = {layer["id"] for layer in layers}
        if args.default_layer in layer_ids:
            for layer in layers:
                layer["shown"] = layer["id"] == args.default_layer
    catalog, catalog_source = build_catalog(
        layers,
        include_remote=True,
        catalog_mode=args.catalog_mode,
        refresh_catalog=args.refresh_catalog,
        catalog_cache_hours=args.catalog_cache_hours,
        catalog_fetch_seconds=args.catalog_fetch_seconds,
    )
    return {
        "title": args.title,
        "project": args.project,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "center": [args.lat, args.lon],
        "zoom": args.zoom,
        "bounds": bounds,
        "startDate": args.start_date,
        "endDate": args.end_date,
        "cloudPct": args.cloud_pct,
        "layers": layers,
        "catalog": catalog,
        "catalogSource": catalog_source,
        "tasks": [
            {"name": "Authenticate Earth Engine", "status": "done"},
            {"name": "Set default project", "status": "done"},
            {"name": "Generate map console", "status": "done"},
            {"name": "Inspect map clicks", "status": "ready"},
        ],
    }


def ensure_leaflet_js(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    target = root / LEAFLET_LOCAL
    if target.exists() and target.stat().st_size > 100_000:
        return f"./{LEAFLET_LOCAL}"
    try:
        with urllib.request.urlopen(LEAFLET_CDN, timeout=20) as response:
            data = response.read()
        if len(data) > 100_000:
            target.write_bytes(data)
            return f"./{LEAFLET_LOCAL}"
    except Exception:
        pass
    return LEAFLET_CDN


def valid_pmtiles_js(data: bytes) -> bool:
    return len(data) > 10_000 and b"PMTiles" in data and b"leafletRasterLayer" in data


def ensure_pmtiles_js(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    target = root / PMTILES_LOCAL
    if target.exists():
        try:
            if valid_pmtiles_js(target.read_bytes()):
                return f"./{PMTILES_LOCAL}"
        except OSError:
            pass
    try:
        with urllib.request.urlopen(PMTILES_CDN, timeout=20) as response:
            data = response.read()
        if valid_pmtiles_js(data):
            target.write_bytes(data)
            return f"./{PMTILES_LOCAL}"
    except Exception:
        pass
    return PMTILES_CDN


def valid_maplibre_js(data: bytes) -> bool:
    return len(data) > 800_000 and b"maplibregl" in data and b"addProtocol" in data


def valid_maplibre_css(data: bytes) -> bool:
    return len(data) > 50_000 and b".maplibregl-map" in data and b".maplibregl-canvas" in data


def valid_maplibre_leaflet_js(data: bytes) -> bool:
    return len(data) > 7_000 and b"maplibreGL" in data and b"getMaplibreMap" in data


def valid_cog_protocol_js(data: bytes) -> bool:
    return len(data) > 400_000 and b"MaplibreCOGProtocol" in data and b"getCogMetadata" in data


def ensure_preview_asset(root: Path, local_name: str, url: str, validator: Any) -> str:
    root.mkdir(parents=True, exist_ok=True)
    target = root / local_name
    if target.exists():
        try:
            if validator(target.read_bytes()):
                return f"./{local_name}"
        except OSError:
            pass
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
        if validator(data):
            target.write_bytes(data)
            return f"./{local_name}"
    except Exception:
        pass
    return url


def cog_engine_cdn_assets() -> dict[str, str]:
    return {
        "maplibreJs": MAPLIBRE_JS_CDN,
        "maplibreCss": MAPLIBRE_CSS_CDN,
        "leafletAdapterJs": MAPLIBRE_LEAFLET_CDN,
        "cogProtocolJs": COG_PROTOCOL_CDN,
    }


def ensure_cog_engine_assets(root: Path) -> dict[str, str]:
    return {
        "maplibreJs": ensure_preview_asset(root, MAPLIBRE_JS_LOCAL, MAPLIBRE_JS_CDN, valid_maplibre_js),
        "maplibreCss": ensure_preview_asset(root, MAPLIBRE_CSS_LOCAL, MAPLIBRE_CSS_CDN, valid_maplibre_css),
        "leafletAdapterJs": ensure_preview_asset(
            root,
            MAPLIBRE_LEAFLET_LOCAL,
            MAPLIBRE_LEAFLET_CDN,
            valid_maplibre_leaflet_js,
        ),
        "cogProtocolJs": ensure_preview_asset(
            root,
            COG_PROTOCOL_LOCAL,
            COG_PROTOCOL_CDN,
            valid_cog_protocol_js,
        ),
    }


def svg_icon(name: str) -> str:
    icons = {
        "data": '<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5"/><path d="M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>',
        "layers": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 3 8l9 5 9-5-9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 16 9 5 9-5"/></svg>',
        "add": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
        "overlay-add": '<svg class="lucide lucide-copy-plus" viewBox="0 0 24 24" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/><path d="M15 12v6M12 15h6"/></svg>',
        "info": '<svg class="lucide lucide-info" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>',
        "favorite": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3 6.4 20.2 7.5 14 3 9.6l6.2-.9L12 3Z"/></svg>',
        "external": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 7H5v12h12v-3"/><path d="M11 5h8v8"/><path d="m10 14 9-9"/></svg>',
        "inspect": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>',
        "draw-aoi": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="12" height="10" rx="1.5"/><path d="M14 19h3l4-4-3-3-4 4v3Z"/><path d="m17 13 3 3"/></svg>',
        "measure": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 17 13-13 3 3L7 20l-3-3Z"/><path d="m14 6 2 2M11 9l2 2M8 12l2 2"/></svg>',
        "basemap": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="1.8"/><path d="M7 19c2.4-3.4 3.4-6.2 3.1-12"/><path d="M18 7c-3.9 1.1-6.7 3.2-9.2 6.2"/><path d="M13.4 19c.3-3 1.7-5.5 4.1-7.3"/><path d="M7 13h10"/></svg>',
        "quota": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 14a8 8 0 0 1 16 0"/><path d="M12 14l4-5"/><path d="M5 18h14"/><path d="M8 18v2M16 18v2"/></svg>',
        "drive": '<svg class="drive-mark" viewBox="0 0 24 24" aria-hidden="true"><path fill="#4f8f70" d="M8.4 3.1c.3-.5.8-.8 1.4-.8h4.7l6.3 10.9h-5.7L8.4 3.1Z"/><path fill="#5d86b6" d="M20.8 13.2 17.6 19c-.3.5-.8.8-1.4.8H4.8l3.3-6.6h12.7Z"/><path fill="#c2a44f" d="M20.8 13.2h-5.7L8.4 3.1l1.4-.8h4.7l6.3 10.9Z" fill-opacity=".88"/><path fill="#3e7f66" d="M8.4 3.1 2.2 13.8c-.3.5-.3 1.1 0 1.6l2.6 4.4 6.6-11.5-3-5.2Z"/><path fill="#fff" fill-opacity=".9" d="M11.4 8.3 15 13.2H8.1l3.3-4.9Z"/></svg>',
        "upload": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16 16h2.2a3.8 3.8 0 0 0 .6-7.6A6.2 6.2 0 0 0 6.7 7.1 4.4 4.4 0 0 0 7.4 16H9"/><path d="M12 20V10"/><path d="m8.5 13.5 3.5-3.5 3.5 3.5"/></svg>',
        "tasks": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6h12M9 12h12M9 18h12"/><path d="m3 6 1 1 2-2M3 12l1 1 2-2M3 18l1 1 2-2"/></svg>',
        "home": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/></svg>',
        "zoom-layer": '<svg class="lucide lucide-scan" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/></svg>',
        "zoom-in": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6"/><path d="M10 7v6M7 10h6M15 15l5 5"/></svg>',
        "zoom-out": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6"/><path d="M7 10h6M15 15l5 5"/></svg>',
        "grip": '<svg class="lucide lucide-grip-vertical" viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="5" r="1"/><circle cx="15" cy="5" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="19" r="1"/><circle cx="15" cy="19" r="1"/></svg>',
        "language": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h9M8.5 5v2M11.5 5c-.8 4.7-3.5 7.3-7 8.8"/><path d="M5.5 9.5c1.2 2 3.1 3.5 5.5 4.4"/><path d="M14 20l4-9 4 9M15.2 17h5.6"/></svg>',
        "style": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 0 0 0 18h1.5a1.8 1.8 0 0 0 .7-3.4 1.8 1.8 0 0 1 .7-3.4H16a5 5 0 0 0 0-10H12Z"/><circle cx="7.5" cy="10" r="1"/><circle cx="10.5" cy="7.5" r="1"/><circle cx="14" cy="7.5" r="1"/><circle cx="8.5" cy="14" r="1"/></svg>',
        "edit": '<svg class="lucide lucide-pencil" viewBox="0 0 24 24" aria-hidden="true"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.5z"/><path d="m15 5 4 4"/></svg>',
        "up": '<svg class="lucide lucide-chevron-up" viewBox="0 0 24 24" aria-hidden="true"><path d="m18 15-6-6-6 6"/></svg>',
        "down": '<svg class="lucide lucide-chevron-down" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>',
        "undo": '<svg class="lucide lucide-undo-2" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-1"/></svg>',
        "refresh": '<svg class="lucide lucide-refresh-cw" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>',
        "trash": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"/><path d="M9 7V5h6v2"/><path d="M7 7l1 13h8l1-13"/><path d="M10 11v5M14 11v5"/></svg>',
        "close": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    }
    return icons[name]


def render_html(
    state: dict,
    leaflet_src: str,
    pmtiles_src: str = PMTILES_CDN,
    cog_engine_assets: dict[str, str] | None = None,
) -> str:
    safe_title = html.escape(state["title"])
    safe_leaflet_src = html.escape(leaflet_src, quote=True)
    safe_pmtiles_src = html.escape(pmtiles_src, quote=True)
    cog_assets_json = json.dumps(cog_engine_assets or cog_engine_cdn_assets(), ensure_ascii=True).replace("</", "<\\/")
    logo_data_uri = html.escape(easygee_logo_data_uri(), quote=True)
    state_json = json.dumps(state, ensure_ascii=True).replace("</", "<\\/")
    logo_mark = (
        f'<img src="{logo_data_uri}" alt="" loading="eager" decoding="async">'
        if logo_data_uri
        else "EG"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <link rel="icon" href="{logo_data_uri}">
  <style>
{leaflet_css()}
{shell_css()}
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar" aria-label="{safe_title} EE">
      <h1>{safe_title}</h1>
      <button class="logo-layer collapsed" id="active-layer-badge" type="button" title="Active layer" aria-label="Active layer" aria-haspopup="true" aria-expanded="false">
        <span class="mark" aria-hidden="true">{logo_mark}</span>
        <span class="logo-layer-copy"><strong id="active-name"></strong><span id="active-dataset"></span></span>
      </button>
    </header>

    <section class="basemap-source-card" id="basemap-source-card" aria-hidden="true" aria-labelledby="basemap-source-heading">
      <div class="basemap-source-head">
        <div class="basemap-source-kicker" id="basemap-source-heading" data-i18n="source.title">Basemap source</div>
        <button class="icon-btn panel-close" id="basemap-source-close" type="button" title="Close" aria-label="Close" data-i18n-title="tool.close">{svg_icon("close")}</button>
      </div>
      <div class="basemap-source-hero">
        <span class="basemap-source-visual basemap-thumb osm" id="basemap-source-visual" aria-hidden="true"></span>
        <div>
          <div class="basemap-source-name" id="basemap-source-name"></div>
          <div class="basemap-source-service" id="basemap-source-service"></div>
        </div>
      </div>
      <dl class="basemap-source-grid">
        <div class="basemap-source-row"><dt data-i18n="source.provider">Provider</dt><dd id="basemap-source-provider"></dd></div>
        <div class="basemap-source-row" id="basemap-source-date-row" hidden><dt data-i18n="source.date">Imagery date</dt><dd id="basemap-source-date"></dd></div>
        <div class="basemap-source-row"><dt data-i18n="source.engine">Data engine</dt><dd id="basemap-source-engine"></dd></div>
        <div class="basemap-source-row"><dt data-i18n="source.performance">Load timing</dt><dd id="basemap-source-performance"></dd></div>
        <div class="basemap-source-row"><dt data-i18n="source.delivery">Delivery</dt><dd id="basemap-source-delivery"></dd></div>
        <div class="basemap-source-row"><dt data-i18n="source.nativeZoom">Native zoom</dt><dd id="basemap-source-zoom"></dd></div>
        <div class="basemap-source-row"><dt data-i18n="source.attribution">Attribution</dt><dd id="basemap-source-attribution"></dd></div>
      </dl>
      <a class="basemap-source-link" id="basemap-source-link" href="#" target="_blank" rel="noopener noreferrer"><span data-i18n="source.open">Open official source</span>{svg_icon("external")}</a>
    </section>

    <nav class="tool-rail" aria-label="Map tools">
      <button class="icon-btn" id="data-btn" title="Add layers" aria-label="Add layers" data-i18n-title="tool.data">{svg_icon("data")}</button>
      <button class="icon-btn" id="upload-btn" title="Import file" aria-label="Import file" data-i18n-title="tool.upload">{svg_icon("upload")}</button>
      <button class="icon-btn" id="layers-btn" title="Layers" aria-label="Layers" data-i18n-title="tool.layers">{svg_icon("layers")}</button>
      <button class="icon-btn" id="inspector-btn" title="Inspector" aria-label="Inspector" data-i18n-title="tool.inspector">{svg_icon("inspect")}</button>
      <button class="icon-btn" id="draw-aoi-btn" title="Draw AOI" aria-label="Draw AOI" data-i18n-title="tool.drawAoi">{svg_icon("draw-aoi")}</button>
      <button class="icon-btn" id="measure-btn" title="Measure distance" aria-label="Measure distance" aria-pressed="false" data-i18n-title="tool.measure">{svg_icon("measure")}</button>
      <div class="rail-break" aria-hidden="true"></div>
      <button class="icon-btn" id="basemap-btn" title="Basemap" aria-label="Basemap" data-i18n-title="tool.basemap">{svg_icon("basemap")}</button>
      <button class="icon-btn quota-ready" id="quota-btn" title="Quota status" aria-label="Quota status" data-i18n-title="tool.quota">{svg_icon("quota")}<span class="quota-indicator"></span></button>
      <button class="icon-btn" id="drive-btn" title="Google Drive" aria-label="Google Drive" data-i18n-title="tool.drive">{svg_icon("drive")}</button>
      <div class="rail-break" aria-hidden="true"></div>
      <button class="icon-btn" id="home-btn" title="Zoom to AOI" aria-label="Zoom to AOI" data-i18n-title="tool.home">{svg_icon("home")}</button>
      <button class="icon-btn" id="lang-btn" title="Switch language" aria-label="Switch language" data-i18n-title="tool.lang">{svg_icon("language")}<span class="lang-code" id="lang-code">中</span></button>
      <button class="icon-btn wide-only" id="copy-btn" title="Copy project state" aria-label="Copy project state" data-i18n-title="action.copyTitle">C</button>
      <button class="icon-btn wide-only" id="download-btn" title="Download project JSON" aria-label="Download project JSON" data-i18n-title="action.jsonTitle">D</button>
    </nav>

    <aside class="upload-panel" aria-label="Import file">
      <div class="panel-head">
        <div class="upload-title" data-i18n="upload.title">Import File</div>
        <button class="icon-btn panel-close" id="upload-close-btn" title="Close" aria-label="Close" data-i18n-title="tool.close">{svg_icon("close")}</button>
      </div>
      <div class="upload-body">
        <div class="upload-field-label" data-i18n="upload.sourceProjection">Source Projection</div>
        <p class="upload-note" data-i18n="upload.projectionHelp">For .shp files only. ZIP and GPKG auto-detect their projection.</p>
        <select class="upload-select" id="upload-projection" aria-label="Source Projection">
          <option value="EPSG:4326">WGS 84 (EPSG:4326)</option>
          <option value="EPSG:3857">Web Mercator (EPSG:3857)</option>
          <option value="EPSG:4490">CGCS2000 (EPSG:4490)</option>
          <option value="EPSG:32650">WGS 84 / UTM zone 50N (EPSG:32650)</option>
        </select>
        <div class="upload-row">
          <label class="upload-file-button" for="upload-file-input" data-i18n="upload.chooseFile">Choose File</label>
          <div class="upload-file-name" id="upload-file-name" data-i18n="upload.noFile">No file selected</div>
          <button class="upload-submit" id="upload-submit-btn" type="button" disabled>{svg_icon("upload")}<span data-i18n="upload.submit">Upload</span></button>
        </div>
        <input id="upload-file-input" type="file" multiple accept=".shp,.shx,.dbf,.prj,.cpg,.zip,.kml,.kmz,.gpx,.geojson,.json,.csv,.gpkg" hidden>
        <div class="upload-formats" data-i18n="upload.formats">SHP, ZIP, KML, KMZ, GPX, GeoJSON, CSV, GPKG · Max 50 MB each</div>
        <div class="upload-status" id="upload-status" aria-live="polite"></div>
        <div class="upload-list" id="upload-list"></div>
      </div>
    </aside>

    <aside class="panel left data-panel">
      <div class="panel-head">
        <div class="panel-heading">
          <div class="panel-title" data-i18n="panel.data">Add Layers</div>
          <div class="panel-subtitle" data-i18n="panel.dataSubtitle">Search Earth Engine datasets</div>
        </div>
        <button class="icon-btn panel-close mobile-only" data-close-panel="data-panel" title="Close" aria-label="Close" data-i18n-title="tool.close">{svg_icon("close")}</button>
      </div>
      <div class="panel-body">
        <div class="catalog-shell">
          <aside class="catalog-sidebar" aria-label="Catalog filters">
            <input class="search" id="category-search" placeholder="Filter options..." data-i18n-placeholder="placeholder.filterOptions">
            <div class="catalog-filter-title" data-i18n="catalog.categories">Categories</div>
            <div class="category-list" id="category-list"></div>
          </aside>
          <section class="catalog-main">
            <div class="catalog-search-row">
              <input class="search" id="dataset-search" placeholder="Search layers by name, category, or id" data-i18n-placeholder="placeholder.searchDatasets">
              <div class="type-chip-list" id="type-chip-list"></div>
            </div>
            <div class="dataset-toolbar">
              <span class="tag" id="catalog-count"></span>
              <span class="dataset-hint" data-i18n="data.addHint">Click + to process nearby and add</span>
            </div>
            <div class="dataset-list" id="dataset-list"></div>
            <aside class="dataset-detail-popover" id="dataset-detail" aria-live="polite"></aside>
          </section>
        </div>
      </div>
    </aside>

    <aside class="basemap-panel">
      <div class="panel-head">
        <div class="panel-heading">
          <div class="panel-title" data-i18n="panel.basemap">Basemap</div>
          <div class="panel-subtitle" id="basemap-current"></div>
        </div>
        <button class="icon-btn panel-close mobile-only" id="basemap-close-btn" title="Close" aria-label="Close" data-i18n-title="tool.close">{svg_icon("close")}</button>
      </div>
      <div class="basemap-body">
        <div class="basemap-toolbar">
          <button class="basemap-add" id="basemap-add-btn" type="button">{svg_icon("add")}<span data-i18n="basemap.addCustom">Add custom basemap</span></button>
          <span class="basemap-custom-count" id="basemap-custom-count"></span>
        </div>
        <section class="basemap-provider-auth" id="tianditu-auth">
          <button class="basemap-provider-auth-toggle" id="tianditu-auth-toggle" type="button" aria-expanded="false" aria-controls="tianditu-auth-body"><span class="basemap-provider-auth-title"><span class="basemap-provider-auth-mark" aria-hidden="true">TK</span><span data-i18n="basemap.tiandituKey">Tianditu access key</span></span><span class="basemap-provider-auth-state" id="tianditu-auth-state"></span></button>
          <div class="basemap-provider-auth-body" id="tianditu-auth-body" hidden>
            <div class="basemap-provider-auth-summary" id="tianditu-auth-summary" hidden>
              <span class="basemap-provider-auth-summary-copy" data-i18n="basemap.tiandituKeyConfiguredHint">Ready for Tianditu basemaps.</span>
              <span class="basemap-provider-auth-actions"><button class="basemap-form-button" id="tianditu-token-persistence" type="button" hidden></button><button class="basemap-form-button" id="tianditu-token-change" type="button" data-i18n="basemap.tiandituKeyChange">Change key</button></span>
            </div>
            <div class="basemap-provider-auth-editor" id="tianditu-auth-editor">
              <div class="basemap-provider-auth-row">
                <input class="basemap-input code" id="tianditu-token" type="password" maxlength="256" autocomplete="off" spellcheck="false" data-i18n-placeholder="basemap.tiandituKeyPlaceholder">
                <button class="basemap-form-button primary" id="tianditu-token-apply" type="button" data-i18n="basemap.tiandituKeyApply">Apply</button>
              </div>
              <label class="basemap-provider-auth-remember"><input id="tianditu-token-remember" type="checkbox"><span data-i18n="basemap.tiandituKeyRememberDevice">Remember on this device (Windows encrypted)</span></label>
              <div class="basemap-provider-auth-help"><span data-i18n="basemap.tiandituKeyHelp">Stored only for this browser tab.</span> <a href="https://cloudcenter.tianditu.gov.cn/center/development/myApp" target="_blank" rel="noopener noreferrer" data-i18n="basemap.tiandituKeyLink">Get a key</a></div>
            </div>
          </div>
        </section>
        <form class="basemap-editor" id="basemap-editor" hidden novalidate>
          <div class="basemap-editor-head">
            <div>
              <div class="basemap-editor-title" id="basemap-editor-title" data-i18n="basemap.editorAdd">New basemap</div>
              <div class="basemap-editor-kind" data-i18n="basemap.editorHint">Local profile configuration</div>
            </div>
            <button class="icon-btn panel-close" id="basemap-editor-close" type="button" title="Close" aria-label="Close" data-i18n-title="tool.close">{svg_icon("close")}</button>
          </div>
          <div class="basemap-editor-grid">
            <label class="basemap-field wide"><span data-i18n="basemap.fieldName">Name</span><input class="basemap-input" id="basemap-form-name" maxlength="120" autocomplete="off" required></label>
            <label class="basemap-field"><span data-i18n="basemap.fieldType">Service type</span><select class="basemap-select" id="basemap-form-type">
              <option value="xyz">XYZ</option><option value="tms">TMS</option><option value="arcgis">ArcGIS REST</option><option value="wms">WMS</option><option value="wmts">WMTS</option><option value="pmtiles">PMTiles (raster)</option><option value="cog">COG (MapLibre WebGL)</option>
            </select></label>
            <label class="basemap-field"><span data-i18n="basemap.fieldProvider">Provider</span><input class="basemap-input" id="basemap-form-provider" maxlength="240" autocomplete="off"></label>
            <label class="basemap-field wide"><span data-i18n="basemap.fieldUrl">Service URL / tile template</span><input class="basemap-input code" id="basemap-form-url" maxlength="4096" inputmode="url" autocomplete="off" required data-i18n-placeholder="basemap.urlPlaceholder"></label>
            <label class="basemap-field basemap-type-field wide" data-basemap-types="xyz,tms"><span data-i18n="basemap.fieldSubdomains">Subdomains</span><input class="basemap-input code" id="basemap-form-subdomains" maxlength="120" autocomplete="off" placeholder="a,b,c"></label>
            <label class="basemap-field basemap-type-field wide" data-basemap-types="wms,wmts"><span data-i18n="basemap.fieldLayers">Layer name</span><input class="basemap-input code" id="basemap-form-layers" maxlength="500" autocomplete="off"></label>
            <label class="basemap-field basemap-type-field" data-basemap-types="wms,wmts"><span data-i18n="basemap.fieldStyles">Style</span><input class="basemap-input code" id="basemap-form-styles" maxlength="500" autocomplete="off"></label>
            <label class="basemap-field basemap-type-field" data-basemap-types="wms"><span data-i18n="basemap.fieldVersion">WMS version</span><select class="basemap-select" id="basemap-form-version"><option value="1.3.0">1.3.0</option><option value="1.1.1">1.1.1</option></select></label>
            <label class="basemap-field basemap-type-field" data-basemap-types="wmts"><span data-i18n="basemap.fieldMatrixSet">Tile matrix set</span><input class="basemap-input code" id="basemap-form-matrix-set" maxlength="160" autocomplete="off" value="GoogleMapsCompatible"></label>
            <label class="basemap-field basemap-type-field" data-basemap-types="wmts"><span data-i18n="basemap.fieldMatrixPrefix">Matrix prefix</span><input class="basemap-input code" id="basemap-form-matrix-prefix" maxlength="160" autocomplete="off" data-i18n-placeholder="basemap.matrixPrefixPlaceholder"></label>
            <label class="basemap-field basemap-type-field" data-basemap-types="wms,wmts"><span data-i18n="basemap.fieldFormat">Image format</span><select class="basemap-select" id="basemap-form-format"><option value="image/png">PNG</option><option value="image/jpeg">JPEG</option><option value="image/webp">WebP</option></select></label>
            <details>
              <summary data-i18n="basemap.advanced">Attribution and zoom levels</summary>
              <div class="basemap-advanced-grid">
                <label class="basemap-field" style="grid-column:1/-1"><span data-i18n="basemap.fieldAttribution">Attribution</span><input class="basemap-input" id="basemap-form-attribution" maxlength="1000" autocomplete="off"></label>
                <label class="basemap-field" style="grid-column:1/-1"><span data-i18n="basemap.fieldSourceUrl">Official source URL</span><input class="basemap-input code" id="basemap-form-source-url" maxlength="4096" inputmode="url" autocomplete="off"></label>
                <label class="basemap-field"><span data-i18n="basemap.fieldMinZoom">Min zoom</span><input class="basemap-input" id="basemap-form-min-zoom" type="number" min="0" max="24" value="0"></label>
                <label class="basemap-field"><span data-i18n="basemap.fieldMaxZoom">Max zoom</span><input class="basemap-input" id="basemap-form-max-zoom" type="number" min="0" max="24" value="19"></label>
                <label class="basemap-field"><span data-i18n="basemap.fieldNativeZoom">Native max</span><input class="basemap-input" id="basemap-form-native-zoom" type="number" min="0" max="24" value="19"></label>
              </div>
            </details>
            <label class="basemap-default-toggle"><input id="basemap-form-default" type="checkbox"><span data-i18n="basemap.setDefaultAfterSave">Set as default after saving</span></label>
          </div>
          <div class="basemap-form-status" id="basemap-form-status" aria-live="polite"></div>
          <div class="basemap-form-actions">
            <button class="basemap-form-button" id="basemap-test-btn" type="button">{svg_icon("refresh")}<span data-i18n="basemap.test">Test current view</span></button>
            <button class="basemap-form-button primary" id="basemap-save-btn" type="submit" disabled><span data-i18n="basemap.save">Save basemap</span></button>
          </div>
        </form>
        <div class="basemap-list" id="basemap-list"></div>
      </div>
    </aside>

    <aside class="panel left layers-panel">
      <div class="panel-head"><div class="panel-title" data-i18n="panel.layers">Layers</div><span class="tag" id="layer-count"></span><button class="icon-btn panel-close mobile-only" data-close-panel="layers-panel" title="Close" aria-label="Close" data-i18n-title="tool.close">{svg_icon("close")}</button></div>
      <div class="panel-body">
        <div class="section-title" data-i18n="section.layerStack">Layer Stack</div>
        <div class="layer-list" id="layer-list"></div>
      </div>
    </aside>

    <main class="map-wrap">
      <div id="map"></div>
      <div class="mode-chip" id="mode-chip"></div>
      <button class="measure-undo-btn" id="measure-undo-btn" type="button" hidden disabled title="Undo last step" aria-label="Undo last step" data-i18n-title="tool.measureUndo">{svg_icon("undo")}<span data-i18n="tool.measureUndo">Undo last step</span></button>
      <div class="simple-scale" id="simple-scale"><div class="scale-label" id="scale-label"></div><div class="scale-track" id="scale-track"></div></div>
    </main>

    <aside class="panel right">
      <div class="panel-head"><div class="panel-title" data-i18n="panel.inspector">Inspector</div><span class="tag" id="click-state">idle</span><button class="icon-btn panel-close mobile-only" data-close-panel="right" title="Close" aria-label="Close" data-i18n-title="tool.close">{svg_icon("close")}</button></div>
      <div class="panel-body">
        <section class="right-card">
          <h2 data-i18n="card.mapClick">Map Click</h2>
          <div class="kv">
            <div class="kv-row"><div class="kv-key" data-i18n="key.latitude">Latitude</div><div class="kv-value" id="lat-value">-</div></div>
            <div class="kv-row"><div class="kv-key" data-i18n="key.longitude">Longitude</div><div class="kv-value" id="lon-value">-</div></div>
            <div class="kv-row"><div class="kv-key" data-i18n="key.zoom">Zoom</div><div class="kv-value" id="zoom-value">-</div></div>
          </div>
        </section>
        <section class="right-card">
          <h2 data-i18n="card.activeLayer">Active Layer</h2>
          <div class="kv">
            <div class="kv-row"><div class="kv-key" data-i18n="key.name">Name</div><div class="kv-value" id="detail-name">-</div></div>
            <div class="kv-row"><div class="kv-key" data-i18n="key.dataset">Dataset</div><div class="kv-value" id="detail-dataset">-</div></div>
            <div class="kv-row"><div class="kv-key" data-i18n="key.type">Type</div><div class="kv-value" id="detail-type">-</div></div>
            <div class="kv-row"><div class="kv-key" data-i18n="key.recipe">Recipe</div><div class="kv-value" id="detail-recipe">-</div></div>
            <div class="kv-row"><div class="kv-key" data-i18n="key.opacity">Opacity</div><div class="kv-value" id="detail-opacity">-</div></div>
          </div>
        </section>
        <section class="right-card">
          <h2 data-i18n="card.legend">Legend</h2>
          <div class="legend" id="legend"></div>
        </section>
        <section class="right-card">
          <h2 data-i18n="card.tasks">Tasks</h2>
          <div class="task-list" id="task-list"></div>
        </section>
      </div>
    </aside>

    <footer class="bottom">
      <section class="bottom-section">
        <div class="quota-head">
          <div>
            <div class="bottom-title" data-i18n="bottom.project">Quotas</div>
            <div class="quota-project" id="quota-project"></div>
            <div class="quota-tier" id="quota-tier"></div>
          </div>
          <a class="quota-link-mini" id="quota-link" target="_blank" rel="noreferrer" data-i18n="link.quota">Console</a>
        </div>
        <div class="quota-stat-grid">
          <div class="quota-stat"><span data-i18n="quota.items">Quota items</span><strong id="quota-count">0</strong></div>
          <div class="quota-stat"><span data-i18n="quota.measured">Measured</span><strong id="quota-used-summary">-</strong></div>
          <div class="quota-stat"><span data-i18n="quota.alerts">Alerts</span><strong id="quota-remaining-summary">-</strong></div>
        </div>
        <div class="quota-summary" id="quota-summary"></div>
        <div class="quota-list" id="quota-list"></div>
      </section>
    </footer>
  </div>

  <script src="{safe_leaflet_src}" crossorigin=""></script>
  <script src="{safe_pmtiles_src}" crossorigin=""></script>
  <script>
    const STATE = {state_json};
    const COG_ENGINE_ASSETS = {cog_assets_json};
    STATE.layers = Array.isArray(STATE.layers) ? STATE.layers : [];
    STATE.layerOrder = Array.isArray(STATE.layerOrder) ? STATE.layerOrder.map(value => String(value)) : [];
    STATE.catalog = Array.isArray(STATE.catalog) ? STATE.catalog : [];
    STATE.tasks = Array.isArray(STATE.tasks) ? STATE.tasks : [];
    STATE.uploads = Array.isArray(STATE.uploads) ? STATE.uploads : [];
    const logLines = [];
    const layerRegistry = new Map();
    const layerRefreshTokens = new Map();
    const I18N = {{
      zh: {{
        "tool.data": "添加图层",
        "tool.upload": "上传地图数据",
        "tool.layers": "图层",
        "tool.layersMeasurementReady": "图层：测距结果已加入",
        "tool.layersMeasurePrompt": "图层：测距结果会自动加入",
        "tool.inspector": "查看器",
        "tool.drawAoi": "绘制 AOI",
        "tool.measure": "测距",
        "tool.measureActive": "测距已开启 · 结果自动加入图层",
        "tool.measureUndo": "撤回上一步",
        "tool.clearMeasurements": "清除测距",
        "tool.basemap": "底图",
        "tool.quota": "配额状态",
        "tool.drive": "Google 云盘",
        "tool.driveRecent": "打开最近的 Drive 导出",
        "tool.driveRoot": "打开 Google 云盘",
        "tool.home": "回到初始视图",
        "tool.zoomIn": "放大",
        "tool.zoomOut": "缩小",
        "tool.lang": "切换语言",
        "tool.close": "关闭",
        "upload.title": "导入文件",
        "upload.sourceProjection": "源投影",
        "upload.projectionHelp": "仅用于 .shp 文件。ZIP 和 GPKG 会自动识别投影。",
        "upload.chooseFile": "选择文件",
        "upload.noFile": "未选择任何文件",
        "upload.submit": "上传",
        "upload.formats": "SHP, ZIP, KML, KMZ, GPX, GeoJSON, CSV, GPKG · 单个文件最大 50 MB",
        "upload.ready": "已选择 :count 个文件",
        "upload.saving": "正在保存上传文件",
        "upload.saved": "已上传 :count 个文件，并加入图层",
        "upload.savedPartial": "已上传 :total 个文件，其中 :added 个已加入图层",
        "upload.failed": "上传失败：:message",
        "upload.tooLarge": ":name 超过 50 MB",
        "upload.empty": "上传记录会显示在这里，并同步给 agent。",
        "upload.agentReady": "agent 可处理",
        "upload.layerAdded": "已加入图层",
        "upload.notRenderable": "未加入图层：缺少可渲染几何",
        "upload.remove": "移除上传记录",
        "tool.styleLayer": "设置图层样式",
        "tool.zoomToLayer": "缩放到图层",
        "tool.refreshLayer": "刷新图层",
        "tool.dragLayer": "拖动排序",
        "tool.removeLayer": "移除图层",
        "tool.basemapSource": "查看地图来源",
        "tool.clearAoi": "清除 AOI",
        "panel.data": "添加图层",
        "panel.dataSubtitle": "搜索与添加 Earth Engine 数据集",
        "panel.basemap": "底图",
        "source.title": "底图来源",
        "source.provider": "提供方",
        "source.date": "影像日期",
        "source.engine": "数据引擎",
        "source.performance": "加载性能",
        "source.performanceIdle": "尚未采样",
        "source.performanceLoading": "等待首屏…",
        "source.performanceSettling": "首屏 :first · 收尾中…",
        "source.performanceReady": "首屏 :first · 完成 :ready",
        "source.performanceFailed": "加载失败",
        "source.delivery": "传输",
        "source.deliveryIdle": "尚无本次加载数据",
        "source.deliveryLoading": ":cache · 统计中…",
        "source.cacheCold": "会话冷启",
        "source.cacheWarm": "会话热启",
        "source.cacheUnknown": "会话缓存未知",
        "source.renderedBlocks": ":count 个绘制块",
        "source.sourceRequests": ":count 次源请求",
        "source.networkRestricted": "网络统计受限",
        "source.nativeZoom": "原生层级",
        "source.nativeZoomValue": "Z0–Z:zoom",
        "source.attribution": "版权说明",
        "source.open": "查看官方数据源",
        "source.trigger": "查看当前底图来源",
        "panel.layers": "图层",
        "panel.inspector": "查看器",
        "section.layerStack": "图层栈",
        "section.operationalLayers": "数据与叠加图层",
        "section.layerReorderHint": "拖动排序",
        "section.primaryBasemap": "主底图",
        "section.primaryBasemapHint": "固定在最底层",
        "placeholder.searchDatasets": "按名称、类别或 ID 搜索图层",
        "placeholder.filterOptions": "筛选类别...",
        "catalog.categories": "分类（当前类型）",
        "catalog.all": "全部",
        "catalog.typeAll": "全部",
        "catalog.typeImageCollection": "影像集合",
        "catalog.typeImage": "影像",
        "catalog.typeTable": "矢量/表",
        "catalog.typeOther": "其他",
        "catalog.favorites": "收藏夹",
        "catalog.favoriteChip": "收藏 (:count)",
        "catalog.sourceOfficial": "官方",
        "catalog.sourceCommunity": "社区",
        "catalog.sourceCurated": "精选",
        "card.mapClick": "地图点击",
        "card.activeLayer": "当前图层",
        "card.legend": "图例",
        "card.tasks": "任务",
        "key.latitude": "纬度",
        "key.longitude": "经度",
        "key.zoom": "缩放",
        "key.name": "名称",
        "key.dataset": "数据集",
        "key.type": "类型",
        "key.recipe": "配方",
        "key.opacity": "不透明度",
        "label.opacity": "不透明度",
        "label.color": "颜色",
        "label.palette": "色带",
        "layers.empty": "还没有图层。点“添加图层”搜索 GEE 数据集。",
        "layers.emptyOperational": "还没有数据或叠加图层。",
        "tasks.empty": "暂无任务。Agent 发起的导出和后台处理会显示在这里。",
        "task.destination": "目的地",
        "task.folder": "文件夹",
        "task.prefix": "文件前缀",
        "task.id": "任务 ID",
        "task.params": "参数",
        "task.driveSearch": "Drive 搜索",
        "task.createdAt": "创建于",
        "layer.none": "未选择图层",
        "measurements.layerName": "测距",
        "measurements.layerDataset": "已保存测距标记（:count 条）",
        "measurements.legend": "测距线",
        "measurements.count": "数量",
        "measurements.summary": ":count 条，合计 :total",
        "badge.noLayer": "EasyGEE 地图",
        "badge.basemap": "底图：:basemap",
        "badge.basemapSource": "底图来源：:source",
        "bottom.project": "配额",
        "link.quota": "控制台",
        "action.copy": "复制",
        "action.json": "JSON",
        "action.copyTitle": "复制项目状态",
        "action.jsonTitle": "下载项目 JSON",
        "pill.project": "项目：:project",
        "pill.aoi": "AOI：:lat, :lon",
        "pill.layers": ":count 个图层",
        "pill.layersWithBasemap": ":count 个图层 · 1 个底图",
        "pill.datasets": ":count 个数据集",
        "pill.datasetMatches": ":shown/:total 个数据集",
        "pill.datasetLoaded": "已加载 :shown / 共 :matches",
        "pill.datasetLoadedFiltered": "已加载 :shown / 命中 :matches / 全部 :total",
        "data.loadingMore": "继续加载中",
        "data.ready": "可直接添加 · :count 个图层",
        "data.catalogItem": "可处理目录项",
        "data.addHint": "点击 + 后本地处理并加入地图",
        "data.noResults": "没有匹配的数据集",
        "data.noFavorites": "还没有收藏的数据集。点星标加入收藏夹。",
        "data.addTitle": "加入地图",
        "data.favoriteTitle": "收藏数据集",
        "data.unfavoriteTitle": "取消收藏",
        "data.openCatalog": "打开数据目录",
        "data.openSample": "示例代码",
        "data.addFromDetail": "加入地图",
        "data.copyId": "复制 ID",
        "data.copyContext": "复制上下文",
        "data.contextCopied": "数据集上下文已复制",
        "data.previewRecipe": "默认预览",
        "data.detailSource": "来源",
        "data.detailType": "类型",
        "data.detailProvider": "提供方",
        "data.detailLicense": "许可",
        "data.detailDates": "时间范围",
        "data.detailDescription": "简介",
        "data.detailTags": "标签",
        "data.detailNoDescription": "暂无详细简介。请打开数据目录或示例代码核对字段、许可和使用方式。",
        "data.detailCopied": "数据集 ID 已复制",
        "data.attrTime": "时间",
        "data.attrSpan": "跨度",
        "data.attrResolution": "分辨率",
        "data.attrType": "类型",
        "data.attrYear": ":count 年",
        "data.attrMonth": ":count 月",
        "data.processing": "正在处理并生成图层",
        "data.generated": "已可视化",
        "data.failed": "生成失败",
        "state.idle": "待命",
        "state.clicked": "已点击",
        "mode.datasetAdded": "已加入 :count 个图层",
        "mode.datasetBuilding": "正在生成 :dataset",
        "mode.datasetNeedsBuild": "需要用本地预览服务生成图层",
        "mode.datasetFailed": "生成失败：:message",
        "mode.favoriteAdded": "已收藏 :dataset",
        "mode.favoriteRemoved": "已取消收藏 :dataset",
        "mode.quotaReady": "配额：:summary",
        "mode.aoiStart": "AOI：选择第一个角",
        "mode.aoiCorner": "AOI：选择对角",
        "mode.aoiDone": "AOI 已更新",
        "mode.aoiOff": "AOI 绘制已关闭",
        "mode.aoiTooSmall": "AOI 太小",
        "mode.polygonStart": "多边形 AOI：点击添加顶点，双击或按 Enter 完成",
        "mode.polygonVertex": "多边形 AOI：已添加 :count 个顶点",
        "mode.polygonTooSmall": "多边形 AOI 至少需要 3 个顶点",
        "mode.ndviBuilding": "正在提取当前 AOI 的 NDVI",
        "mode.ndviDone": "NDVI 均值 :mean，像元 :count",
        "mode.ndviNoAoi": "请先绘制 AOI 再提取 NDVI",
        "mode.ndviFailed": "NDVI 提取失败：:message",
        "mode.driveExportBuilding": "正在发起 Drive 导出",
        "mode.driveExportDone": "Drive 导出任务已创建：:task",
        "mode.driveExportFailed": "Drive 导出失败：:message",
        "mode.styleBuilding": "正在更新图层样式：:layer",
        "mode.styleApplied": "图层样式已更新：:layer",
        "mode.styleFailed": "样式更新失败：:message",
        "mode.layerZooming": "正在缩放到图层：:layer",
        "mode.layerZoomed": "已缩放到图层：:layer",
        "mode.layerReordered": "图层顺序已更新",
        "mode.layerExtentUnavailable": "无法获取图层范围：:layer",
        "quota.project": "项目：:project",
        "quota.tier": "用量层级：:tier",
        "quota.tierInferred": "用量层级：:tier",
        "quota.tierUnknown": "用量层级：待连接",
        "quota.items": "额度项",
        "quota.summaryLiveUsage": "实时用量可用",
        "quota.summaryLiveLimit": "实时额度可用；用量未接通",
        "quota.summaryDefault": "默认额度；剩余未知",
        "quota.summaryEmpty": "配额数据不可用",
        "quota.issueCloudLogin": "需登录 Google Cloud CLI",
        "quota.issueCloudQuotasApi": "需启用 Cloud Quotas API",
        "quota.issueQuotaPermission": "缺少 Cloud Quotas 权限",
        "quota.issueMonitoringPermission": "缺少 Monitoring 用量权限",
        "quota.issueQuotaNetwork": "gcloud 配额组件/网络异常",
        "quota.issueLiveUnavailable": "实时配额不可用",
        "quota.total": "总额",
        "quota.used": "已用",
        "quota.remaining": "剩余",
        "quota.measured": "可量化",
        "quota.alerts": "预警",
        "quota.noAlerts": "0 项",
        "quota.alertCount": ":count 项",
        "quota.measuredOfTotal": ":count/:total",
        "quota.maxUsed": "最高用量 :percent",
        "quota.usedOfTotal": ":used/:total (:percent)",
        "quota.usedUnlimited": ":used/无限",
        "quota.totalOnly": "总额 :total",
        "quota.remainingValue": "剩余 :remaining",
        "quota.remainingUnlimited": "剩余 无限",
        "quota.unlimited": "无限",
        "quota.usageMissing": "用量未接通",
        "quota.usageUnavailable": "用量未提供",
        "quota.noUsageYet": "暂无用量",
        "quota.limitOnlyState": "仅额度",
        "quota.unlimitedState": "无限额度",
        "quota.noUsageState": "未产生",
        "quota.okState": "余量正常",
        "quota.warnState": "接近上限",
        "quota.notAvailable": "不可用",
        "quota.unknown": "未知",
        "quota.usageRequired": "需要 Cloud Monitoring 用量权限",
        "mode.basemap": "底图：:basemap",
        "mode.tiandituKeyRequired": "请先在底图面板配置天地图 Key",
        "mode.tiandituKeySaved": "天地图 Key 已应用到当前标签页",
        "mode.tiandituKeyRemembered": "天地图 Key 已用 Windows 加密保存在本机",
        "mode.tiandituKeySessionOnly": "已移除本机副本，当前标签页仍可使用",
        "mode.tiandituKeyRememberFailed": "当前标签页可继续使用，本机加密保存失败",
        "mode.basemapOverlayAdded": "已叠加到图层：:basemap",
        "mode.measureStart": "测距：点击两个点",
        "mode.measureOff": "测距已关闭",
        "mode.measureEndpoint": "测距：选择终点",
        "mode.distance": "距离：:distance",
        "mode.measureSaved": "测量已加入图层：:distance（共 :count 条，均值 :mean）",
        "mode.measureUndoDraft": "已撤回上一个测量点",
        "mode.measureUndoSaved": "已撤回上一条测量：:distance",
        "mode.measureUndoEmpty": "暂无可撤回的测量",
        "mode.measureCleared": "测距标记已清除",
        "basemap.osm": "OpenStreetMap",
        "basemap.osmNote": "道路与标注",
        "basemap.light": "浅色",
        "basemap.lightNote": "突出分析图层",
        "basemap.dark": "深色",
        "basemap.darkNote": "夜间对比",
        "basemap.voyager": "彩色",
        "basemap.voyagerNote": "清爽道路与地物",
        "basemap.topo": "地形",
        "basemap.topoNote": "等高线与地貌，高层级自动回退",
        "basemap.topoCoverage": "Esri World Topographic Map · 全球原生覆盖至 z13",
        "basemap.imagery": "影像",
        "basemap.imageryNote": "Esri 全球影像",
        "basemap.esriClarity": "Esri 清晰影像",
        "basemap.esriClarityNote": "清晰度优先的备用影像",
        "basemap.tiandituVector": "天地图·矢量",
        "basemap.tiandituVectorNote": "国家级矢量底图与中文注记",
        "basemap.tiandituImagery": "天地图·影像",
        "basemap.tiandituImageryNote": "国家级卫星影像与中文注记",
        "basemap.tiandituTerrain": "天地图·地形",
        "basemap.tiandituTerrainNote": "地形晕渲与中文注记",
        "basemap.tiandituKey": "天地图访问 Key",
        "basemap.tiandituKeyMissing": "未配置",
        "basemap.tiandituKeyReady": "已配置 · 本次会话",
        "basemap.tiandituKeyReadyDevice": "已配置 · 本机加密",
        "basemap.tiandituKeyConfiguredHint": "已应用，可直接使用天地图底图。",
        "basemap.tiandituKeyChange": "更换 Key",
        "basemap.tiandituKeyPlaceholder": "输入 tk（不会进入项目状态）",
        "basemap.tiandituKeyApply": "应用",
        "basemap.tiandituKeyHelp": "仅保存在当前浏览器标签页，关闭后自动清除。",
        "basemap.tiandituKeyRememberDevice": "记住此设备（Windows 加密）",
        "basemap.tiandituKeyRemember": "记住此设备",
        "basemap.tiandituKeyForget": "仅本次会话",
        "basemap.tiandituKeyLink": "申请 Key",
        "basemap.tiandituKeyInvalid": "Key 不能为空，且不能包含空格或 URL 分隔符",
        "basemap.addCustom": "自定义底图",
        "basemap.addOverlay": "叠加到图层",
        "basemap.overlayInLayers": "已在图层中",
        "basemap.primaryRole": "主底图",
        "basemap.overlayRole": "地图叠加",
        "basemap.customCount": ":count 个自定义",
        "basemap.editorAdd": "新建底图",
        "basemap.editorEdit": "编辑底图",
        "basemap.editorHint": "保存到本机用户档案",
        "basemap.fieldName": "名称",
        "basemap.fieldType": "服务类型",
        "basemap.fieldProvider": "提供方",
        "basemap.fieldUrl": "服务地址 / 瓦片模板",
        "basemap.urlPlaceholder": "https://.../{{z}}/{{x}}/{{y}}.png",
        "basemap.fieldSubdomains": "子域名",
        "basemap.fieldLayers": "图层名称",
        "basemap.fieldStyles": "样式",
        "basemap.fieldVersion": "WMS 版本",
        "basemap.fieldMatrixSet": "瓦片矩阵集",
        "basemap.fieldMatrixPrefix": "矩阵前缀",
        "basemap.matrixPrefixPlaceholder": "例如 EPSG:3857:",
        "basemap.fieldFormat": "图像格式",
        "basemap.advanced": "版权与缩放层级",
        "basemap.fieldAttribution": "版权说明",
        "basemap.fieldSourceUrl": "官方来源地址",
        "basemap.fieldMinZoom": "最小层级",
        "basemap.fieldMaxZoom": "最大层级",
        "basemap.fieldNativeZoom": "原生最大层级",
        "basemap.setDefaultAfterSave": "保存后设为默认底图",
        "basemap.test": "测试当前视图",
        "basemap.save": "保存底图",
        "basemap.testing": "正在测试当前视图的瓦片…",
        "basemap.pmtilesInspecting": "正在读取 PMTiles 归档索引…",
        "basemap.testPassed": "连接成功，可以保存",
        "basemap.testFailed": "连接失败：:message",
        "basemap.nameRequired": "请填写底图名称",
        "basemap.urlRequired": "请填写服务地址",
        "basemap.urlInvalid": "服务地址必须是有效的 HTTP(S) 地址",
        "basemap.urlCredentialsBlocked": "地址中含有 Key、Token 或账号信息；请改用专用凭据配置，避免明文写入项目状态",
        "basemap.pmtilesUnavailable": "PMTiles 数据引擎没有加载，请刷新页面后重试",
        "basemap.pmtilesInspectFailed": "无法读取 PMTiles 归档索引，请检查跨域与 HTTP Range 支持",
        "basemap.pmtilesRasterOnly": "当前归档是矢量 PMTiles；底图暂时只支持栅格 PMTiles",
        "basemap.pmtilesOutsideView": "当前视图不在 PMTiles 覆盖范围内",
        "basemap.pmtilesZoomOutside": "当前缩放层级不在 PMTiles 原生层级范围内",
        "basemap.pmtilesNoTile": "当前视图范围内没有实际栅格瓦片",
        "basemap.cogLoading": "正在按需加载 MapLibre COG 引擎…",
        "basemap.cogInspecting": "正在读取 COG 元数据与字节范围…",
        "basemap.cogUnavailable": "MapLibre COG 引擎加载失败，请检查本地资源或网络",
        "basemap.cogInspectFailed": "无法读取 COG，请检查跨域、HTTP Range 与文件结构",
        "basemap.cogWebMercatorOnly": "当前轻量 COG 通道要求 EPSG:3857（Web Mercator）",
        "basemap.cogOutsideView": "当前视图不在 COG 覆盖范围内",
        "basemap.cogFit": "已定位到 COG 覆盖范围，正在验证可见影像…",
        "basemap.layersRequired": "WMS/WMTS 需要填写图层名称",
        "basemap.matrixRequired": "WMTS 需要填写瓦片矩阵集",
        "basemap.testFirst": "请先测试连接",
        "basemap.tileTimeout": "等待瓦片超时，请确认当前视图位于服务覆盖范围内",
        "basemap.tileFailed": "当前视图没有加载到有效瓦片",
        "basemap.defaultTitle": "设为默认底图",
        "basemap.defaultCurrent": "默认底图",
        "basemap.edit": "编辑自定义底图",
        "basemap.moveUp": "上移",
        "basemap.moveDown": "下移",
        "basemap.remove": "删除自定义底图",
        "basemap.removeConfirm": "删除自定义底图“:name”？",
        "basemap.customNote": "自定义 :type · :provider",
        "basemap.saved": "自定义底图已保存：:name",
        "basemap.updated": "自定义底图已更新：:name",
        "basemap.removed": "自定义底图已删除：:name",
        "basemap.defaultChanged": "默认底图已设为：:name",
        "log.loaded": "EasyGEE 地图控制台已加载",
        "log.uploadSaved": "上传文件已保存：:file",
        "log.datasetSelected": "已选择数据集 :dataset",
        "log.datasetAdded": "已加入数据集：:dataset",
        "log.datasetBuilding": "正在生成数据集图层：:dataset",
        "log.datasetFailed": "数据集生成失败：:dataset",
        "log.catalogLoaded": "目录已刷新：:count 个数据集",
        "log.catalogOpened": "已打开数据目录：:dataset",
        "log.favoriteAdded": "已收藏数据集：:dataset",
        "log.favoriteRemoved": "已取消收藏数据集：:dataset",
        "log.layerOn": "已显示图层：:layer",
        "log.layerOff": "已隐藏图层：:layer",
        "log.layerRemoved": "已移除图层：:layer",
        "log.layerRefreshed": "已刷新图层：:layer",
        "log.layerReordered": "已调整图层顺序：:layer",
        "log.layerStyled": "已更新图层样式：:layer",
        "log.layerStyleFailed": "图层样式更新失败：:layer",
        "log.layerZoomed": "已缩放到图层：:layer",
        "log.layerExtentUnavailable": "无法获取图层范围：:layer",
        "log.home": "已回到研究区",
        "log.basemap": "底图已切换为 :basemap",
        "log.basemapOverlayAdded": "底图已叠加到图层：:basemap",
        "log.aoiOn": "AOI 绘制模式已开启",
        "log.aoiOff": "AOI 绘制模式已关闭",
        "log.aoiDrawn": "AOI 已更新：:bounds",
        "log.aoiRestored": "已从本地状态恢复 AOI",
        "log.aoiCleared": "AOI 已清除",
        "log.ndviStarted": "已开始 NDVI 提取",
        "log.ndviDone": "NDVI 摘要已生成：均值 :mean",
        "log.ndviFailed": "NDVI 提取失败",
        "log.driveExportStarted": "正在发起 Drive 导出",
        "log.driveExportDone": "Drive 导出任务已加入：:task",
        "log.driveExportFailed": "Drive 导出失败",
        "log.driveOpened": "已打开 Drive：:target",
        "log.taskAdded": "任务已记录：:task",
        "log.measureOn": "测距模式已开启",
        "log.measureOff": "测距模式已关闭",
        "log.measured": "测得距离：:distance",
        "log.measureSummary": "测量统计：共 :count 条，均值 :mean",
        "log.measureUndo": "已撤回测量：:distance",
        "log.measureCleared": "测距标记已清除：:count 条",
        "log.copied": "项目状态已复制",
        "log.clipboardUnavailable": "剪贴板不可用",
        "log.downloaded": "项目 JSON 已下载",
        "log.clicked": "点击坐标 :lat, :lon",
        "log.quotaOpened": "已打开配额详情",
        "log.language": "界面语言已切换为中文"
      }},
      en: {{
        "tool.data": "Add layers",
        "tool.upload": "Import file",
        "tool.layers": "Layers",
        "tool.layersMeasurementReady": "Layers: measurement added",
        "tool.layersMeasurePrompt": "Layers: measurement results will be added",
        "tool.inspector": "Inspector",
        "tool.drawAoi": "Draw AOI",
        "tool.measure": "Measure distance",
        "tool.measureActive": "Measure on · results are added to Layers",
        "tool.measureUndo": "Undo last step",
        "tool.clearMeasurements": "Clear measurements",
        "tool.basemap": "Basemap",
        "tool.quota": "Quota status",
        "tool.drive": "Google Drive",
        "tool.driveRecent": "Open latest Drive export",
        "tool.driveRoot": "Open Google Drive",
        "tool.home": "Home view",
        "tool.zoomIn": "Zoom in",
        "tool.zoomOut": "Zoom out",
        "tool.lang": "Switch language",
        "tool.close": "Close",
        "upload.title": "Import File",
        "upload.sourceProjection": "Source Projection",
        "upload.projectionHelp": "For .shp files only. ZIP and GPKG auto-detect their projection.",
        "upload.chooseFile": "Choose File",
        "upload.noFile": "No file selected",
        "upload.submit": "Upload",
        "upload.formats": "SHP, ZIP, KML, KMZ, GPX, GeoJSON, CSV, GPKG · Max 50 MB each",
        "upload.ready": ":count file(s) selected",
        "upload.saving": "Saving uploaded file(s)",
        "upload.saved": "Uploaded :count file(s) and added them to layers",
        "upload.savedPartial": "Uploaded :total file(s); :added added to layers",
        "upload.failed": "Upload failed: :message",
        "upload.tooLarge": ":name exceeds 50 MB",
        "upload.empty": "Upload records appear here and sync to agents.",
        "upload.agentReady": "agent-readable",
        "upload.layerAdded": "Added to layers",
        "upload.notRenderable": "Not added to layers: no renderable geometry",
        "upload.remove": "Remove upload record",
        "tool.styleLayer": "Style layer",
        "tool.zoomToLayer": "Zoom to layer",
        "tool.refreshLayer": "Refresh layer",
        "tool.dragLayer": "Drag to reorder",
        "tool.removeLayer": "Remove layer",
        "tool.basemapSource": "View map source",
        "tool.clearAoi": "Clear AOI",
        "panel.data": "Add Layers",
        "panel.dataSubtitle": "Search and add Earth Engine datasets",
        "panel.basemap": "Basemap",
        "source.title": "Basemap source",
        "source.provider": "Provider",
        "source.date": "Imagery date",
        "source.engine": "Data engine",
        "source.performance": "Load timing",
        "source.performanceIdle": "Not sampled yet",
        "source.performanceLoading": "Waiting for first render…",
        "source.performanceSettling": "First :first · settling…",
        "source.performanceReady": "First :first · ready :ready",
        "source.performanceFailed": "Load failed",
        "source.delivery": "Delivery",
        "source.deliveryIdle": "No activation data yet",
        "source.deliveryLoading": ":cache · measuring…",
        "source.cacheCold": "Cold session",
        "source.cacheWarm": "Warm session",
        "source.cacheUnknown": "Session cache unknown",
        "source.renderedBlocks": ":count rendered blocks",
        "source.sourceRequests": ":count source requests",
        "source.networkRestricted": "Network timing restricted",
        "source.nativeZoom": "Native zoom",
        "source.nativeZoomValue": "Z0–Z:zoom",
        "source.attribution": "Attribution",
        "source.open": "Open official source",
        "source.trigger": "View current basemap source",
        "panel.layers": "Layers",
        "panel.inspector": "Inspector",
        "section.layerStack": "Layer Stack",
        "section.operationalLayers": "Data and overlays",
        "section.layerReorderHint": "Drag to reorder",
        "section.primaryBasemap": "Primary basemap",
        "section.primaryBasemapHint": "Pinned to the bottom",
        "placeholder.searchDatasets": "Search layers by name, category, or id",
        "placeholder.filterOptions": "Filter options...",
        "catalog.categories": "Categories (current type)",
        "catalog.all": "All",
        "catalog.typeAll": "All",
        "catalog.typeImageCollection": "Image collections",
        "catalog.typeImage": "Images",
        "catalog.typeTable": "Vectors / tables",
        "catalog.typeOther": "Other",
        "catalog.favorites": "Favorites",
        "catalog.favoriteChip": "Favorites (:count)",
        "catalog.sourceOfficial": "Official",
        "catalog.sourceCommunity": "Community",
        "catalog.sourceCurated": "Curated",
        "card.mapClick": "Map Click",
        "card.activeLayer": "Active Layer",
        "card.legend": "Legend",
        "card.tasks": "Tasks",
        "key.latitude": "Latitude",
        "key.longitude": "Longitude",
        "key.zoom": "Zoom",
        "key.name": "Name",
        "key.dataset": "Dataset",
        "key.type": "Type",
        "key.recipe": "Recipe",
        "key.opacity": "Opacity",
        "label.opacity": "Opacity",
        "label.color": "Color",
        "label.palette": "Palette",
        "layers.empty": "No layers yet. Use Add layers to search the GEE catalog.",
        "layers.emptyOperational": "No data or overlay layers yet.",
        "tasks.empty": "No tasks yet. Agent-started exports and background processing appear here.",
        "task.destination": "Destination",
        "task.folder": "Folder",
        "task.prefix": "File prefix",
        "task.id": "Task ID",
        "task.params": "Params",
        "task.driveSearch": "Drive search",
        "task.createdAt": "Created",
        "layer.none": "No layer selected",
        "measurements.layerName": "Measurements",
        "measurements.layerDataset": "Saved distance markers (:count)",
        "measurements.legend": "Measurement line",
        "measurements.count": "Count",
        "measurements.summary": ":count total, :total",
        "badge.noLayer": "EasyGEE map",
        "badge.basemap": "Basemap: :basemap",
        "badge.basemapSource": "Basemap source: :source",
        "bottom.project": "Quotas",
        "link.quota": "Console",
        "action.copy": "Copy",
        "action.json": "JSON",
        "action.copyTitle": "Copy project state",
        "action.jsonTitle": "Download project JSON",
        "pill.project": "Project: :project",
        "pill.aoi": "AOI: :lat, :lon",
        "pill.layers": ":count layers",
        "pill.layersWithBasemap": ":count layers · 1 basemap",
        "pill.datasets": ":count datasets",
        "pill.datasetMatches": ":shown/:total datasets",
        "pill.datasetLoaded": "Loaded :shown / :matches",
        "pill.datasetLoadedFiltered": "Loaded :shown / :matches matches / :total total",
        "data.loadingMore": "Loading more",
        "data.ready": "Ready to add · :count layers",
        "data.catalogItem": "processable catalog item",
        "data.addHint": "Click + to process nearby and add",
        "data.noResults": "No matching datasets",
        "data.noFavorites": "No favorite datasets yet. Click a star to save one.",
        "data.addTitle": "Add to map",
        "data.favoriteTitle": "Favorite dataset",
        "data.unfavoriteTitle": "Remove favorite",
        "data.openCatalog": "Open catalog page",
        "data.openSample": "Sample code",
        "data.addFromDetail": "Add to map",
        "data.copyId": "Copy ID",
        "data.copyContext": "Copy context",
        "data.contextCopied": "Dataset context copied",
        "data.previewRecipe": "Default preview",
        "data.detailSource": "Source",
        "data.detailType": "Type",
        "data.detailProvider": "Provider",
        "data.detailLicense": "License",
        "data.detailDates": "Date range",
        "data.detailDescription": "Description",
        "data.detailTags": "Tags",
        "data.detailNoDescription": "No detailed description is available. Open the catalog page or sample code to verify fields, license, and usage.",
        "data.detailCopied": "Dataset ID copied",
        "data.attrTime": "Time",
        "data.attrSpan": "Span",
        "data.attrResolution": "Resolution",
        "data.attrType": "Type",
        "data.attrYear": ":count yr",
        "data.attrMonth": ":count mo",
        "data.processing": "Processing and generating layer",
        "data.generated": "Visualized",
        "data.failed": "Generation failed",
        "state.idle": "idle",
        "state.clicked": "clicked",
        "mode.datasetAdded": "Added :count layers",
        "mode.datasetBuilding": "Generating :dataset",
        "mode.datasetNeedsBuild": "Use the local preview service to generate the layer",
        "mode.datasetFailed": "Generation failed: :message",
        "mode.favoriteAdded": "Favorited :dataset",
        "mode.favoriteRemoved": "Removed favorite :dataset",
        "mode.quotaReady": "Quota: :summary",
        "mode.aoiStart": "AOI: choose first corner",
        "mode.aoiCorner": "AOI: choose opposite corner",
        "mode.aoiDone": "AOI updated",
        "mode.aoiOff": "AOI draw off",
        "mode.aoiTooSmall": "AOI too small",
        "mode.polygonStart": "Polygon AOI: add vertices, double-click or Enter to finish",
        "mode.polygonVertex": "Polygon AOI: :count vertices",
        "mode.polygonTooSmall": "Polygon AOI needs at least 3 vertices",
        "mode.ndviBuilding": "Extracting NDVI for current AOI",
        "mode.ndviDone": "NDVI mean :mean from :count pixels",
        "mode.ndviNoAoi": "Draw an AOI before extracting NDVI",
        "mode.ndviFailed": "NDVI failed: :message",
        "mode.driveExportBuilding": "Starting Drive export",
        "mode.driveExportDone": "Drive export task created: :task",
        "mode.driveExportFailed": "Drive export failed: :message",
        "mode.styleBuilding": "Updating layer style: :layer",
        "mode.styleApplied": "Layer style updated: :layer",
        "mode.styleFailed": "Style update failed: :message",
        "mode.layerZooming": "Zooming to layer: :layer",
        "mode.layerZoomed": "Zoomed to layer: :layer",
        "mode.layerReordered": "Layer order updated",
        "mode.layerExtentUnavailable": "Layer extent unavailable: :layer",
        "quota.project": "Project: :project",
        "quota.tier": "Usage tier: :tier",
        "quota.tierInferred": "Usage tier: :tier",
        "quota.tierUnknown": "Usage tier: pending",
        "quota.items": "Quota items",
        "quota.summaryLiveUsage": "Live usage available",
        "quota.summaryLiveLimit": "Live limits available; usage unavailable",
        "quota.summaryDefault": "Default limits; remaining unknown",
        "quota.summaryEmpty": "Quota data unavailable",
        "quota.issueCloudLogin": "Google Cloud CLI login required",
        "quota.issueCloudQuotasApi": "Cloud Quotas API must be enabled",
        "quota.issueQuotaPermission": "Cloud Quotas permission missing",
        "quota.issueMonitoringPermission": "Monitoring usage permission missing",
        "quota.issueQuotaNetwork": "gcloud quota component/network issue",
        "quota.issueLiveUnavailable": "Live quota unavailable",
        "quota.total": "Total",
        "quota.used": "Used",
        "quota.remaining": "Remaining",
        "quota.measured": "Measured",
        "quota.alerts": "Alerts",
        "quota.noAlerts": "0 items",
        "quota.alertCount": ":count items",
        "quota.measuredOfTotal": ":count/:total",
        "quota.maxUsed": "Max used :percent",
        "quota.usedOfTotal": ":used/:total (:percent)",
        "quota.usedUnlimited": ":used/unlimited",
        "quota.totalOnly": "Total :total",
        "quota.remainingValue": "Remaining :remaining",
        "quota.remainingUnlimited": "Remaining unlimited",
        "quota.unlimited": "Unlimited",
        "quota.usageMissing": "Usage unavailable",
        "quota.usageUnavailable": "Usage not provided",
        "quota.noUsageYet": "No usage yet",
        "quota.limitOnlyState": "Limit only",
        "quota.unlimitedState": "Unlimited",
        "quota.noUsageState": "No usage",
        "quota.okState": "Healthy",
        "quota.warnState": "Near limit",
        "quota.notAvailable": "N/A",
        "quota.unknown": "Unknown",
        "quota.usageRequired": "Cloud Monitoring usage permission required",
        "mode.basemap": "Basemap: :basemap",
        "mode.tiandituKeyRequired": "Configure a Tianditu key in the basemap panel first",
        "mode.tiandituKeySaved": "Tianditu key applied to this browser tab",
        "mode.tiandituKeyRemembered": "Tianditu key saved locally with Windows encryption",
        "mode.tiandituKeySessionOnly": "Local copy removed; this browser tab can still use the key",
        "mode.tiandituKeyRememberFailed": "This tab can keep using the key, but encrypted local storage failed",
        "mode.basemapOverlayAdded": "Added as overlay: :basemap",
        "mode.measureStart": "Measure: click two points",
        "mode.measureOff": "Measure off",
        "mode.measureEndpoint": "Measure: choose endpoint",
        "mode.distance": "Distance: :distance",
        "mode.measureSaved": "Measurement added to Layers: :distance (:count total, mean :mean)",
        "mode.measureUndoDraft": "Undid the last measurement point",
        "mode.measureUndoSaved": "Undid the last measurement: :distance",
        "mode.measureUndoEmpty": "No measurement to undo",
        "mode.measureCleared": "Measurement markers cleared",
        "basemap.osm": "OpenStreetMap",
        "basemap.osmNote": "Roads and labels",
        "basemap.light": "Light",
        "basemap.lightNote": "Clean overlay base",
        "basemap.dark": "Dark",
        "basemap.darkNote": "High contrast",
        "basemap.voyager": "Voyager",
        "basemap.voyagerNote": "Balanced roads and places",
        "basemap.topo": "Topo",
        "basemap.topoNote": "Terrain and contours with zoom fallback",
        "basemap.topoCoverage": "Esri World Topographic Map · global native coverage through z13",
        "basemap.imagery": "Imagery",
        "basemap.imageryNote": "Esri global imagery",
        "basemap.esriClarity": "Esri Clarity Imagery",
        "basemap.esriClarityNote": "Clarity-first archive imagery",
        "basemap.tiandituVector": "Tianditu Vector",
        "basemap.tiandituVectorNote": "National vector map with Chinese labels",
        "basemap.tiandituImagery": "Tianditu Imagery",
        "basemap.tiandituImageryNote": "National satellite imagery with Chinese labels",
        "basemap.tiandituTerrain": "Tianditu Terrain",
        "basemap.tiandituTerrainNote": "Terrain shading with Chinese labels",
        "basemap.tiandituKey": "Tianditu access key",
        "basemap.tiandituKeyMissing": "Not configured",
        "basemap.tiandituKeyReady": "Configured · this session",
        "basemap.tiandituKeyReadyDevice": "Configured · encrypted locally",
        "basemap.tiandituKeyConfiguredHint": "Ready for Tianditu basemaps.",
        "basemap.tiandituKeyChange": "Change key",
        "basemap.tiandituKeyPlaceholder": "Enter tk (excluded from project state)",
        "basemap.tiandituKeyApply": "Apply",
        "basemap.tiandituKeyHelp": "Stored only for this browser tab and cleared when it closes.",
        "basemap.tiandituKeyRememberDevice": "Remember on this device (Windows encrypted)",
        "basemap.tiandituKeyRemember": "Remember device",
        "basemap.tiandituKeyForget": "This session only",
        "basemap.tiandituKeyLink": "Get a key",
        "basemap.tiandituKeyInvalid": "The key cannot be empty or contain spaces or URL delimiters",
        "basemap.addCustom": "Custom basemap",
        "basemap.addOverlay": "Add as overlay",
        "basemap.overlayInLayers": "Already in layers",
        "basemap.primaryRole": "Primary basemap",
        "basemap.overlayRole": "Map overlay",
        "basemap.customCount": ":count custom",
        "basemap.editorAdd": "New basemap",
        "basemap.editorEdit": "Edit basemap",
        "basemap.editorHint": "Saved in the local user profile",
        "basemap.fieldName": "Name",
        "basemap.fieldType": "Service type",
        "basemap.fieldProvider": "Provider",
        "basemap.fieldUrl": "Service URL / tile template",
        "basemap.urlPlaceholder": "https://.../{{z}}/{{x}}/{{y}}.png",
        "basemap.fieldSubdomains": "Subdomains",
        "basemap.fieldLayers": "Layer name",
        "basemap.fieldStyles": "Style",
        "basemap.fieldVersion": "WMS version",
        "basemap.fieldMatrixSet": "Tile matrix set",
        "basemap.fieldMatrixPrefix": "Matrix prefix",
        "basemap.matrixPrefixPlaceholder": "For example EPSG:3857:",
        "basemap.fieldFormat": "Image format",
        "basemap.advanced": "Attribution and zoom levels",
        "basemap.fieldAttribution": "Attribution",
        "basemap.fieldSourceUrl": "Official source URL",
        "basemap.fieldMinZoom": "Min zoom",
        "basemap.fieldMaxZoom": "Max zoom",
        "basemap.fieldNativeZoom": "Native max",
        "basemap.setDefaultAfterSave": "Set as default after saving",
        "basemap.test": "Test current view",
        "basemap.save": "Save basemap",
        "basemap.testing": "Testing tiles for the current view…",
        "basemap.pmtilesInspecting": "Reading the PMTiles archive index…",
        "basemap.testPassed": "Connection passed; ready to save",
        "basemap.testFailed": "Connection failed: :message",
        "basemap.nameRequired": "Enter a basemap name",
        "basemap.urlRequired": "Enter a service URL",
        "basemap.urlInvalid": "The service URL must be a valid HTTP(S) address",
        "basemap.urlCredentialsBlocked": "The URL contains a key, token, or account credentials; use a dedicated credential field to keep secrets out of project state",
        "basemap.pmtilesUnavailable": "The PMTiles engine did not load; reload the page and try again",
        "basemap.pmtilesInspectFailed": "Could not read the PMTiles archive index; check CORS and HTTP Range support",
        "basemap.pmtilesRasterOnly": "This is a vector PMTiles archive; basemaps currently support raster PMTiles only",
        "basemap.pmtilesOutsideView": "The current view is outside the PMTiles coverage",
        "basemap.pmtilesZoomOutside": "The current zoom is outside the native PMTiles zoom range",
        "basemap.pmtilesNoTile": "No raster tile exists inside the current view",
        "basemap.cogLoading": "Loading the MapLibre COG engine on demand…",
        "basemap.cogInspecting": "Reading COG metadata and byte ranges…",
        "basemap.cogUnavailable": "The MapLibre COG engine failed to load; check local assets or network access",
        "basemap.cogInspectFailed": "Could not read the COG; check CORS, HTTP Range, and file structure",
        "basemap.cogWebMercatorOnly": "This lightweight COG path requires EPSG:3857 (Web Mercator)",
        "basemap.cogOutsideView": "The current view is outside the COG coverage",
        "basemap.cogFit": "Moved to the COG extent; validating visible imagery…",
        "basemap.layersRequired": "WMS/WMTS requires a layer name",
        "basemap.matrixRequired": "WMTS requires a tile matrix set",
        "basemap.testFirst": "Test the connection first",
        "basemap.tileTimeout": "Tile test timed out; check whether the current view is inside the service coverage",
        "basemap.tileFailed": "No valid tile loaded for the current view",
        "basemap.defaultTitle": "Set as default basemap",
        "basemap.defaultCurrent": "Default basemap",
        "basemap.edit": "Edit custom basemap",
        "basemap.moveUp": "Move up",
        "basemap.moveDown": "Move down",
        "basemap.remove": "Delete custom basemap",
        "basemap.removeConfirm": "Delete custom basemap “:name”?",
        "basemap.customNote": "Custom :type · :provider",
        "basemap.saved": "Custom basemap saved: :name",
        "basemap.updated": "Custom basemap updated: :name",
        "basemap.removed": "Custom basemap deleted: :name",
        "basemap.defaultChanged": "Default basemap set to: :name",
        "log.loaded": "EasyGEE Map Console loaded",
        "log.uploadSaved": "Upload saved: :file",
        "log.datasetSelected": "Selected dataset :dataset",
        "log.datasetAdded": "Added dataset: :dataset",
        "log.datasetBuilding": "Generating dataset layer: :dataset",
        "log.datasetFailed": "Dataset generation failed: :dataset",
        "log.catalogLoaded": "Catalog refreshed: :count datasets",
        "log.catalogOpened": "Opened catalog page: :dataset",
        "log.favoriteAdded": "Favorited dataset: :dataset",
        "log.favoriteRemoved": "Removed favorite dataset: :dataset",
        "log.layerOn": "Layer on: :layer",
        "log.layerOff": "Layer off: :layer",
        "log.layerRemoved": "Removed layer: :layer",
        "log.layerRefreshed": "Refreshed layer: :layer",
        "log.layerReordered": "Reordered layer: :layer",
        "log.layerStyled": "Updated layer style: :layer",
        "log.layerStyleFailed": "Layer style update failed: :layer",
        "log.layerZoomed": "Zoomed to layer: :layer",
        "log.layerExtentUnavailable": "Layer extent unavailable: :layer",
        "log.home": "Zoomed to AOI",
        "log.basemap": "Basemap switched to :basemap",
        "log.basemapOverlayAdded": "Basemap added as overlay: :basemap",
        "log.aoiOn": "AOI draw mode on",
        "log.aoiOff": "AOI draw mode off",
        "log.aoiDrawn": "AOI updated: :bounds",
        "log.aoiRestored": "AOI restored from local state",
        "log.aoiCleared": "AOI cleared",
        "log.ndviStarted": "NDVI extraction started",
        "log.ndviDone": "NDVI summary ready: mean :mean",
        "log.ndviFailed": "NDVI extraction failed",
        "log.driveExportStarted": "Starting Drive export",
        "log.driveExportDone": "Drive export task added: :task",
        "log.driveExportFailed": "Drive export failed",
        "log.driveOpened": "Opened Drive: :target",
        "log.taskAdded": "Task recorded: :task",
        "log.measureOn": "Measure mode on",
        "log.measureOff": "Measure mode off",
        "log.measured": "Measured distance: :distance",
        "log.measureSummary": "Measurements: :count total, mean :mean",
        "log.measureUndo": "Measurement undone: :distance",
        "log.measureCleared": "Measurement markers cleared: :count",
        "log.copied": "Project state copied",
        "log.clipboardUnavailable": "Clipboard write unavailable",
        "log.downloaded": "Project JSON downloaded",
        "log.clicked": "Clicked :lat, :lon",
        "log.quotaOpened": "Quota details opened",
        "log.language": "Interface language switched to English"
      }}
    }};
    let activeLayerId = STATE.layers.find(layer => layer.shown)?.id || STATE.layers[0]?.id || null;
    let draggedLayerId = null;
    let operationalLayerOrder = [...STATE.layerOrder];
    let operationalMapOrderDirty = true;
    let activeDatasetId = null;
    let activeBadgeTimer = null;
    let basemapSourceOpen = false;
    let basemapSourceDetailId = null;
    let currentLang = localStorage.getItem('easygee-lang') || 'zh';
    const TIANDITU_TOKEN_STORAGE_KEY = 'easygee-tianditu-tk';
    let tiandituToken = readTiandituToken();
    let tiandituTokenRemembered = false;
    let tiandituCredentialSupported = false;
    let tiandituKeyEditing = false;
    let restoredProfileView = null;
    let restoredProfileActiveLayerId = null;
    let pendingProfileLayers = [];
    let clickStateKey = 'state.idle';
    let currentModeKey = null;
    let quotaFocus = false;
    let catalogTypeFilter = 'all';
    let catalogCategoryFilter = 'all';
    let catalogFavoriteFilter = false;
    let catalogCategoryQuery = '';
    let catalogListItems = [];
    let catalogRenderedCount = 0;
    const CATALOG_RENDER_BATCH = 120;
    const FAVORITES_STORAGE_KEY = 'easygee-dataset-favorites';
    const PROJECT_STORAGE_SOURCE = String((STATE.project && STATE.project !== 'YOUR_EE_PROJECT') ? STATE.project : (STATE.title || 'default'));
    const PROJECT_STORAGE_ID = PROJECT_STORAGE_SOURCE.replace(/[^a-z0-9_-]+/gi, '-').slice(0, 80) || 'default';
    const LEGACY_PROJECT_STORAGE_ID = String(STATE.project || STATE.title || 'default').replace(/[^a-z0-9_-]+/gi, '-').slice(0, 80) || 'default';
    const AOI_STORAGE_KEYS = [...new Set([`easygee-aoi:${{PROJECT_STORAGE_ID}}`, `easygee-aoi:${{LEGACY_PROJECT_STORAGE_ID}}`])];
    const MEASUREMENTS_STORAGE_KEYS = [...new Set([`easygee-measurements:${{PROJECT_STORAGE_ID}}`, `easygee-measurements:${{LEGACY_PROJECT_STORAGE_ID}}`])];
    const TASKS_STORAGE_KEYS = [...new Set([`easygee-tasks:${{PROJECT_STORAGE_ID}}`, `easygee-tasks:${{LEGACY_PROJECT_STORAGE_ID}}`])];
    const UPLOADS_STORAGE_KEYS = [...new Set([`easygee-uploads:${{PROJECT_STORAGE_ID}}`, `easygee-uploads:${{LEGACY_PROJECT_STORAGE_ID}}`])];
    const UPLOAD_CAPABILITIES = {{
      endpoint: '/api/uploads',
      maxBytes: 50 * 1024 * 1024,
      acceptedExtensions: ['.shp', '.shx', '.dbf', '.prj', '.cpg', '.zip', '.kml', '.kmz', '.gpx', '.geojson', '.json', '.csv', '.gpkg'],
      formats: ['SHP', 'ZIP', 'KML', 'KMZ', 'GPX', 'GeoJSON', 'CSV', 'GPKG'],
      agentVisible: true,
      stateKey: 'uploads',
    }};
    const AGENT_PROTOCOL_VERSION = 5;
    const SESSION_SYNC_INTERVAL_MS = 1200;
    const SESSION_ACTION_POLL_MS = 900;
    const ACTION_SET_AOI_STYLE = 'setAoiStyle';
    const ACTION_UPDATE_LAYER_STYLE = 'updateLayerStyle';
    const AOI_LAYER_ID = '__easygee_aoi__';
    const MEASUREMENTS_LAYER_ID = '__easygee_measurements__';
    const PRIMARY_BASEMAP_LAYER_ID = '__easygee_primary_basemap__';
    const PRIMARY_BASEMAP_PANE = 'easygeePrimaryBasemapPane';
    const DEFAULT_AOI_STYLE = {{ color: '#d23b3b', fillColor: '#d23b3b', opacity: 1, fillOpacity: 0.08, weight: 2, shown: true }};
    const DEFAULT_MEASUREMENTS_STYLE = {{ color: '#16734d', opacity: 1, weight: 3, shown: true }};
    const VIS_PRESETS = {{
      ndvi: [
        {{ id: 'default', label: 'NDVI purple-green', visParams: {{ min: 0, max: 0.8, palette: ['#2c105c', '#4856a5', '#31a354', '#addd8e', '#f7fcb9'] }}, legend: [['#2c105c', 'Low'], ['#31a354', 'Medium'], ['#f7fcb9', 'High']] }},
        {{ id: 'natural-green', label: 'NDVI brown-green', visParams: {{ min: -0.2, max: 0.9, palette: ['#8c510a', '#d8b365', '#f6e8c3', '#5ab469', '#006837'] }}, legend: [['#8c510a', 'Bare/low'], ['#f6e8c3', 'Moderate'], ['#006837', 'High']] }},
        {{ id: 'soft-green', label: 'NDVI soft green', visParams: {{ min: 0, max: 0.8, palette: ['#f7fcf5', '#c7e9c0', '#74c476', '#238b45', '#00441b'] }}, legend: [['#f7fcf5', 'Low'], ['#74c476', 'Medium'], ['#00441b', 'High']] }},
        {{ id: 'contrast', label: 'NDVI high contrast', visParams: {{ min: -0.2, max: 1, palette: ['#440154', '#31688e', '#35b779', '#fde725'] }}, legend: [['#440154', 'Low'], ['#35b779', 'Medium'], ['#fde725', 'High']] }},
      ],
      water: [
        {{ id: 'default', label: 'Water blue', visParams: {{ min: 0, max: 100, palette: ['#f7fbff', '#6baed6', '#08306b'] }}, legend: [['#f7fbff', 'Rare'], ['#6baed6', 'Seasonal'], ['#08306b', 'Persistent']] }},
        {{ id: 'deep-blue', label: 'Water deep blue', visParams: {{ min: 0, max: 100, palette: ['#f0f9ff', '#38bdf8', '#075985'] }}, legend: [['#f0f9ff', 'Rare'], ['#38bdf8', 'Seasonal'], ['#075985', 'Persistent']] }},
        {{ id: 'cyan', label: 'Water cyan', visParams: {{ min: 0, max: 100, palette: ['#ecfeff', '#67e8f9', '#0e7490'] }}, legend: [['#ecfeff', 'Rare'], ['#67e8f9', 'Seasonal'], ['#0e7490', 'Persistent']] }},
        {{ id: 'single-blue', label: 'Water mask blue', visParams: {{ min: 1, max: 100, palette: ['#bfdbfe', '#1d4ed8'] }}, legend: [['#bfdbfe', 'Low occurrence'], ['#1d4ed8', 'High occurrence']] }},
      ],
      temperature: [
        {{ id: 'default', label: 'Temperature blue-red', visParams: {{ min: 0, max: 45, palette: ['#313695', '#74add1', '#ffffbf', '#f46d43', '#a50026'] }}, legend: [['#313695', 'Cool'], ['#ffffbf', 'Moderate'], ['#a50026', 'Hot']] }},
        {{ id: 'fire', label: 'Temperature fire', visParams: {{ min: 0, max: 45, palette: ['#081d58', '#225ea8', '#ffffb2', '#fd8d3c', '#bd0026'] }}, legend: [['#081d58', 'Cool'], ['#ffffb2', 'Moderate'], ['#bd0026', 'Hot']] }},
      ],
      terrain: [
        {{ id: 'default', label: 'Terrain green-brown', visParams: {{ min: 0, max: 1000, palette: ['#0f3b2e', '#3f7d3f', '#c9b96d', '#a2673f', '#f4f1e8'] }}, legend: [['#0f3b2e', 'Low'], ['#c9b96d', 'Mid'], ['#f4f1e8', 'High']] }},
        {{ id: 'gray', label: 'Terrain gray', visParams: {{ min: 0, max: 1000, palette: ['#111827', '#6b7280', '#f9fafb'] }}, legend: [['#111827', 'Low'], ['#6b7280', 'Mid'], ['#f9fafb', 'High']] }},
      ],
      nightlights: [
        {{ id: 'default', label: 'Night lights amber', visParams: {{ min: 0, max: 60, palette: ['#03071e', '#370617', '#f48c06', '#ffba08'] }}, legend: [['#03071e', 'Low'], ['#f48c06', 'Medium'], ['#ffba08', 'High']] }},
        {{ id: 'purple-gold', label: 'Night lights purple-gold', visParams: {{ min: 0, max: 60, palette: ['#1e1b4b', '#7e22ce', '#facc15'] }}, legend: [['#1e1b4b', 'Low'], ['#7e22ce', 'Medium'], ['#facc15', 'High']] }},
      ],
      population: [
        {{ id: 'default', label: 'Population red', visParams: {{ min: 0, max: 100, palette: ['#fff7ec', '#fdbb84', '#e34a33', '#7f0000'] }}, legend: [['#fff7ec', 'Sparse'], ['#e34a33', 'Dense']] }},
        {{ id: 'magenta', label: 'Population magenta', visParams: {{ min: 0, max: 100, palette: ['#fdf2f8', '#f472b6', '#831843'] }}, legend: [['#fdf2f8', 'Sparse'], ['#831843', 'Dense']] }},
      ],
      raster: [
        {{ id: 'default', label: 'Raster teal', visParams: {{ min: 0, max: 1, palette: ['#132b43', '#2c7fb8', '#7fcdbb', '#ffffcc'] }}, legend: [['#132b43', 'Low'], ['#7fcdbb', 'Mid'], ['#ffffcc', 'High']] }},
        {{ id: 'gray', label: 'Raster gray', visParams: {{ min: 0, max: 1, palette: ['#111827', '#9ca3af', '#f9fafb'] }}, legend: [['#111827', 'Low'], ['#9ca3af', 'Mid'], ['#f9fafb', 'High']] }},
      ],
      vector: [
        {{ id: 'default', label: 'Vector green', visParams: {{}}, legend: [['#16734d', 'Features']] }},
      ],
      rgb: [
        {{ id: 'default', label: 'RGB default', visParams: {{}}, legend: [['#6f9fcf', 'RGB composite']] }},
      ],
    }};
    let lastSessionStateText = '';
    let lastSessionActionId = 0;
    let sessionSyncBusy = false;
    let sessionActionBusy = false;
    const pendingDatasetIds = new Set();
    const failedDatasetIds = new Map();
    const DATASET_QUERY_ALIASES = {{
      '人口': 'population people worldpop ghsl ciesin',
      '建筑': 'building buildings footprint open-buildings built',
      '建筑物': 'building buildings footprint open-buildings built',
      '降水': 'precipitation rainfall rain chirps era5 gpm',
      '雨量': 'precipitation rainfall rain chirps gpm',
      '温度': 'temperature lst land surface temperature era5 modis',
      '地表温度': 'land surface temperature lst modis landsat',
      '夜光': 'nighttime lights viirs dnb radiance',
      '土地覆盖': 'land cover landcover dynamic world worldcover esa',
      '地类': 'land cover landcover dynamic world worldcover esa',
      '水体': 'water surface water occurrence jrc gsw',
      '地表水': 'water surface water occurrence jrc gsw',
      '洪水': 'flood water sentinel sar s1 inundation',
      '植被': 'vegetation ndvi evi modis sentinel landsat',
      '农作物': 'crop agriculture cropland aafc usda',
      '农业': 'agriculture crop cropland',
      '高程': 'elevation dem terrain srtm copernicus',
      '地形': 'terrain elevation dem srtm copernicus',
      '土壤': 'soil smap soilgrids moisture',
      '火灾': 'fire burned wildfire modis viirs',
      '空气': 'air quality atmosphere no2 aerosol',
      '气候': 'climate era5 temperature precipitation wind',
      '哨兵': 'sentinel copernicus s1 s2 s3 s5p',
      '雷达': 'sar radar sentinel-1 s1',
      '光学': 'optical sentinel-2 landsat modis',
    }};

    function $(id) {{ return document.getElementById(id); }}
    function t(key, vars = {{}}) {{
      const text = (I18N[currentLang] && I18N[currentLang][key]) || I18N.en[key] || key;
      return Object.entries(vars).reduce((value, [name, replacement]) => value.split(`:${{name}}`).join(String(replacement)), text);
    }}
    function log(message) {{
      const stamp = new Date().toLocaleTimeString([], {{ hour: '2-digit', minute: '2-digit', second: '2-digit' }});
      logLines.unshift(`${{stamp}}  ${{message}}`);
      const target = $('session-log');
      if (target) {{
        target.innerHTML = logLines.slice(0, 8).map(line => `<div class="log-line">${{escapeHtml(line)}}</div>`).join('');
      }}
    }}
    function logMsg(key, vars = {{}}) {{ log(t(key, vars)); }}
    function escapeHtml(value) {{
      return String(value).replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
    }}
    function fmt(num, digits = 5) {{ return Number(num).toFixed(digits); }}
    function normalizeFavoriteDatasetIds(value) {{
      if (!Array.isArray(value)) return [];
      return [...new Set(value.map(item => String(item || '').trim()).filter(Boolean))].sort();
    }}
    function loadFavoriteDatasetIds() {{
      try {{
        const parsed = JSON.parse(localStorage.getItem(FAVORITES_STORAGE_KEY) || '[]');
        return new Set(normalizeFavoriteDatasetIds(parsed));
      }} catch {{
        return new Set();
      }}
    }}
    let favoriteDatasetIds = loadFavoriteDatasetIds();
    STATE.aoiStyle = {{ ...DEFAULT_AOI_STYLE, ...(STATE.aoiStyle || {{}}) }};
    STATE.aoiShown = STATE.aoiShown !== false;
    STATE.measurementsShown = STATE.measurementsShown !== false;
    STATE.measurementsOpacity = normalizeMeasurementsOpacity(STATE.measurementsOpacity);
    let visualPreferences = (STATE.visualPreferences && typeof STATE.visualPreferences === 'object') ? {{ ...STATE.visualPreferences }} : {{}};
    function saveFavoriteDatasetIds() {{
      localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify([...favoriteDatasetIds].sort()));
    }}
    function isFavoriteDataset(datasetId) {{
      return favoriteDatasetIds.has(String(datasetId || ''));
    }}
    function favoriteCatalogItems(items = STATE.catalog) {{
      const catalog = Array.isArray(items) ? items : [];
      return catalog.filter(item => isFavoriteDataset(item.id));
    }}
    function toggleFavoriteDataset(datasetId) {{
      const id = String(datasetId || '');
      if (!id) return;
      const added = !favoriteDatasetIds.has(id);
      if (added) favoriteDatasetIds.add(id);
      else favoriteDatasetIds.delete(id);
      saveFavoriteDatasetIds();
      renderDatasets(filteredCatalog());
      showModeKey(added ? 'mode.favoriteAdded' : 'mode.favoriteRemoved', {{ dataset: id }});
      logMsg(added ? 'log.favoriteAdded' : 'log.favoriteRemoved', {{ dataset: id }});
      syncSessionState('favorites');
    }}
    function normalizeBounds(value) {{
      if (!Array.isArray(value) || value.length !== 2 || !Array.isArray(value[0]) || !Array.isArray(value[1])) return null;
      const south = Number(value[0][0]);
      const west = Number(value[0][1]);
      const north = Number(value[1][0]);
      const east = Number(value[1][1]);
      if (![south, west, north, east].every(Number.isFinite)) return null;
      if (south >= north || west >= east) return null;
      if (south < -90 || north > 90 || west < -180 || east > 180) return null;
      return [[south, west], [north, east]];
    }}
    function aoiFromBounds(bounds) {{
      const normalized = normalizeBounds(bounds);
      if (!normalized) return null;
      const [[south, west], [north, east]] = normalized;
      return {{
        type: 'rectangle',
        bounds: normalized,
        coordinates: [[south, west], [south, east], [north, east], [north, west]],
        coordinateOrder: 'latlng',
      }};
    }}
    function normalizeLatLngPair(pair) {{
      if (!Array.isArray(pair) || pair.length < 2) return null;
      const lat = Number(pair[0]);
      const lng = Number(pair[1]);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
      if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null;
      return [lat, lng];
    }}
    function normalizeLonLatPair(pair) {{
      if (!Array.isArray(pair) || pair.length < 2) return null;
      const lng = Number(pair[0]);
      const lat = Number(pair[1]);
      return normalizeLatLngPair([lat, lng]);
    }}
    function boundsFromAoiCoordinates(coordinates) {{
      if (!Array.isArray(coordinates) || coordinates.length < 3) return null;
      const lats = coordinates.map(point => point[0]);
      const lngs = coordinates.map(point => point[1]);
      const south = Math.min(...lats);
      const north = Math.max(...lats);
      const west = Math.min(...lngs);
      const east = Math.max(...lngs);
      return normalizeBounds([[south, west], [north, east]]);
    }}
    function normalizeAoiCoordinates(raw, order = 'latlng') {{
      if (!Array.isArray(raw) || !raw.length) return null;
      let points = raw;
      let pointOrder = order;
      if (Array.isArray(raw[0]) && raw[0].length && Array.isArray(raw[0][0])) {{
        points = raw[0];
        pointOrder = 'lonlat';
      }}
      const normalized = points.map(point => pointOrder === 'lonlat' ? normalizeLonLatPair(point) : normalizeLatLngPair(point)).filter(Boolean);
      const deduped = [];
      normalized.forEach(point => {{
        const previous = deduped[deduped.length - 1];
        if (!previous || Math.abs(previous[0] - point[0]) > 1e-12 || Math.abs(previous[1] - point[1]) > 1e-12) {{
          deduped.push(point);
        }}
      }});
      if (deduped.length > 3) {{
        const first = deduped[0];
        const last = deduped[deduped.length - 1];
        if (Math.abs(first[0] - last[0]) < 1e-12 && Math.abs(first[1] - last[1]) < 1e-12) deduped.pop();
      }}
      return deduped.length >= 3 && boundsFromAoiCoordinates(deduped) ? deduped : null;
    }}
    function normalizeAoi(value) {{
      if (!value || typeof value !== 'object') return null;
      if (String(value.type || '').toLowerCase() === 'feature' && value.geometry) return normalizeAoi(value.geometry);
      const type = String(value.type || '').toLowerCase();
      if (type === 'polygon' || type === 'multipolygon') {{
        const coordinates = normalizeAoiCoordinates(
          value.coordinates || value.latLngs || value.points,
          String(value.coordinateOrder || '').toLowerCase() === 'lonlat' ? 'lonlat' : 'latlng'
        );
        const bounds = coordinates ? boundsFromAoiCoordinates(coordinates) : null;
        if (!coordinates || !bounds) return null;
        return {{ type: 'polygon', bounds, coordinates, coordinateOrder: 'latlng' }};
      }}
      return aoiFromBounds(value.bounds || value.bbox || value);
    }}
    function cloneAoi(aoi) {{
      return aoi ? JSON.parse(JSON.stringify(aoi)) : null;
    }}
    function isHexColor(value) {{
      return /^#[0-9a-f]{{6}}$/i.test(String(value || '').trim());
    }}
    function normalizeAoiStyle(value = {{}}) {{
      const source = value && typeof value === 'object' ? value : {{}};
      const color = isHexColor(source.color) ? source.color : DEFAULT_AOI_STYLE.color;
      const fillColor = isHexColor(source.fillColor) ? source.fillColor : color;
      const opacity = Number.isFinite(Number(source.opacity)) ? Math.max(0, Math.min(1, Number(source.opacity))) : DEFAULT_AOI_STYLE.opacity;
      const fillOpacity = Number.isFinite(Number(source.fillOpacity)) ? Math.max(0, Math.min(0.6, Number(source.fillOpacity))) : DEFAULT_AOI_STYLE.fillOpacity;
      const weight = Number.isFinite(Number(source.weight)) ? Math.max(1, Math.min(6, Number(source.weight))) : DEFAULT_AOI_STYLE.weight;
      return {{ color, fillColor, opacity, fillOpacity, weight, shown: source.shown !== false }};
    }}
    function normalizeMeasurementsOpacity(value) {{
      const opacity = Number(value);
      return Number.isFinite(opacity) ? Math.max(0, Math.min(1, opacity)) : DEFAULT_MEASUREMENTS_STYLE.opacity;
    }}
    function layerStyleProfile(layer) {{
      if (!layer) return 'raster';
      if (layer.id === AOI_LAYER_ID || layer.type === 'aoi') return 'aoi';
      if (layer.id === MEASUREMENTS_LAYER_ID || layer.type === 'measurements') return 'measurements';
      if (Array.isArray(layer.visParams?.bands) && layer.visParams.bands.length > 1) return 'rgb';
      if (layer.styleProfile) return layer.styleProfile;
      const text = `${{layer.dataset || ''}} ${{layer.type || ''}} ${{layer.method || ''}} ${{layer.name || ''}}`.toLowerCase();
      if (text.includes('ndvi') || text.includes('vegetation')) return 'ndvi';
      if (text.includes('water') || text.includes('jrc') || text.includes('gsw')) return 'water';
      if (text.includes('lst') || text.includes('temperature') || text.includes('thermal')) return 'temperature';
      if (text.includes('dem') || text.includes('elevation') || text.includes('terrain')) return 'terrain';
      if (text.includes('viirs') || text.includes('night')) return 'nightlights';
      if (text.includes('population') || text.includes('worldpop') || text.includes('ghsl')) return 'population';
      if (String(layer.type || '').includes('categorical')) return 'categorical';
      if (String(layer.type || '').includes('vector')) return 'vector';
      return 'raster';
    }}
    function stylePresetOptions(layer) {{
      const profile = layerStyleProfile(layer);
      return VIS_PRESETS[profile] || VIS_PRESETS.raster;
    }}
    function stylePresetForLayer(layer, presetId) {{
      const options = stylePresetOptions(layer);
      return options.find(item => item.id === presetId) || options[0];
    }}
    function isLocalVectorLayer(meta) {{
      if (!meta || typeof meta !== 'object') return false;
      if (meta.recipe?.kind === 'localVectorOverlay') return true;
      const candidates = [
        meta.previewUrl,
        meta.sourceUrl,
        meta.recipe?.previewUrl,
        meta.recipe?.sourceUrl,
        meta.recipe?.url,
        meta.recipe?.path,
        meta.summary?.geojson,
        meta.summary?.path,
      ];
      return candidates.some(value => typeof value === 'string' && value.trim());
    }}
    function isUploadPlaceholderLayer(meta) {{
      return meta?.recipe?.kind === 'localUploadPlaceholder' || meta?.type === 'local-upload';
    }}
    function appendCacheBust(url, token) {{
      if (!url || !token) return url;
      const separator = String(url).includes('?') ? '&' : '?';
      return `${{url}}${{separator}}_easygeeRefresh=${{encodeURIComponent(token)}}`;
    }}
    function localVectorSourceUrl(meta) {{
      const raw = [
        meta?.previewUrl,
        meta?.sourceUrl,
        meta?.recipe?.previewUrl,
        meta?.recipe?.sourceUrl,
        meta?.recipe?.url,
        meta?.recipe?.path,
        meta?.summary?.geojson,
        meta?.summary?.path,
      ].find(value => typeof value === 'string' && value.trim());
      if (!raw) return '';
      const text = String(raw).trim();
      const refreshToken = layerRefreshTokens.get(meta?.id);
      const withRefresh = url => appendCacheBust(url, refreshToken);
      if (/^https?:\/\//i.test(text) || text.startsWith('/')) return withRefresh(text);
      const cleaned = text.replace(/\\\\/g, '/');
      const file = cleaned.split('/').filter(Boolean).pop();
      return file ? withRefresh(`./${{encodeURIComponent(file)}}`) : '';
    }}
    function localVectorBaseStyle(meta, feature) {{
      const properties = feature?.properties || {{}};
      const confidence = Number(properties.confidence);
      const opacity = Number.isFinite(Number(meta?.opacity)) ? Number(meta.opacity) : 0.95;
      const datasetText = `${{meta?.dataset || ''}} ${{meta?.name || ''}} ${{properties.object_class || ''}} ${{properties.road_type || ''}}`.toLowerCase();
      const geometryType = String(feature?.geometry?.type || '').toLowerCase();
      const isLine = geometryType.includes('line');
      const isPoint = geometryType.includes('point');
      const isRoad = datasetText.includes('road');
      const isCar = datasetText.includes('car') || datasetText.includes('vehicle');
      if (isRoad) {{
        const stroke = confidence >= 0.9 ? '#f59e0b' : confidence >= 0.75 ? '#22c55e' : '#38bdf8';
        return {{
          color: stroke,
          weight: confidence >= 0.9 ? 4 : confidence >= 0.75 ? 3.2 : 2.6,
          opacity,
          fill: false,
          dashArray: confidence >= 0.75 ? null : '6 6',
        }};
      }}
      if (isCar) {{
        const stroke = confidence >= 0.85 ? '#f97316' : confidence >= 0.7 ? '#06b6d4' : '#d946ef';
        return {{
          color: stroke,
          weight: 1.4,
          opacity,
          fill: true,
          fillColor: stroke,
          fillOpacity: Math.max(0.12, Math.min(0.55, opacity * 0.32)),
        }};
      }}
      if (isLine) {{
        return {{
          color: '#16734d',
          weight: 2.8,
          opacity,
          fill: false,
        }};
      }}
      return {{
        color: '#16734d',
        weight: 2.4,
        opacity,
        fill: !isLine,
        fillColor: '#16734d',
        fillOpacity: isPoint ? Math.max(0.18, Math.min(0.55, opacity * 0.28)) : Math.max(0.1, Math.min(0.45, opacity * 0.2)),
      }};
    }}
    function localVectorTooltip(feature) {{
      const properties = feature?.properties || {{}};
      const parts = [
        properties.name,
        properties.id,
        properties.object_class,
        properties.road_type,
        properties.status_hint,
      ].filter(Boolean);
      const confidence = Number(properties.confidence);
      if (Number.isFinite(confidence)) parts.push(`confidence ${{confidence.toFixed(2)}}`);
      return parts.join(' | ');
    }}
    function refreshLocalVectorLayer(record) {{
      const overlay = record?.tile?.__vectorOverlay;
      if (!overlay) return;
      overlay.eachLayer(layer => {{
        if (typeof layer.setStyle === 'function') {{
          layer.setStyle(localVectorBaseStyle(record.meta, layer.feature));
        }}
      }});
    }}
    function createLocalVectorLayer(meta) {{
      const group = L.layerGroup();
      const sourceUrl = localVectorSourceUrl(meta);
      if (!sourceUrl) return {{ layer: group, refresh: () => {{}} }};
      const refresh = () => refreshLocalVectorLayer({{ meta, tile: group }});
      group.__vectorReady = fetch(sourceUrl)
        .then(response => {{
          if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
          return response.json();
        }})
        .then(data => {{
          const overlay = L.geoJSON(data, {{
            style: feature => localVectorBaseStyle(meta, feature),
            pointToLayer: (feature, latlng) => L.circleMarker(latlng, {{
              ...localVectorBaseStyle(meta, feature),
              radius: 6,
            }}),
            onEachFeature: (feature, layer) => {{
              const tooltip = localVectorTooltip(feature);
              if (tooltip && typeof layer.bindTooltip === 'function') layer.bindTooltip(tooltip, {{ sticky: true }});
            }},
          }});
          group.__vectorOverlay = overlay;
          group.addLayer(overlay);
          refresh();
          return overlay;
        }})
        .catch(error => {{
          console.warn('EasyGEE local vector layer load failed:', meta?.name || meta?.id || 'layer', error);
          return null;
        }});
      return {{ layer: group, refresh }};
    }}
    function normalizeStateLayer(meta) {{
      if (!meta || typeof meta !== 'object') return null;
      if (isUploadPlaceholderLayer(meta) && meta.summary?.renderable === false) return null;
      const next = {{
        ...meta,
        shown: meta.shown !== false,
        opacity: Number.isFinite(Number(meta.opacity)) ? Math.max(0, Math.min(1, Number(meta.opacity))) : 0.82,
      }};
      if (isBasemapOverlayLayer(next)) {{
        next.sourceId = String(next.sourceId || '').trim();
        if (!next.sourceId) return null;
        next.role = 'overlay';
        next.styleProfile = 'basemap';
      }}
      next.styleProfile = next.styleProfile || layerStyleProfile(next);
      if (!next.stylePreset && visualPreferences[next.styleProfile]) next.stylePreset = visualPreferences[next.styleProfile];
      return next;
    }}
    function replaceStateLayers(layers) {{
      Array.from(layerRegistry.values()).forEach(record => {{
        if (record?.tile && map.hasLayer(record.tile)) map.removeLayer(record.tile);
      }});
      layerRegistry.clear();
      STATE.layers = (Array.isArray(layers) ? layers : []).map(normalizeStateLayer).filter(Boolean);
      STATE.layers.forEach(registerLayer);
      operationalMapOrderDirty = true;
      syncOperationalLayerOrder();
      if (activeLayerId && !layerModels().some(layer => layer?.id === activeLayerId)) {{
        activeLayerId = null;
      }}
    }}
    function uploadExtension(name = '') {{
      const text = String(name || '').toLowerCase();
      const dot = text.lastIndexOf('.');
      return dot >= 0 ? text.slice(dot) : '';
    }}
    function uploadFormatForName(name = '') {{
      const ext = uploadExtension(name);
      if (ext === '.geojson' || ext === '.json') return 'GeoJSON';
      if (ext === '.zip') return 'ZIP/Shapefile';
      if (['.shp', '.shx', '.dbf', '.prj', '.cpg'].includes(ext)) return 'Shapefile';
      if (ext === '.kml' || ext === '.kmz') return ext.slice(1).toUpperCase();
      if (ext === '.gpx') return 'GPX';
      if (ext === '.csv') return 'CSV';
      if (ext === '.gpkg') return 'GPKG';
      return 'Unknown';
    }}
    function uploadProcessingHints(record) {{
      const format = String(record?.format || uploadFormatForName(record?.name)).toLowerCase();
      if (record?.renderable || record?.previewUrl) {{
        return {{
          browserPreview: true,
          agentAction: 'loaded as a local preview layer; optional QA or convert to EE FeatureCollection',
          expectedGeometry: 'browser-renderable GeoJSON preview',
        }};
      }}
      if (format.includes('geojson')) {{
        return {{
          browserPreview: true,
          agentAction: 'optional QA or convert GeoJSON to EE FeatureCollection',
          expectedGeometry: 'GeoJSON FeatureCollection or Geometry',
        }};
      }}
      if (format.includes('csv')) {{
        return {{
          browserPreview: false,
          agentAction: 'inspect columns, detect lon/lat or WKT, then convert to GeoJSON/EE table',
          expectedGeometry: 'point table or WKT geometry columns',
        }};
      }}
      if (format.includes('shapefile') || format.includes('zip')) {{
        return {{
          browserPreview: false,
          agentAction: 'read saved shapefile bundle with geopandas/ogr, apply projection if missing, then add vector layer',
          expectedGeometry: 'vector features',
        }};
      }}
      if (format.includes('gpkg')) {{
        return {{
          browserPreview: false,
          agentAction: 'inspect GeoPackage layers with geopandas/ogr and choose a layer to add',
          expectedGeometry: 'vector or raster package layer',
        }};
      }}
      if (format.includes('kml') || format.includes('kmz') || format.includes('gpx')) {{
        return {{
          browserPreview: false,
          agentAction: 'convert GPS/KML features to GeoJSON before map overlay',
          expectedGeometry: 'vector tracks, points, or polygons',
        }};
      }}
      return {{
        browserPreview: false,
        agentAction: 'inspect saved file and choose a geospatial conversion path',
        expectedGeometry: 'unknown',
      }};
    }}
    function normalizeUploadRecord(record) {{
      if (!record || typeof record !== 'object') return null;
      const name = String(record.name || record.storedName || 'upload');
      const format = record.format || uploadFormatForName(name);
      const extension = record.extension || uploadExtension(name);
      const shapefileSidecarOnly = ['.dbf', '.shx', '.prj', '.cpg'].includes(String(extension).toLowerCase());
      const renderable = record.renderable === true || Boolean(record.previewUrl) || String(format || '').toLowerCase().includes('geojson');
      const timestamp = new Date().toISOString();
      const next = {{
        id: String(record.id || `upload-${{Date.now()}}-${{Math.random().toString(16).slice(2, 8)}}`),
        name,
        storedName: record.storedName || name,
        extension,
        format,
        size: Number(record.size || 0),
        projection: record.projection || $('upload-projection')?.value || 'EPSG:4326',
        savedPath: record.savedPath || null,
        url: record.url || null,
        componentPaths: record.componentPaths || null,
        previewPath: record.previewPath || null,
        previewUrl: record.previewUrl || null,
        previewFormat: record.previewFormat || null,
        previewFeatureCount: Number.isFinite(Number(record.previewFeatureCount)) ? Number(record.previewFeatureCount) : null,
        previewLimited: record.previewLimited === true,
        previewError: record.previewError || null,
        renderable,
        agentReadable: record.agentReadable !== false,
        status: record.status || 'saved',
        createdAt: record.createdAt || timestamp,
        updatedAt: record.updatedAt || record.createdAt || timestamp,
        layerId: renderable ? (record.layerId || null) : null,
      }};
      if (shapefileSidecarOnly && !next.renderable) {{
        next.status = 'missing-shapefile-components';
        next.previewError = next.previewError || 'Shapefile upload is incomplete. Select the .shp geometry file together with .shx and .dbf, or upload a ZIP containing all components.';
      }}
      next.processingHints = record.processingHints || uploadProcessingHints(next);
      next.recommendedAgentAction = record.recommendedAgentAction || next.processingHints.agentAction;
      return next;
    }}
    function persistUploads() {{
      localStorage.setItem(UPLOADS_STORAGE_KEYS[0], JSON.stringify((STATE.uploads || []).slice(0, 50)));
    }}
    function restoreUploads() {{
      for (const key of UPLOADS_STORAGE_KEYS) {{
        try {{
          const parsed = JSON.parse(localStorage.getItem(key) || '[]');
          const uploads = Array.isArray(parsed) ? parsed.map(normalizeUploadRecord).filter(Boolean) : [];
          if (uploads.length) return uploads;
        }} catch {{}}
      }}
      return [];
    }}
    function formatBytes(value) {{
      const size = Number(value || 0);
      if (!Number.isFinite(size) || size <= 0) return '0 B';
      if (size >= 1024 * 1024) return `${{(size / 1024 / 1024).toFixed(1)}} MB`;
      if (size >= 1024) return `${{(size / 1024).toFixed(1)}} KB`;
      return `${{Math.round(size)}} B`;
    }}
    function renderUploads() {{
      const fileInput = $('upload-file-input');
      const fileCount = fileInput?.files?.length || 0;
      const nameTarget = $('upload-file-name');
      if (nameTarget) {{
        if (!fileCount) nameTarget.textContent = t('upload.noFile');
        else if (fileCount === 1) nameTarget.textContent = fileInput.files[0].name;
        else nameTarget.textContent = t('upload.ready', {{ count: fileCount }});
      }}
      const submit = $('upload-submit-btn');
      if (submit) submit.disabled = fileCount <= 0;
      const list = $('upload-list');
      if (!list) return;
      const uploads = (Array.isArray(STATE.uploads) ? STATE.uploads : []).map(normalizeUploadRecord).filter(Boolean);
      if (!uploads.length) {{
        list.innerHTML = `<div class="upload-status">${{escapeHtml(t('upload.empty'))}}</div>`;
        return;
      }}
      list.innerHTML = uploads.slice(0, 8).map(record => `
        <div class="upload-item" data-upload="${{escapeHtml(record.id)}}">
          <div class="upload-item-top">
            <div class="upload-item-name">${{escapeHtml(record.name)}}</div>
            <div class="upload-item-actions">
              <span class="upload-item-tag">${{escapeHtml(record.format)}}</span>
              <button class="upload-remove icon-btn" data-upload-remove="${{escapeHtml(record.id)}}" title="${{escapeHtml(t('upload.remove'))}}" aria-label="${{escapeHtml(t('upload.remove'))}}" type="button">{svg_icon("trash")}</button>
            </div>
          </div>
          <div class="upload-item-meta">${{escapeHtml(formatBytes(record.size))}} · ${{escapeHtml(record.projection || '-')}} · ${{escapeHtml(t('upload.agentReady'))}}</div>
          <div class="upload-item-meta">${{escapeHtml(record.savedPath || record.url || record.status || '')}}</div>
          ${{record.layerId ? `<div class="upload-item-meta">${{escapeHtml(t('upload.layerAdded'))}}</div>` : ''}}
          ${{!record.layerId && !record.renderable ? `<div class="upload-item-meta">${{escapeHtml(record.previewError || t('upload.notRenderable'))}}</div>` : ''}}
        </div>
      `).join('');
      list.querySelectorAll('[data-upload-remove]').forEach(button => {{
        button.addEventListener('click', event => {{
          event.stopPropagation();
          removeUpload(button.dataset.uploadRemove);
        }});
      }});
    }}
    function uploadedLayerId(record) {{
      return `upload-${{record.id.replace(/[^a-z0-9_-]+/gi, '-')}}-vector`;
    }}
    function addUploadedLayer(record) {{
      if (!record) return null;
      const layerId = uploadedLayerId(record);
      const sourceUrl = record.previewUrl || (String(record.format || '').toLowerCase().includes('geojson') ? record.url : null);
      const baseName = record.name.replace(/\.(geojson|json|csv|kml|kmz|gpx|shp|zip|gpkg)$/i, '');
      if (!sourceUrl) {{
        const placeholder = {{
          id: layerId,
          name: baseName,
          dataset: `local-upload:${{record.name}}`,
          type: 'local-upload',
          shown: true,
          opacity: 1,
          styleProfile: 'vector',
          stylePreset: 'default',
          legend: [['#64748b', 'Uploaded file']],
          recipe: {{
            kind: 'localUploadPlaceholder',
            source: 'userUpload',
            savedPath: record.savedPath,
            componentPaths: record.componentPaths,
            projection: record.projection,
            format: record.format,
            status: record.status,
            previewError: record.previewError,
            recommendedAgentAction: record.recommendedAgentAction,
          }},
          summary: {{
            format: record.format,
            size: record.size,
            uploadedAt: record.createdAt,
            savedPath: record.savedPath,
            componentPaths: record.componentPaths,
            previewError: record.previewError,
            renderable: false,
          }},
        }};
        addGeneratedLayer(placeholder);
        return layerId;
      }}
      const layer = {{
        id: layerId,
        name: baseName,
        dataset: `local-upload:${{record.name}}`,
        type: 'local-vector',
        shown: true,
        opacity: 0.92,
        sourceUrl,
        previewUrl: sourceUrl,
        styleProfile: 'vector',
        stylePreset: 'default',
        legend: [['#16734d', 'Uploaded features']],
        recipe: {{
          kind: 'localVectorOverlay',
          source: 'userUpload',
          sourceUrl,
          previewUrl: sourceUrl,
          savedPath: record.savedPath,
          previewPath: record.previewPath,
          componentPaths: record.componentPaths,
          projection: record.projection,
          format: record.format,
          previewFeatureCount: record.previewFeatureCount,
        }},
        summary: {{
          format: record.format,
          size: record.size,
          uploadedAt: record.createdAt,
          savedPath: record.savedPath,
          previewPath: record.previewPath,
          previewFeatureCount: record.previewFeatureCount,
          previewLimited: record.previewLimited,
          renderable: true,
        }},
      }};
      addGeneratedLayer(layer);
      return layerId;
    }}
    function rememberUploads(records) {{
      const existing = new Map((STATE.uploads || []).map(item => [item.id, item]));
      records.map(normalizeUploadRecord).filter(Boolean).forEach(record => existing.set(record.id, record));
      STATE.uploads = Array.from(existing.values()).slice(-50).reverse();
      persistUploads();
      renderUploads();
    }}
    function removeUpload(uploadId) {{
      const id = String(uploadId || '');
      if (!id) return false;
      const uploads = (Array.isArray(STATE.uploads) ? STATE.uploads : []).map(normalizeUploadRecord).filter(Boolean);
      const record = uploads.find(item => item.id === id);
      if (!record) return false;
      STATE.uploads = uploads.filter(item => item.id !== id);
      persistUploads();
      if (record.layerId) removeLayer(record.layerId);
      renderUploads();
      syncSessionState('upload-removed');
      return true;
    }}
    async function uploadSelectedFiles() {{
      const input = $('upload-file-input');
      const files = Array.from(input?.files || []);
      if (!files.length) return false;
      const oversized = files.find(file => file.size > UPLOAD_CAPABILITIES.maxBytes);
      const status = $('upload-status');
      if (oversized) {{
        status.textContent = t('upload.tooLarge', {{ name: oversized.name }});
        status.classList.add('error');
        return false;
      }}
      status.textContent = t('upload.saving');
      status.classList.remove('error');
      const form = new FormData();
      files.forEach(file => form.append('files', file, file.name));
      form.append('projection', $('upload-projection').value || 'EPSG:4326');
      try {{
        const response = await fetch(UPLOAD_CAPABILITIES.endpoint, {{ method: 'POST', body: form }});
        const payload = await response.json().catch(() => ({{ ok: false, error: response.statusText || 'upload failed' }}));
        if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${{response.status}}`);
        const savedRecords = (Array.isArray(payload.uploads) ? payload.uploads : []).map(normalizeUploadRecord).filter(Boolean);
        savedRecords.forEach(record => {{
          if (record.renderable) {{
            record.layerId = addUploadedLayer(record);
            if (record.layerId) record.status = 'layer-added';
          }} else {{
            record.layerId = null;
            if (!record.status || record.status === 'saved') record.status = 'saved-needs-conversion';
          }}
          addTask({{
            type: 'upload',
            name: `Upload: ${{record.name}}`,
            status: record.layerId && record.renderable ? 'done' : 'ready',
            destination: 'EasyGEE local uploads',
            createdAt: record.createdAt,
            params: {{
              format: record.format,
              projection: record.projection,
              savedPath: record.savedPath,
              previewPath: record.previewPath,
              url: record.url,
              previewUrl: record.previewUrl,
              renderable: record.renderable,
              previewError: record.previewError,
              recommendedAgentAction: record.recommendedAgentAction,
            }},
            notes: [record.previewError, record.recommendedAgentAction].filter(Boolean),
          }}, {{ reason: 'upload-task' }});
          logMsg('log.uploadSaved', {{ file: record.name }});
        }});
        rememberUploads(savedRecords);
        input.value = '';
        const addedCount = savedRecords.filter(record => record.layerId).length;
        status.textContent = addedCount === savedRecords.length
          ? t('upload.saved', {{ count: savedRecords.length }})
          : t('upload.savedPartial', {{ total: savedRecords.length, added: addedCount }});
        status.classList.toggle('error', addedCount < savedRecords.length);
        renderUploads();
        syncSessionState('uploads');
        return true;
      }} catch (error) {{
        const message = error && error.message ? error.message : String(error);
        status.textContent = t('upload.failed', {{ message }});
        status.classList.add('error');
        syncSessionState('upload-failed');
        return false;
      }}
    }}
    function palettePreviewHtml(palette = []) {{
      if (!Array.isArray(palette) || !palette.length) return '';
      return `<div class="palette-preview">${{palette.map(color => `<span style="background:${{escapeHtml(color)}}"></span>`).join('')}}</div>`;
    }}
    function sanitizeVisParams(value) {{
      if (!value || typeof value !== 'object') return {{}};
      const out = {{}};
      ['min', 'max', 'gamma'].forEach(key => {{
        const num = Number(value[key]);
        if (Number.isFinite(num)) out[key] = num;
      }});
      if (Array.isArray(value.bands)) out.bands = value.bands.map(String).filter(Boolean).slice(0, 4);
      if (Array.isArray(value.palette)) out.palette = value.palette.map(String).filter(isHexColor).slice(0, 32);
      return out;
    }}
    function readLocalJson(keys, fallbackText = 'null') {{
      for (const key of keys) {{
        try {{
          const raw = localStorage.getItem(key);
          if (raw != null) return JSON.parse(raw);
        }} catch {{}}
      }}
      try {{
        return JSON.parse(fallbackText);
      }} catch {{
        return null;
      }}
    }}
    function loadPersistedAoi() {{
      try {{
        const parsed = readLocalJson(AOI_STORAGE_KEYS, 'null');
        const restored = normalizeAoi(parsed && parsed.aoi ? parsed.aoi : parsed);
        return restored || null;
      }} catch {{
        return null;
      }}
    }}
    function persistAoi() {{
      if (!STATE.aoi) {{
        AOI_STORAGE_KEYS.forEach(key => localStorage.removeItem(key));
        return;
      }}
      localStorage.setItem(AOI_STORAGE_KEYS[0], JSON.stringify({{
        project: STATE.project,
        title: STATE.title,
        aoi: STATE.aoi,
        updatedAt: new Date().toISOString(),
      }}));
    }}
    function hasAoi() {{
      return Boolean(STATE.aoi && normalizeAoi(STATE.aoi));
    }}
    function hasAoiBounds() {{
      return Boolean(hasAoi() && normalizeBounds(STATE.aoi.bounds));
    }}
    function currentAoiBounds() {{
      return hasAoiBounds() ? STATE.aoi.bounds : null;
    }}
    function cogBasemapBounds(meta) {{
      if (!meta?.custom || meta.type !== 'cog' || !Array.isArray(meta.bounds) || meta.bounds.length !== 4) return null;
      const values = meta.bounds.map(Number);
      if (!values.every(Number.isFinite) || values[0] >= values[2] || values[1] >= values[3]) return null;
      return L.latLngBounds([[values[1], values[0]], [values[3], values[2]]]);
    }}
    function fitCogBasemapBounds(meta, force = false) {{
      const bounds = cogBasemapBounds(meta);
      if (!bounds || (!force && map.getBounds().intersects(bounds))) return false;
      map.fitBounds(bounds, {{ padding: [42, 42], maxZoom: Math.min(meta.maxNativeZoom || 17, 17) }});
      return true;
    }}
    function resetHomeView() {{
      const activeBasemap = BASEMAPS.find(meta => meta.id === currentBasemap);
      const activeCogBounds = cogBasemapBounds(activeBasemap);
      const aoiBounds = hasAoiBounds() ? L.latLngBounds(STATE.aoi.bounds) : null;
      if (activeCogBounds && (!aoiBounds || !aoiBounds.intersects(activeCogBounds))) {{
        fitCogBasemapBounds(activeBasemap, true);
        return;
      }}
      if (hasAoiBounds()) {{
        map.fitBounds(STATE.aoi.bounds, {{ padding: [24, 24] }});
      }} else {{
        map.setView(STATE.center || [{DEFAULT_EMPTY_CENTER[0]}, {DEFAULT_EMPTY_CENTER[1]}], STATE.zoom || {DEFAULT_EMPTY_ZOOM});
      }}
    }}
    function mapBoundsAoi() {{
      const bounds = map.getBounds();
      return aoiFromBounds([[bounds.getSouth(), bounds.getWest()], [bounds.getNorth(), bounds.getEast()]]);
    }}
    function currentProcessingAoi() {{
      return hasAoi() ? cloneAoi(STATE.aoi) : mapBoundsAoi();
    }}
    function currentProcessingBounds() {{
      const aoi = currentProcessingAoi();
      return aoi ? aoi.bounds : null;
    }}
    function normalizeMeasurement(item) {{
      if (!item || typeof item !== 'object') return null;
      const start = normalizeLatLngPair(item.start);
      const end = normalizeLatLngPair(item.end);
      const lengthMeters = Number(item.lengthMeters);
      if (!start || !end || !Number.isFinite(lengthMeters) || lengthMeters < 0) return null;
      return {{
        id: String(item.id || `measure-${{Date.now().toString(36)}}`),
        start,
        end,
        lengthMeters,
        lengthLabel: item.lengthLabel || formatDistance(lengthMeters),
        createdAt: item.createdAt || new Date().toISOString(),
      }};
    }}
    function loadPersistedMeasurements() {{
      try {{
        const parsed = readLocalJson(MEASUREMENTS_STORAGE_KEYS, '[]');
        return Array.isArray(parsed) ? parsed.map(normalizeMeasurement).filter(Boolean) : [];
      }} catch {{
        return [];
      }}
    }}
    function persistMeasurements() {{
      localStorage.setItem(MEASUREMENTS_STORAGE_KEYS[0], JSON.stringify(STATE.measurements || []));
    }}
    function normalizeTask(item) {{
      if (!item || typeof item !== 'object') return null;
      const taskId = item.taskId || item.eeTaskId || item.id || '';
      const id = String(item.id || taskId || item.name || item.title || `task-${{Date.now().toString(36)}}-${{Math.random().toString(36).slice(2, 7)}}`);
      const title = String(item.title || item.name || item.analysis || item.type || 'Task');
      const status = String(item.status || item.state || 'ready').toLowerCase();
      const normalized = {{
        ...item,
        id,
        title,
        status,
        type: item.type || 'task',
        createdAt: item.createdAt || new Date().toISOString(),
        updatedAt: item.updatedAt || item.createdAt || new Date().toISOString(),
      }};
      if (taskId) normalized.taskId = String(taskId);
      return normalized;
    }}
    function loadPersistedTasks() {{
      try {{
        const parsed = readLocalJson(TASKS_STORAGE_KEYS, '[]');
        return Array.isArray(parsed) ? parsed.map(normalizeTask).filter(Boolean) : [];
      }} catch {{
        return [];
      }}
    }}
    function persistTasks() {{
      localStorage.setItem(TASKS_STORAGE_KEYS[0], JSON.stringify((STATE.tasks || []).slice(0, 30)));
    }}
    function taskStatusClass(status) {{
      return String(status || 'ready').toLowerCase().replace(/[^a-z0-9_-]+/g, '-');
    }}
    function taskParamsText(task) {{
      const params = task && typeof task.params === 'object' ? task.params : null;
      if (!params) return '';
      return [
        params.index,
        params.dataset,
        params.startDate && params.endDate ? `${{params.startDate}} to ${{params.endDate}}` : '',
        params.scale ? `${{params.scale}} m` : '',
      ].filter(Boolean).join(' | ');
    }}
    function latestDriveTask() {{
      return (Array.isArray(STATE.tasks) ? STATE.tasks : []).map(normalizeTask).filter(task => {{
        return task && (task.driveSearchUrl || task.destination === 'Google Drive' || task.type === 'drive-export');
      }})[0] || null;
    }}
    function driveTargetUrl() {{
      const task = latestDriveTask();
      if (task?.driveSearchUrl) return task.driveSearchUrl;
      if (task?.fileNamePrefix) return `https://drive.google.com/drive/search?q=${{encodeURIComponent(task.fileNamePrefix)}}`;
      return 'https://drive.google.com/drive/my-drive';
    }}
    function driveTargetLabel() {{
      const task = latestDriveTask();
      if (task?.fileNamePrefix) return task.fileNamePrefix;
      if (task?.title) return task.title;
      return 'Google Drive';
    }}
    function updateDriveButtonTitle() {{
      const button = $('drive-btn');
      if (!button) return;
      const key = latestDriveTask() ? 'tool.driveRecent' : 'tool.driveRoot';
      const label = t(key);
      button.title = label;
      button.setAttribute('aria-label', label);
    }}
    function openDriveTarget() {{
      const url = driveTargetUrl();
      const opened = window.open(url, '_blank', 'noopener,noreferrer');
      if (!opened) window.location.href = url;
      logMsg('log.driveOpened', {{ target: driveTargetLabel() }});
    }}
    function renderTasks() {{
      const target = $('task-list');
      if (!target) return;
      const rows = Array.isArray(STATE.tasks) ? STATE.tasks.map(normalizeTask).filter(Boolean) : [];
      STATE.tasks = rows;
      updateDriveButtonTitle();
      if (!rows.length) {{
        target.innerHTML = `<div class="quota-note">${{escapeHtml(t('tasks.empty'))}}</div>`;
        return;
      }}
      target.innerHTML = rows.slice(0, 12).map(task => {{
        const title = task.title || task.name || 'Task';
        const status = task.status || 'ready';
        const meta = [
          task.destination ? `${{t('task.destination')}}: ${{task.destination}}` : '',
          task.folder ? `${{t('task.folder')}}: ${{task.folder}}` : '',
          task.fileNamePrefix ? `${{t('task.prefix')}}: ${{task.fileNamePrefix}}` : '',
          task.taskId ? `${{t('task.id')}}: ${{task.taskId}}` : '',
          taskParamsText(task) ? `${{t('task.params')}}: ${{taskParamsText(task)}}` : '',
        ].filter(Boolean);
        const search = task.driveSearchUrl
          ? `<a class="task-link" href="${{escapeHtml(task.driveSearchUrl)}}" target="_blank" rel="noreferrer">${{escapeHtml(t('task.driveSearch'))}}</a>`
          : '';
        const note = Array.isArray(task.notes) && task.notes.length ? `<div>${{escapeHtml(task.notes[0])}}</div>` : '';
        return `
          <div class="task-row status-${{escapeHtml(taskStatusClass(status))}}">
            <div class="task-head">
              <div class="task-title">${{escapeHtml(title)}}</div>
              <div class="task-status" title="${{escapeHtml(status)}}">${{escapeHtml(status)}}</div>
            </div>
            <div class="task-meta">${{meta.map(item => `<div>${{escapeHtml(item)}}</div>`).join('')}}${{note}}</div>
            ${{search ? `<div class="task-actions">${{search}}</div>` : ''}}
          </div>
        `;
      }}).join('');
    }}
    function addTask(task, options = {{}}) {{
      const normalized = normalizeTask(task);
      if (!normalized) return false;
      const index = (STATE.tasks || []).findIndex(item => {{
        const existing = normalizeTask(item);
        return existing && (existing.id === normalized.id || (existing.taskId && normalized.taskId && existing.taskId === normalized.taskId));
      }});
      normalized.updatedAt = new Date().toISOString();
      if (index >= 0) {{
        STATE.tasks.splice(index, 1);
      }}
      STATE.tasks.unshift(normalized);
      STATE.tasks = STATE.tasks.slice(0, 30);
      persistTasks();
      renderTasks();
      updateDriveButtonTitle();
      logMsg(options.logKey || 'log.taskAdded', {{ task: normalized.title }});
      syncSessionState(options.reason || 'task-added');
      return true;
    }}
    function measurementSummary(measurements = STATE.measurements) {{
      const rows = Array.isArray(measurements) ? measurements.filter(item => Number.isFinite(Number(item.lengthMeters))) : [];
      const lengths = rows.map(item => Number(item.lengthMeters));
      const totalMeters = lengths.reduce((sum, value) => sum + value, 0);
      const count = lengths.length;
      const meanMeters = count ? totalMeters / count : 0;
      return {{
        count,
        totalMeters,
        meanMeters,
        minMeters: count ? Math.min(...lengths) : 0,
        maxMeters: count ? Math.max(...lengths) : 0,
        totalLabel: formatDistance(totalMeters),
        meanLabel: formatDistance(meanMeters),
        minLabel: formatDistance(count ? Math.min(...lengths) : 0),
        maxLabel: formatDistance(count ? Math.max(...lengths) : 0),
      }};
    }}
    function initializePersistentState() {{
      const generatedAoi = normalizeAoi(STATE.aoi) || aoiFromBounds(STATE.bounds);
      const restoredAoi = loadPersistedAoi();
      STATE.aoi = restoredAoi || generatedAoi || null;
      STATE.bounds = STATE.aoi ? STATE.aoi.bounds : null;
      STATE.aoiStyle = normalizeAoiStyle(STATE.aoiStyle);
      STATE.aoiShown = STATE.aoiShown !== false;
      STATE.measurementsShown = STATE.measurementsShown !== false;
      STATE.measurementsOpacity = normalizeMeasurementsOpacity(STATE.measurementsOpacity);
      const generatedMeasurements = Array.isArray(STATE.measurements) ? STATE.measurements.map(normalizeMeasurement).filter(Boolean) : [];
      const restoredMeasurements = loadPersistedMeasurements();
      STATE.measurements = restoredMeasurements.length ? restoredMeasurements : generatedMeasurements;
      const generatedTasks = Array.isArray(STATE.tasks) ? STATE.tasks.map(normalizeTask).filter(Boolean) : [];
      const restoredTasks = loadPersistedTasks();
      STATE.tasks = restoredTasks.length ? restoredTasks : generatedTasks;
      const generatedUploads = Array.isArray(STATE.uploads) ? STATE.uploads.map(normalizeUploadRecord).filter(Boolean) : [];
      const restoredUploads = restoreUploads();
      STATE.uploads = restoredUploads.length ? restoredUploads : generatedUploads;
      if (restoredAoi) logMsg('log.aoiRestored');
    }}
    function profileProjectEntry(profile) {{
      if (!profile || typeof profile !== 'object' || !profile.projects || typeof profile.projects !== 'object') return null;
      if (profile.projects[PROJECT_STORAGE_ID] && typeof profile.projects[PROJECT_STORAGE_ID] === 'object') return profile.projects[PROJECT_STORAGE_ID];
      const project = String(STATE.project || '');
      const title = String(STATE.title || '');
      return Object.values(profile.projects).find(entry => entry && typeof entry === 'object' && (entry.project === project || entry.title === title)) || null;
    }}
    function applySessionProfile(profile) {{
      if (!profile || typeof profile !== 'object') return false;
      let changed = false;
      let basemapProfileChanged = false;
      let preferredBasemap = null;
      if (Array.isArray(profile.favoriteDatasets) && (profile.updatedAt || profile.favoriteDatasets.length)) {{
        const nextFavorites = normalizeFavoriteDatasetIds(profile.favoriteDatasets);
        const currentFavorites = [...favoriteDatasetIds].sort();
        if (JSON.stringify(nextFavorites) !== JSON.stringify(currentFavorites)) {{
          favoriteDatasetIds = new Set(nextFavorites);
          saveFavoriteDatasetIds();
          changed = true;
        }}
      }}
      if (profile.visualPreferences && typeof profile.visualPreferences === 'object') {{
        visualPreferences = {{ ...visualPreferences, ...profile.visualPreferences }};
        changed = true;
      }}
      if (Array.isArray(profile.customBasemaps)) {{
        const nextCustomBasemaps = normalizeCustomBasemaps(profile.customBasemaps);
        const currentText = JSON.stringify(customBasemaps.map(serializableCustomBasemap));
        const nextText = JSON.stringify(nextCustomBasemaps.map(serializableCustomBasemap));
        if (currentText !== nextText) {{
          customBasemaps = nextCustomBasemaps;
          basemapProfileChanged = true;
        }}
      }}
      if (typeof profile.defaultBasemap === 'string' && profile.defaultBasemap.trim()) {{
        const nextDefault = profile.defaultBasemap.trim();
        if (nextDefault !== defaultBasemapId) basemapProfileChanged = true;
        defaultBasemapId = nextDefault;
        preferredBasemap = nextDefault;
      }}
      const entry = profileProjectEntry(profile);
      if (entry) {{
        if (entry.view && typeof entry.view === 'object') {{
          const center = Array.isArray(entry.view.center) ? entry.view.center.map(Number) : [];
          const zoom = Number(entry.view.zoom);
          if (center.length === 2 && center.every(Number.isFinite) && center[0] >= -90 && center[0] <= 90 && center[1] >= -180 && center[1] <= 180 && Number.isFinite(zoom)) {{
            restoredProfileView = {{ center, zoom: Math.max(0, Math.min(24, zoom)) }};
            STATE.center = [...center];
            STATE.zoom = restoredProfileView.zoom;
            changed = true;
          }}
        }}
        if (entry.view && typeof entry.view === 'object' && typeof entry.view.basemap === 'string') {{
          preferredBasemap = entry.view.basemap;
          basemapProfileChanged = true;
        }}
        if (entry.view && typeof entry.view === 'object' && typeof entry.view.basemapShown === 'boolean') {{
          primaryBasemapShown = entry.view.basemapShown;
          basemapProfileChanged = true;
        }}
        if (entry.view && typeof entry.view === 'object' && Number.isFinite(Number(entry.view.basemapOpacity))) {{
          primaryBasemapOpacity = Math.max(0, Math.min(1, Number(entry.view.basemapOpacity)));
          basemapProfileChanged = true;
        }}
        const profileAoi = normalizeAoi(entry.aoi);
        if (profileAoi && JSON.stringify(profileAoi) !== JSON.stringify(STATE.aoi || null)) {{
          STATE.aoi = profileAoi;
          STATE.bounds = profileAoi.bounds;
          persistAoi();
          changed = true;
          logMsg('log.aoiRestored');
        }}
        if (entry.aoiStyle && typeof entry.aoiStyle === 'object') {{
          STATE.aoiStyle = normalizeAoiStyle(entry.aoiStyle);
          changed = true;
        }}
        if (typeof entry.aoiShown === 'boolean') {{
          STATE.aoiShown = entry.aoiShown;
          changed = true;
        }}
        if (Array.isArray(entry.measurements)) {{
          const profileMeasurements = entry.measurements.map(normalizeMeasurement).filter(Boolean);
          if (JSON.stringify(profileMeasurements) !== JSON.stringify(STATE.measurements || [])) {{
            STATE.measurements = profileMeasurements;
            persistMeasurements();
            changed = true;
          }}
        }}
        if (typeof entry.measurementsShown === 'boolean') {{
          STATE.measurementsShown = entry.measurementsShown;
          changed = true;
        }}
        if (entry.measurementsOpacity !== undefined) {{
          const opacity = normalizeMeasurementsOpacity(entry.measurementsOpacity);
          if (opacity !== STATE.measurementsOpacity) {{
            STATE.measurementsOpacity = opacity;
            changed = true;
          }}
        }}
        if (Array.isArray(entry.tasks)) {{
          const profileTasks = entry.tasks.map(normalizeTask).filter(Boolean);
          if (JSON.stringify(profileTasks) !== JSON.stringify(STATE.tasks || [])) {{
            STATE.tasks = profileTasks;
            persistTasks();
            changed = true;
          }}
        }}
        if (Array.isArray(entry.uploads)) {{
          const profileUploads = entry.uploads.map(normalizeUploadRecord).filter(Boolean);
          if (JSON.stringify(profileUploads) !== JSON.stringify(STATE.uploads || [])) {{
            STATE.uploads = profileUploads;
            persistUploads();
            changed = true;
          }}
        }}
        const describeLayers = layers => JSON.stringify((layers || []).map(layer => ({{
            id: layer.id,
            name: layer.name,
            dataset: layer.dataset,
            type: layer.type,
            shown: layer.shown !== false,
            opacity: layer.opacity,
            role: layer.role || null,
            sourceId: layer.sourceId || null,
            styleProfile: layer.styleProfile || null,
            stylePreset: layer.stylePreset || null,
            recipe: layer.recipe || null,
            summary: layer.summary || null,
        }})));
        if (Array.isArray(entry.layers)) {{
          const restoredLayers = entry.layers.map(normalizeStateLayer).filter(Boolean);
          if (describeLayers(restoredLayers) !== describeLayers(STATE.layers || [])) {{
            replaceStateLayers(restoredLayers);
            changed = true;
          }}
        }} else if (Array.isArray(entry.recentLayers)) {{
          const recentById = new Map(entry.recentLayers
            .filter(layer => layer && typeof layer === 'object' && layer.id)
            .map(layer => [String(layer.id), layer]));
          const restoredGeneratedLayers = (STATE.layers || []).filter(layer => !isBasemapOverlayLayer(layer)).map(layer => {{
            const recent = recentById.get(String(layer.id));
            return recent
              ? normalizeStateLayer({{ ...layer, ...recent, tileUrl: layer.tileUrl }})
              : layer;
          }}).filter(Boolean);
          const restoredBasemapOverlays = entry.recentLayers
            .filter(layer => isBasemapOverlayLayer(layer) && basemapMetaById(layer.sourceId))
            .map(normalizeStateLayer)
            .filter(Boolean);
          const restoredLayers = [...restoredBasemapOverlays, ...restoredGeneratedLayers];
          const restoredIds = new Set(restoredLayers.map(layer => String(layer.id)));
          // ponytail: restore at most eight remote EE layers per startup; add a queued loader if larger workspaces become common.
          pendingProfileLayers = entry.recentLayers
            .filter(layer => profileLayerCanBeRebuilt(layer) && !restoredIds.has(String(layer.id)))
            .slice(0, 8);
          if (pendingProfileLayers.length) changed = true;
          if (describeLayers(restoredLayers) !== describeLayers(STATE.layers || [])) {{
            replaceStateLayers(restoredLayers);
            changed = true;
          }}
        }}
        if (Array.isArray(entry.layerOrder)) {{
          const nextLayerOrder = entry.layerOrder.map(value => String(value));
          if (JSON.stringify(nextLayerOrder) !== JSON.stringify(operationalLayerOrder)) {{
            operationalLayerOrder = nextLayerOrder;
            operationalMapOrderDirty = true;
            changed = true;
          }}
        }}
        restoredProfileActiveLayerId = typeof entry.activeLayerId === 'string' && entry.activeLayerId.trim()
          ? entry.activeLayerId.trim()
          : null;
      }}
      if (basemapProfileChanged) {{
        if (![...BUILTIN_BASEMAPS, ...customBasemaps].some(meta => meta.id === defaultBasemapId)) defaultBasemapId = 'OSM';
        rebuildBasemapRegistry(preferredBasemap || defaultBasemapId);
        changed = true;
      }}
      return changed;
    }}
    function profileLayerCanBeRebuilt(layer) {{
      if (!layer || typeof layer !== 'object' || isBasemapOverlayLayer(layer) || layer.type === 'local-upload') return false;
      return Boolean(String(layer.dataset || '').trim() && layer.recipe && typeof layer.recipe === 'object');
    }}
    function profileRestorePlaceholder(saved) {{
      return normalizeStateLayer({{
        ...saved,
        type: 'ee-restore-pending',
        shown: saved.shown !== false,
        summary: {{ ...(saved.summary || {{}}), restorePending: true }},
      }});
    }}
    function restoreProfileMapView() {{
      if (!restoredProfileView) return false;
      map.setView(restoredProfileView.center, restoredProfileView.zoom, {{ animate: false }});
      return true;
    }}
    async function rebuildProfileLayer(saved) {{
      const datasetId = String(saved?.dataset || saved?.recipe?.datasetId || '').trim();
      if (!datasetId) return false;
      const item = datasetById(datasetId) || {{ id: datasetId, label: saved.name || datasetId, type: saved.type }};
      const recipe = saved.recipe && typeof saved.recipe === 'object' ? saved.recipe : null;
      const savedAoi = normalizeAoi(saved.aoi) || currentProcessingAoi();
      try {{
        const response = await fetch('/api/layer', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            project: STATE.project,
            datasetId,
            catalogItem: item,
            recipe,
            aoi: savedAoi,
            bounds: savedAoi?.bounds || currentProcessingBounds(),
            startDate: recipe?.startDate || saved.summary?.startDate || STATE.startDate,
            endDate: recipe?.endDate || saved.summary?.endDate || STATE.endDate,
            cloudPct: saved.summary?.cloudPct ?? STATE.cloudPct,
            name: saved.name,
            visParams: saved.visParams,
            legend: saved.legend,
            stylePreset: saved.stylePreset,
          }}),
        }});
        const payload = await response.json().catch(() => ({{ ok: false }}));
        if (!response.ok || !payload.ok || !payload.layer) return false;
        addGeneratedLayer({{
          ...payload.layer,
          id: String(saved.id || payload.layer.id),
          name: saved.name || payload.layer.name,
          opacity: Number.isFinite(Number(saved.opacity)) ? Number(saved.opacity) : payload.layer.opacity,
          styleProfile: saved.styleProfile || payload.layer.styleProfile,
          stylePreset: saved.stylePreset || payload.layer.stylePreset,
          visParams: saved.visParams || payload.layer.visParams,
          legend: saved.legend || payload.layer.legend,
          recipe: recipe || payload.layer.recipe,
          summary: saved.summary || payload.layer.summary,
          aoi: savedAoi || payload.layer.aoi,
        }}, {{ activate: false, sync: false, shown: saved.shown !== false }});
        return true;
      }} catch {{
        return false;
      }}
    }}
    async function restoreRecentProfileLayers() {{
      const layers = pendingProfileLayers;
      pendingProfileLayers = [];
      let restored = 0;
      for (const layer of layers) {{
        if (await rebuildProfileLayer(layer)) {{
          restored += 1;
          continue;
        }}
        const placeholder = profileRestorePlaceholder(layer);
        if (placeholder && !STATE.layers.some(item => item.id === placeholder.id)) {{
          STATE.layers.push(placeholder);
          registerLayer(placeholder);
        }}
      }}
      return restored;
    }}
    async function restoreProfileFromServer() {{
      try {{
        await restoreTiandituCredential();
        const response = await fetch('/api/session/profile');
        if (!response.ok) return false;
        const payload = await response.json();
        const changed = applySessionProfile(payload.profile);
        const restoredLayerCount = await restoreRecentProfileLayers();
        if (changed) {{
          renderAoiLayer();
          renderLayers();
          renderMeasurements();
          renderTasks();
          renderUploads();
          renderDatasets(filteredCatalog());
          if (!restoreProfileMapView()) resetHomeView();
          const desiredLayerId = restoredProfileActiveLayerId;
          if (desiredLayerId && layerModels().some(layer => layer?.id === desiredLayerId)) setActiveLayer(desiredLayerId, {{ reveal: false }});
          syncSessionState('profile-restored');
        }}
        return changed || restoredLayerCount > 0;
      }} catch {{
        return false;
      }}
    }}
    function showMode(message, persist = false) {{
      currentModeKey = null;
      const chip = $('mode-chip');
      chip.textContent = message;
      chip.classList.add('show');
      window.clearTimeout(showMode.timer);
      if (!persist) {{
        showMode.timer = window.setTimeout(() => chip.classList.remove('show'), 2200);
      }}
    }}
    function showModeKey(key, vars = {{}}, persist = false) {{
      currentModeKey = {{ key, vars, persist }};
      showMode(t(key, vars), persist);
      currentModeKey = {{ key, vars, persist }};
    }}
    function setToolActive(id, active) {{
      const button = $(id);
      if (button) button.classList.toggle('active', active);
    }}
    function syncMeasurementIndicator() {{
      const active = measureMode === true;
      const badge = $('active-layer-badge');
      if (badge) {{
        badge.classList.toggle('measure-active', active);
        const activeLabel = badge.dataset.activeLabel;
        if (activeLabel) {{
          const sourceHint = t('source.trigger');
          const modeHint = active ? t('tool.measureActive') : '';
          const hints = [sourceHint, modeHint].filter(Boolean).join(' · ');
          badge.title = `${{activeLabel}} · ${{hints}}`;
          badge.setAttribute('aria-label', `${{hints}} · ${{activeLabel}}`);
        }}
      }}
      const measureButton = $('measure-btn');
      if (measureButton) {{
        measureButton.classList.toggle('measure-active', active);
        measureButton.setAttribute('aria-pressed', active ? 'true' : 'false');
        const label = t(active ? 'tool.measureActive' : 'tool.measure');
        measureButton.title = label;
        measureButton.setAttribute('aria-label', label);
      }}
      const undoButton = $('measure-undo-btn');
      if (undoButton) {{
        const canUndo = measurePoints.length > 0 || (Array.isArray(STATE.measurements) && STATE.measurements.length > 0);
        undoButton.hidden = !active;
        undoButton.disabled = !canUndo;
        const label = t('tool.measureUndo');
        undoButton.title = label;
        undoButton.setAttribute('aria-label', label);
      }}
      const layersButton = $('layers-btn');
      if (layersButton) {{
        const layersOpen = document.querySelector('.layers-panel')?.classList.contains('open');
        const prompt = !layersOpen && (active || measurementLayerNotice);
        layersButton.classList.toggle('measurement-prompt', prompt);
        layersButton.classList.toggle('measurement-ready', measurementLayerNotice);
        const label = measurementLayerNotice
          ? t('tool.layersMeasurementReady')
          : prompt
            ? t('tool.layersMeasurePrompt')
            : t('tool.layers');
        layersButton.title = label;
        layersButton.setAttribute('aria-label', label);
      }}
    }}
    function collapseActiveBadge() {{
      const badge = $('active-layer-badge');
      if (!badge) return;
      badge.classList.add('collapsed');
      window.clearTimeout(activeBadgeTimer);
      activeBadgeTimer = null;
    }}
    function revealActiveBadge(duration = 2600) {{
      const badge = $('active-layer-badge');
      if (!badge) return;
      badge.classList.remove('collapsed');
      window.clearTimeout(activeBadgeTimer);
      activeBadgeTimer = null;
      if (duration > 0) {{
        activeBadgeTimer = window.setTimeout(collapseActiveBadge, duration);
      }}
    }}
    function syncToolState() {{
      setToolActive('data-btn', document.querySelector('.data-panel').classList.contains('open'));
      setToolActive('upload-btn', document.querySelector('.upload-panel').classList.contains('open'));
      setToolActive('layers-btn', document.querySelector('.layers-panel').classList.contains('open'));
      setToolActive('inspector-btn', document.querySelector('.right').classList.contains('open'));
      setToolActive('draw-aoi-btn', drawAoiMode || drawPolygonMode);
      setToolActive('measure-btn', measureMode);
      syncMeasurementIndicator();
      setToolActive('basemap-btn', document.querySelector('.basemap-panel').classList.contains('open'));
      setToolActive('quota-btn', quotaFocus && document.querySelector('.bottom').classList.contains('open'));
    }}
    function applyI18n() {{
      document.documentElement.lang = currentLang === 'zh' ? 'zh-CN' : 'en';
      document.querySelectorAll('[data-i18n]').forEach(element => {{
        element.textContent = t(element.dataset.i18n);
      }});
      document.querySelectorAll('[data-i18n-title]').forEach(element => {{
        const label = t(element.dataset.i18nTitle);
        element.title = label;
        element.setAttribute('aria-label', label);
      }});
      document.querySelectorAll('[data-i18n-placeholder]').forEach(element => {{
        element.placeholder = t(element.dataset.i18nPlaceholder);
      }});
      $('lang-code').textContent = currentLang === 'zh' ? 'EN' : '中';
      $('catalog-count').textContent = t('pill.datasets', {{ count: STATE.catalog.length }});
      $('layer-count').textContent = t('pill.layers', {{ count: layerCount() }});
      $('click-state').textContent = t(clickStateKey);
      renderCatalogFacets();
      renderQuota();
      renderTasks();
      renderUploads();
      renderTiandituAuth();
      renderBasemapChoices();
      updateInspector();
      if (currentModeKey && $('mode-chip').classList.contains('show')) {{
        $('mode-chip').textContent = t(currentModeKey.key, currentModeKey.vars);
      }}
    }}
    function layerKind(layer) {{
      if (layer.type === 'aoi') return {{ label: 'A', className: 'aoi' }};
      if (layer.type === 'measurements') return {{ label: 'M', className: 'measurements' }};
      if (layer.type === 'primary-basemap') return {{ label: 'B', className: 'basemap' }};
      if (layer.type === 'basemap-overlay') return {{ label: 'O', className: 'basemap-overlay' }};
      if (String(layer.type || '').includes('vector')) return {{ label: 'V', className: 'vector' }};
      if (layer.type.includes('categorical')) return {{ label: 'C', className: 'categorical' }};
      if (layer.type.includes('derived')) return {{ label: 'D', className: 'derived' }};
      return {{ label: 'R', className: 'raster' }};
    }}
    function distanceMeters(a, b) {{
      const toRad = value => value * Math.PI / 180;
      const earth = 6371008.8;
      const dLat = toRad(b.lat - a.lat);
      const dLng = toRad(b.lng - a.lng);
      const lat1 = toRad(a.lat);
      const lat2 = toRad(b.lat);
      const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
      return 2 * earth * Math.asin(Math.min(1, Math.sqrt(h)));
    }}
    function formatDistance(meters) {{
      return meters >= 1000 ? `${{(meters / 1000).toFixed(2)}} km` : `${{meters.toFixed(0)}} m`;
    }}
    function formatScaleDistance(meters) {{
      if (meters >= 1000) {{
        const km = meters / 1000;
        return `${{km >= 10 ? km.toFixed(0) : km.toFixed(1)}} km`;
      }}
      return `${{Math.round(meters)}} m`;
    }}
    function setClickState(key) {{
      clickStateKey = key;
      $('click-state').textContent = t(clickStateKey);
    }}
    function displayBasemapName() {{
      const meta = currentBasemapMeta();
      return meta.nameKey ? t(meta.nameKey) : String(meta.name || meta.id || 'Basemap');
    }}
    function currentBasemapMeta() {{
      return BASEMAPS.find(item => item.id === currentBasemap) || BASEMAPS[0];
    }}
    function basemapDisplayName(meta) {{
      return meta?.nameKey ? t(meta.nameKey) : String(meta?.name || meta?.id || 'Basemap');
    }}
    function basemapDisplayNote(meta) {{
      if (meta?.noteKey) return t(meta.noteKey);
      const provider = String(meta?.provider || meta?.service || '-');
      return t('basemap.customNote', {{ type: String(meta?.type || 'xyz').toUpperCase(), provider }});
    }}
    function normalizeTiandituToken(value) {{
      const token = String(value || '').trim();
      return token && !/[\s&?#]/.test(token) ? token.slice(0, 256) : '';
    }}
    function readTiandituToken() {{
      try {{ return normalizeTiandituToken(window.sessionStorage.getItem(TIANDITU_TOKEN_STORAGE_KEY)); }} catch {{ return ''; }}
    }}
    function isTiandituBasemap(meta) {{
      return Boolean(meta?.tiandituBase && meta?.tiandituLabels);
    }}
    function renderTiandituAuth() {{
      const card = $('tianditu-auth');
      const status = $('tianditu-auth-state');
      const summary = $('tianditu-auth-summary');
      const editor = $('tianditu-auth-editor');
      const input = $('tianditu-token');
      const remember = $('tianditu-token-remember');
      const persistence = $('tianditu-token-persistence');
      if (!card || !status) return;
      const configured = Boolean(tiandituToken);
      const editing = !configured || tiandituKeyEditing;
      card.classList.toggle('configured', configured);
      status.textContent = t(configured
        ? (tiandituTokenRemembered ? 'basemap.tiandituKeyReadyDevice' : 'basemap.tiandituKeyReady')
        : 'basemap.tiandituKeyMissing');
      if (summary) summary.hidden = !configured || editing;
      if (editor) editor.hidden = !editing;
      if (remember) {{
        remember.checked = tiandituTokenRemembered;
        remember.disabled = !tiandituCredentialSupported;
      }}
      if (persistence) {{
        persistence.hidden = !configured || editing || !tiandituCredentialSupported;
        persistence.textContent = t(tiandituTokenRemembered ? 'basemap.tiandituKeyForget' : 'basemap.tiandituKeyRemember');
      }}
      if (configured && !editing && input) input.value = '';
    }}
    function setTiandituAuthOpen(open) {{
      const card = $('tianditu-auth');
      const body = $('tianditu-auth-body');
      const toggle = $('tianditu-auth-toggle');
      if (!card || !body || !toggle) return false;
      card.classList.toggle('open', Boolean(open));
      body.hidden = !open;
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      return true;
    }}
    function requestTiandituToken() {{
      document.querySelector('.basemap-panel')?.classList.add('open');
      tiandituKeyEditing = true;
      renderTiandituAuth();
      setTiandituAuthOpen(true);
      $('tianditu-token')?.focus();
      showModeKey('mode.tiandituKeyRequired', {{}}, true);
      syncToolState();
      return false;
    }}
    function editTiandituToken() {{
      if (!tiandituToken) return false;
      tiandituKeyEditing = true;
      renderTiandituAuth();
      $('tianditu-token')?.focus();
      return true;
    }}
    async function restoreTiandituCredential() {{
      try {{
        const response = await fetch('/api/session/credentials/tianditu', {{ cache: 'no-store' }});
        if (!response.ok) return false;
        const payload = await response.json();
        tiandituCredentialSupported = payload.supported === true;
        const token = payload.remembered ? normalizeTiandituToken(payload.token) : '';
        if (token) {{
          tiandituToken = token;
          tiandituTokenRemembered = true;
          try {{ window.sessionStorage.setItem(TIANDITU_TOKEN_STORAGE_KEY, token); }} catch {{}}
          rebuildBasemapRegistry(currentBasemap);
          renderBasemapChoices();
        }}
        renderTiandituAuth();
        return Boolean(token);
      }} catch {{
        renderTiandituAuth();
        return false;
      }}
    }}
    async function persistTiandituCredential(token, remember) {{
      if (!tiandituCredentialSupported) return !remember;
      try {{
        const response = await fetch('/api/session/credentials/tianditu', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ token: remember ? token : '', remember: remember === true }}),
        }});
        const payload = await response.json().catch(() => ({{ ok: false }}));
        if (!response.ok || !payload.ok) return false;
        tiandituTokenRemembered = payload.remembered === true;
        return true;
      }} catch {{
        return false;
      }}
    }}
    async function toggleTiandituPersistence() {{
      if (!tiandituToken || !tiandituCredentialSupported) return false;
      const remember = !tiandituTokenRemembered;
      const saved = await persistTiandituCredential(tiandituToken, remember);
      renderTiandituAuth();
      showModeKey(saved
        ? (remember ? 'mode.tiandituKeyRemembered' : 'mode.tiandituKeySessionOnly')
        : 'mode.tiandituKeyRememberFailed', {{}}, !saved);
      return saved;
    }}
    async function applyTiandituToken() {{
      const input = $('tianditu-token');
      const token = normalizeTiandituToken(input?.value);
      if (!token) {{
        showModeKey('basemap.tiandituKeyInvalid', {{}}, true);
        input?.focus();
        return false;
      }}
      try {{ window.sessionStorage.setItem(TIANDITU_TOKEN_STORAGE_KEY, token); }} catch {{}}
      tiandituToken = token;
      const remember = $('tianditu-token-remember')?.checked === true && tiandituCredentialSupported;
      const persistenceUpdated = remember || tiandituTokenRemembered
        ? await persistTiandituCredential(token, remember)
        : true;
      tiandituKeyEditing = false;
      if (input) input.value = '';
      rebuildBasemapRegistry(currentBasemap);
      [...new Set(STATE.layers
        .filter(layer => isBasemapOverlayLayer(layer) && isTiandituBasemap(basemapMetaById(layer.sourceId)))
        .map(layer => layer.sourceId))]
        .forEach(sourceId => reloadBasemapOverlays(sourceId));
      renderTiandituAuth();
      renderBasemapChoices();
      setTiandituAuthOpen(false);
      showModeKey(persistenceUpdated
        ? (tiandituTokenRemembered ? 'mode.tiandituKeyRemembered' : 'mode.tiandituKeySaved')
        : 'mode.tiandituKeyRememberFailed', {{}}, !persistenceUpdated);
      return true;
    }}
    function basemapThumbSvg(meta) {{
      switch (meta.thumb) {{
        case 'osm':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#f1eed8"/><path d="M0 32C13 28 22 31 31 38C40 44 52 43 64 36V48H0Z" fill="#b8d4a4"/><path d="M-5 8 69 43" stroke="#fff9e7" stroke-width="9"/><path d="M-5 8 69 43" stroke="#cf6b60" stroke-width="3"/><path d="M47-6C44 12 37 29 24 54" stroke="#fff9e7" stroke-width="8"/><path d="M47-6C44 12 37 29 24 54" stroke="#d7a14d" stroke-width="2.6"/><circle cx="40" cy="22" r="3.2" fill="#fff9e7" stroke="#526e61" stroke-width="1.2"/></svg>`;
        case 'light':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#f5f7f4"/><path d="M8 0v48M25 0v48M46 0v48M0 13h64M0 31h64" stroke="#dce3de" stroke-width="1"/><path d="M-4 42C14 31 23 21 35 5C42-4 51-7 68-6" fill="none" stroke="#a9c7ba" stroke-width="5"/><path d="M-4 42C14 31 23 21 35 5C42-4 51-7 68-6" fill="none" stroke="#f9fbf9" stroke-width="2"/><path d="M17-4 55 52" stroke="#cbd5cf" stroke-width="2"/><circle cx="32" cy="9" r="2.7" fill="#6b9e85"/></svg>`;
        case 'dark':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#172425"/><path d="M9 0v48M23 0v48M43 0v48M56 0v48M0 11h64M0 27h64M0 40h64" stroke="#314142" stroke-width="1"/><path d="M-8 44C9 33 18 31 30 19C40 9 47 5 70 4" fill="none" stroke="#59c8ad" stroke-width="3.2"/><path d="M16-6 48 55" stroke="#6577c4" stroke-width="3.4"/><circle cx="30" cy="19" r="3.2" fill="#d0f1e6" stroke="#172425" stroke-width="1.5"/></svg>`;
        case 'voyager':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#eee3c9"/><path d="M0 32C11 26 23 27 32 35C42 43 52 44 64 40V48H0Z" fill="#b9d4b2"/><path d="M-5 7 69 39" stroke="#fff3d8" stroke-width="8"/><path d="M-5 7 69 39" stroke="#e78663" stroke-width="3"/><path d="M48-5C43 12 34 29 19 52" fill="none" stroke="#f8edcf" stroke-width="7"/><path d="M48-5C43 12 34 29 19 52" fill="none" stroke="#75a9b8" stroke-width="2.8"/><path d="M5 16h13v10H5zM48 27h12v9H48z" fill="#e4cda6" stroke="#c9b58f" stroke-width="1"/></svg>`;
        case 'topo':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#e9e4c7"/><path d="M-5 36C6 18 17 10 31 12C44 14 51 28 69 20" fill="none" stroke="#a99365" stroke-width="1.4"/><path d="M-4 42C8 22 18 16 31 18C43 20 51 33 68 27" fill="none" stroke="#b29c6e" stroke-width="1.25"/><path d="M4 47C14 30 22 24 32 25C42 26 49 38 61 34" fill="none" stroke="#b9a678" stroke-width="1.1"/><path d="M11 0C17 8 20 11 29 8C38 4 45 3 55 10C59 13 62 15 67 14" fill="none" stroke="#8da27c" stroke-width="2.2"/><path d="m31 17 5 9H26Z" fill="#7d6c4b"/><circle cx="31" cy="17" r="2" fill="#f7f0d5"/></svg>`;
        case 'imagery':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#284336"/><path d="M0 0h30L18 22 0 19Z" fill="#3f6b47"/><path d="m30 0 20 0 4 20-19 7-17-5Z" fill="#6d7645"/><path d="m50 0 14 0v28l-10-8Z" fill="#947b50"/><path d="M0 19 18 22l7 26H0Z" fill="#4f7a4b"/><path d="m18 22 17 5 8 21H25Z" fill="#8b8258"/><path d="m35 27 19-7 10 8v20H43Z" fill="#45634b"/><path d="M42-5C37 9 38 24 47 53" fill="none" stroke="#366779" stroke-width="4"/><path d="M42-5C37 9 38 24 47 53" fill="none" stroke="#7aa3a5" stroke-opacity=".55" stroke-width="1"/></svg>`;
        case 'clarity':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#858d69"/><path d="M0 0h24L19 18 0 14ZM24 0h22l-6 16-21 2ZM46 0h18v20l-24-4ZM0 14l19 4 5 18-24 7ZM19 18l21-2 5 19-21 1ZM40 16l24 4v20l-19-5ZM0 43l24-7 4 12H0ZM24 36l21-1 9 13H28ZM45 35l19 5v8H54Z" fill="none" stroke="#dfe2bd" stroke-opacity=".66" stroke-width="1.1"/><path d="M8 7h17v10H8z" fill="#cbd8a3"/><path d="M35 25h20v12H35z" fill="#687b58"/><path d="M-3 31 68 8" stroke="#e8e0b8" stroke-width="2.2"/></svg>`;
        case 'tianditu-vector':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#edf2de"/><path d="M0 34c12-8 22-8 32-1s20 8 32 3v12H0Z" fill="#c5ddae"/><path d="M-5 9 69 40" stroke="#fff9df" stroke-width="7"/><path d="M-5 9 69 40" stroke="#d46f5e" stroke-width="2.2"/><path d="M49-5C44 10 37 26 21 53" fill="none" stroke="#f9f6dc" stroke-width="7"/><path d="M49-5C44 10 37 26 21 53" fill="none" stroke="#6ba8bd" stroke-width="2.4"/><circle cx="36" cy="21" r="2.8" fill="#fff" stroke="#507461"/></svg>`;
        case 'tianditu-imagery':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#315342"/><path d="M0 0h25L17 21 0 17ZM25 0h21l-7 18-22 3ZM46 0h18v22l-25-4ZM0 17l17 4 7 27H0ZM17 21l22-3 7 30H24ZM39 18l25 4v26H46Z" fill="none" stroke="#8fa56b" stroke-width="1.2"/><path d="M-4 39C15 31 23 19 34 21c11 2 15 12 34-4" fill="none" stroke="#8bc9c4" stroke-width="3"/><path d="M-4 39C15 31 23 19 34 21c11 2 15 12 34-4" fill="none" stroke="#e8df9c" stroke-width="1"/></svg>`;
        case 'tianditu-terrain':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#ded8b7"/><path d="M-7 39C8 18 20 11 34 15c12 3 17 15 37 5" fill="none" stroke="#9c8b5f" stroke-width="1.5"/><path d="M-6 45C10 25 21 18 34 21c12 3 18 15 36 10" fill="none" stroke="#aa986b" stroke-width="1.25"/><path d="M5 49c11-15 20-21 30-20 11 1 17 11 27 11" fill="none" stroke="#b7a779" stroke-width="1"/><path d="M4 4c12 9 19 11 27 6 9-6 17-6 30 3" fill="none" stroke="#7f9f7b" stroke-width="2.4"/><path d="m33 15 5 9H28Z" fill="#766445"/></svg>`;
        case 'custom-xyz':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#dcebe2"/><path d="M0 13h64M0 34h64M17 0v48M45 0v48" stroke="#aac7b7" stroke-width="1"/><path d="M-6 41C12 30 22 17 34 18c10 1 18 12 36-8" fill="none" stroke="#3f8c69" stroke-width="4"/><circle cx="34" cy="18" r="3.5" fill="#f4c968" stroke="#fff" stroke-width="1.5"/></svg>`;
        case 'custom-tms':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#ebe3cf"/><path d="M8 6h17v15H8zM39 6h17v15H39zM8 27h17v15H8zM39 27h17v15H39z" fill="#d8c89e" stroke="#9c8962"/><path d="m32 9 5 6h-3v18h3l-5 6-5-6h3V15h-3Z" fill="#6f947d"/></svg>`;
        case 'custom-arcgis':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#dce7ef"/><path d="M7 36 21 12l11 18L43 7l14 29Z" fill="#6d9a86" opacity=".78"/><path d="M5 39h54" stroke="#426f87" stroke-width="2"/><circle cx="44" cy="13" r="6" fill="none" stroke="#f2b84b" stroke-width="2"/><path d="m48 17 6 6" stroke="#f2b84b" stroke-width="2"/></svg>`;
        case 'custom-wms':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#dfe8ec"/><path d="M7 10h35v24H7z" fill="#b8d3c5" stroke="#5f8975"/><path d="M15 17c7-7 15 9 23 0v11c-8 9-16-8-23 0Z" fill="#5f9eb1" opacity=".85"/><path d="m38 31 9 9 11-18" fill="none" stroke="#d2a847" stroke-width="4"/></svg>`;
        case 'custom-wmts':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#e1e8dc"/><g fill="#aac5b3" stroke="#668774"><path d="M7 6h15v15H7zM25 6h15v15H25zM43 6h14v15H43zM7 24h15v18H7zM25 24h15v18H25zM43 24h14v18H43z"/></g><path d="M11 35c11-11 19-5 27-14 6-6 11-5 19-10" fill="none" stroke="#f5e8bd" stroke-width="3"/></svg>`;
        case 'custom-pmtiles':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" rx="7" fill="#193342"/><path d="M7 11h22v14H7zM35 7h22v14H35zM10 30h19v11H10zM35 27h22v14H35z" fill="#315464" stroke="#7894a0" stroke-width=".8"/><path d="M-4 38C9 32 15 19 27 20c11 1 15 10 24 7 7-2 10-9 17-11" fill="none" stroke="#63c6aa" stroke-width="3.1"/><path d="M4 42C17 35 21 24 31 25c10 1 16 8 29-2" fill="none" stroke="#f2bc72" stroke-width="1.4"/><circle cx="49" cy="13" r="4.5" fill="#e9f2ee"/><path d="M47 13h4M49 11v4" stroke="#315464" stroke-width="1.2"/></svg>`;
        case 'custom-cog':
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><defs><linearGradient id="cog-g" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#17343c"/><stop offset=".52" stop-color="#27685f"/><stop offset="1" stop-color="#d6a960"/></linearGradient></defs><rect width="64" height="48" rx="7" fill="url(#cog-g)"/><path d="M-5 39C8 28 18 33 28 22S45 6 69 13" fill="none" stroke="#d9f0d5" stroke-opacity=".78" stroke-width="2.2"/><path d="M-4 44C11 34 20 39 31 28S49 12 68 19" fill="none" stroke="#f2cf83" stroke-opacity=".8" stroke-width="1.2"/><g fill="none" stroke="#f4faf6" stroke-width="1.1"><path d="M9 9h13v10H9zM26 9h13v10H26zM43 9h12v10H43zM9 23h13v10H9z"/></g><circle cx="49" cy="34" r="7" fill="#102f35" fill-opacity=".78"/><path d="M46 34h6M49 31v6" stroke="#eaf7f1" stroke-width="1.4"/></svg>`;
        default:
          return `<svg viewBox="0 0 64 48" aria-hidden="true"><rect width="64" height="48" fill="#dfe8e2"/><path d="M-4 39C12 23 25 17 39 20C49 22 57 17 68 7" fill="none" stroke="#5f9278" stroke-width="4"/></svg>`;
      }}
    }}
    function setBasemapVisual(element, meta) {{
      if (!element || !meta) return;
      if (element.dataset.thumb) element.classList.remove(element.dataset.thumb);
      element.dataset.thumb = meta.thumb || 'custom-xyz';
      element.classList.add(element.dataset.thumb);
      element.innerHTML = basemapThumbSvg(meta);
    }}
    function setActiveBadgeLabel(label) {{
      const badge = $('active-layer-badge');
      if (!badge) return;
      badge.dataset.activeLabel = label;
      const sourceHint = t('source.trigger');
      const modeHint = measureMode ? t('tool.measureActive') : '';
      const hints = [sourceHint, modeHint].filter(Boolean).join(' · ');
      badge.title = `${{label}} · ${{hints}}`;
      badge.setAttribute('aria-label', `${{hints}} · ${{label}}`);
    }}
    function formatBasemapDuration(value) {{
      const milliseconds = Number(value);
      if (!Number.isFinite(milliseconds) || milliseconds < 0) return '-';
      if (milliseconds < 1000) return `${{Math.round(milliseconds)}} ms`;
      return `${{(milliseconds / 1000).toFixed(milliseconds < 10000 ? 1 : 0).replace(/[.]0$/, '')}} s`;
    }}
    function formatBasemapBytes(value) {{
      const bytes = Number(value);
      if (!Number.isFinite(bytes) || bytes < 0) return '-';
      if (bytes < 1024) return `${{Math.round(bytes)}} B`;
      if (bytes < 1024 * 1024) return `${{(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0).replace(/[.]0$/, '')}} KB`;
      return `${{(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0).replace(/[.]0$/, '')}} MB`;
    }}
    function basemapCacheLabel(cache) {{
      if (cache === 'cold') return t('source.cacheCold');
      if (cache === 'warm') return t('source.cacheWarm');
      return t('source.cacheUnknown');
    }}
    function renderBasemapPerformanceDetails(meta) {{
      const diagnostics = publicBasemapPerformance(meta);
      const performanceTarget = $('basemap-source-performance');
      const deliveryTarget = $('basemap-source-delivery');
      if (!diagnostics) {{
        performanceTarget.textContent = t('source.performanceIdle');
        deliveryTarget.textContent = t('source.deliveryIdle');
        return;
      }}
      const first = Number.isFinite(diagnostics.firstRenderMs) ? formatBasemapDuration(diagnostics.firstRenderMs) : null;
      const ready = Number.isFinite(diagnostics.readyMs) ? formatBasemapDuration(diagnostics.readyMs) : null;
      if (diagnostics.status === 'error') performanceTarget.textContent = t('source.performanceFailed');
      else if (ready) performanceTarget.textContent = t('source.performanceReady', {{ first: first || ready, ready }});
      else if (first) performanceTarget.textContent = t('source.performanceSettling', {{ first }});
      else performanceTarget.textContent = t('source.performanceLoading');

      const cache = basemapCacheLabel(diagnostics.cache);
      if (diagnostics.status === 'loading') {{
        deliveryTarget.textContent = t('source.deliveryLoading', {{ cache }});
        return;
      }}
      const delivery = [cache];
      if (Number.isFinite(diagnostics.renderedBlocks) && diagnostics.renderedBlocks > 0) {{
        delivery.push(t('source.renderedBlocks', {{ count: diagnostics.renderedBlocks }}));
      }}
      if (Number.isFinite(diagnostics.sourceRequests)) {{
        delivery.push(t('source.sourceRequests', {{ count: diagnostics.sourceRequests }}));
      }}
      if (Number.isFinite(diagnostics.transferredBytes)) delivery.push(formatBasemapBytes(diagnostics.transferredBytes));
      else delivery.push(t('source.networkRestricted'));
      deliveryTarget.textContent = delivery.join(' · ');
    }}
    function renderBasemapSourceDetails() {{
      const meta = (basemapSourceDetailId && BASEMAPS.find(item => item.id === basemapSourceDetailId)) || currentBasemapMeta();
      setBasemapVisual($('basemap-source-visual'), meta);
      $('basemap-source-name').textContent = basemapDisplayName(meta);
      $('basemap-source-service').textContent = meta.serviceKey ? t(meta.serviceKey) : (meta.service || basemapDisplayNote(meta));
      $('basemap-source-provider').textContent = meta.provider || basemapAttributionText(meta);
      $('basemap-source-engine').textContent = basemapEngineLabel(meta);
      renderBasemapPerformanceDetails(meta);
      const dateRow = $('basemap-source-date-row');
      const hasDate = Boolean(meta.sourceDate);
      dateRow.hidden = !hasDate;
      $('basemap-source-date').textContent = hasDate ? meta.sourceDate : '';
      const nativeZoom = Number(meta.options?.maxNativeZoom ?? meta.options?.maxZoom);
      $('basemap-source-zoom').textContent = Number.isFinite(nativeZoom)
        ? t('source.nativeZoomValue', {{ zoom: nativeZoom }})
        : '-';
      $('basemap-source-attribution').textContent = basemapAttributionText(meta) || '-';
      const sourceLink = $('basemap-source-link');
      sourceLink.href = meta.sourceUrl || '#';
      sourceLink.hidden = !meta.sourceUrl;
    }}
    function setBasemapSourceOpen(open, sourceId = null) {{
      basemapSourceOpen = Boolean(open);
      basemapSourceDetailId = basemapSourceOpen ? String(sourceId || currentBasemap) : null;
      const card = $('basemap-source-card');
      const badge = $('active-layer-badge');
      card.classList.toggle('open', basemapSourceOpen);
      card.setAttribute('aria-hidden', basemapSourceOpen ? 'false' : 'true');
      badge.setAttribute('aria-expanded', basemapSourceOpen ? 'true' : 'false');
      badge.classList.toggle('source-open', basemapSourceOpen);
      if (basemapSourceOpen) {{
        renderBasemapSourceDetails();
        revealActiveBadge(0);
      }} else {{
        collapseActiveBadge();
      }}
    }}
    function basemapAttributionText(meta = currentBasemapMeta()) {{
      const holder = document.createElement('span');
      holder.innerHTML = String((meta.options && meta.options.attribution) || '');
      return (holder.textContent || holder.innerText || '').replace(/\s+/g, ' ').trim();
    }}
    function basemapEngineLabel(meta) {{
      const type = String(meta?.type || 'xyz').toLowerCase();
      if (meta?.custom && type === 'pmtiles') return 'PMTiles {PMTILES_VERSION} · HTTP Range';
      if (meta?.custom && type === 'cog') return 'MapLibre {MAPLIBRE_VERSION} · COG {COG_PROTOCOL_VERSION} · WebGL / HTTP Range';
      if (meta?.custom) return `Leaflet · ${{type.toUpperCase()}}`;
      return 'Leaflet · XYZ tiles';
    }}
    function displayBasemapSource() {{
      const attribution = basemapAttributionText();
      const name = displayBasemapName();
      return attribution ? `${{name}} - ${{attribution}}` : name;
    }}
    function compactBasemapBadge() {{
      return t('badge.basemap', {{ basemap: displayBasemapName() }});
    }}
    function fullBasemapBadge() {{
      return t('badge.basemapSource', {{ source: displayBasemapSource() }});
    }}
    function layerBadgeDataset(dataset) {{
      return `${{dataset}} · ${{compactBasemapBadge()}}`;
    }}
    function layerBadgeTitle(name, dataset) {{
      return `${{name}} - ${{dataset}} | ${{fullBasemapBadge()}}`;
    }}
    function renderBasemapChoices() {{
      const current = $('basemap-current');
      if (current) current.textContent = displayBasemapName();
      const count = $('basemap-custom-count');
      if (count) count.textContent = t('basemap.customCount', {{ count: customBasemaps.length }});
      const list = $('basemap-list');
      if (list) {{
        list.innerHTML = BASEMAPS.map(meta => {{
          const customIndex = customBasemaps.findIndex(item => item.id === meta.id);
          const isCustom = customIndex >= 0;
          const isDefault = meta.id === defaultBasemapId;
          const hasOverlay = STATE.layers.some(layer => isBasemapOverlayLayer(layer) && layer.sourceId === meta.id);
          const overlayLabel = t(hasOverlay ? 'basemap.overlayInLayers' : 'basemap.addOverlay');
          const overlayAction = `<button class="basemap-overlay-add" data-basemap-overlay="${{escapeHtml(meta.id)}}" type="button" title="${{escapeHtml(overlayLabel)}}" aria-label="${{escapeHtml(overlayLabel)}}" ${{hasOverlay ? 'disabled' : ''}}>{svg_icon("overlay-add")}<span>${{escapeHtml(overlayLabel)}}</span></button>`;
          const customActions = isCustom ? `
            <div class="basemap-custom-actions">
              <button class="basemap-entry-action" data-basemap-up="${{escapeHtml(meta.id)}}" type="button" title="${{escapeHtml(t('basemap.moveUp'))}}" aria-label="${{escapeHtml(t('basemap.moveUp'))}}" ${{customIndex === 0 ? 'disabled' : ''}}>{svg_icon("up")}</button>
              <button class="basemap-entry-action" data-basemap-down="${{escapeHtml(meta.id)}}" type="button" title="${{escapeHtml(t('basemap.moveDown'))}}" aria-label="${{escapeHtml(t('basemap.moveDown'))}}" ${{customIndex === customBasemaps.length - 1 ? 'disabled' : ''}}>{svg_icon("down")}</button>
              <button class="basemap-entry-action" data-basemap-edit="${{escapeHtml(meta.id)}}" type="button" title="${{escapeHtml(t('basemap.edit'))}}" aria-label="${{escapeHtml(t('basemap.edit'))}}">{svg_icon("edit")}</button>
              <button class="basemap-entry-action danger" data-basemap-remove="${{escapeHtml(meta.id)}}" type="button" title="${{escapeHtml(t('basemap.remove'))}}" aria-label="${{escapeHtml(t('basemap.remove'))}}">{svg_icon("trash")}</button>
            </div>` : '';
          return `
            <div class="basemap-entry ${{meta.id === currentBasemap ? 'active' : ''}}">
              <button class="basemap-entry-default ${{isDefault ? 'active' : ''}}" data-basemap-default="${{escapeHtml(meta.id)}}" type="button" title="${{escapeHtml(t(isDefault ? 'basemap.defaultCurrent' : 'basemap.defaultTitle'))}}" aria-label="${{escapeHtml(t(isDefault ? 'basemap.defaultCurrent' : 'basemap.defaultTitle'))}}">{svg_icon("favorite")}</button>
              <button class="basemap-choice" data-basemap="${{escapeHtml(meta.id)}}" type="button">
                <span class="basemap-thumb ${{escapeHtml(meta.thumb)}}" aria-hidden="true">${{basemapThumbSvg(meta)}}</span>
                <span class="basemap-copy">
                  <span class="basemap-name">${{escapeHtml(basemapDisplayName(meta))}}</span>
                  <span class="basemap-note">${{escapeHtml(basemapDisplayNote(meta))}}</span>
                  ${{isCustom ? `<span class="basemap-type-chip">${{escapeHtml(String(meta.type || 'xyz'))}}</span>` : ''}}
                </span>
              </button>
              <div class="basemap-entry-footer">${{overlayAction}}${{customActions}}</div>
            </div>`;
        }}).join('');
        list.querySelectorAll('.basemap-choice').forEach(button => {{
          button.addEventListener('click', () => {{
            if (setBasemap(button.dataset.basemap)) {{
              document.querySelector('.basemap-panel').classList.remove('open');
              syncToolState();
            }}
          }});
        }});
        list.querySelectorAll('[data-basemap-overlay]').forEach(button => {{
          button.addEventListener('click', () => addBasemapOverlay(button.dataset.basemapOverlay));
        }});
        list.querySelectorAll('[data-basemap-default]').forEach(button => {{
          button.addEventListener('click', () => setDefaultBasemap(button.dataset.basemapDefault));
        }});
        list.querySelectorAll('[data-basemap-edit]').forEach(button => {{
          button.addEventListener('click', () => openBasemapEditor(button.dataset.basemapEdit));
        }});
        list.querySelectorAll('[data-basemap-up]').forEach(button => {{
          button.addEventListener('click', () => moveCustomBasemap(button.dataset.basemapUp, -1));
        }});
        list.querySelectorAll('[data-basemap-down]').forEach(button => {{
          button.addEventListener('click', () => moveCustomBasemap(button.dataset.basemapDown, 1));
        }});
        list.querySelectorAll('[data-basemap-remove]').forEach(button => {{
          button.addEventListener('click', () => removeCustomBasemap(button.dataset.basemapRemove));
        }});
      }}
      const title = `${{t('tool.basemap')}} - ${{displayBasemapName()}}`;
      $('basemap-btn').title = title;
      $('basemap-btn').setAttribute('aria-label', title);
      renderBasemapSourceDetails();
    }}
    function createCustomBasemapId(name) {{
      const slug = String(name || 'basemap').trim().toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48) || 'basemap';
      const base = customBasemapIdentifier(`custom-${{slug}}`);
      let candidate = base;
      let suffix = 2;
      while (customBasemaps.some(meta => meta.id === candidate)) {{
        candidate = `${{base.slice(0, 70)}}-${{suffix}}`;
        suffix += 1;
      }}
      return candidate;
    }}
    function setBasemapFormStatus(key = '', vars = {{}}, tone = '') {{
      const status = $('basemap-form-status');
      if (!status) return;
      status.textContent = key ? t(key, vars) : '';
      status.className = `basemap-form-status${{tone ? ` ${{tone}}` : ''}}`;
    }}
    function updateBasemapTypeFields() {{
      const type = String($('basemap-form-type')?.value || 'xyz');
      document.querySelectorAll('.basemap-type-field').forEach(field => {{
        const supported = String(field.dataset.basemapTypes || '').split(',');
        field.hidden = !supported.includes(type);
      }});
      const url = $('basemap-form-url');
      if (url) url.placeholder = type === 'arcgis'
        ? 'https://.../ArcGIS/rest/services/.../MapServer'
        : type === 'wms'
          ? 'https://.../wms'
          : type === 'wmts'
            ? 'https://.../wmts'
            : type === 'pmtiles'
              ? 'https://.../imagery.pmtiles'
              : type === 'cog'
                ? 'https://.../imagery-cog.tif'
              : 'https://.../{{z}}/{{x}}/{{y}}.png';
    }}
    function closeBasemapEditor() {{
      const editor = $('basemap-editor');
      if (editor) editor.hidden = true;
      basemapEditorId = null;
      testedBasemapSignature = '';
      testedCogDetails = null;
      if ($('basemap-save-btn')) $('basemap-save-btn').disabled = true;
      setBasemapFormStatus();
    }}
    function openBasemapEditor(id = null) {{
      const meta = id ? customBasemaps.find(item => item.id === id) : null;
      basemapEditorId = meta?.id || null;
      testedCogDetails = meta?.type === 'cog'
        ? {{ url: meta.url, bounds: meta.bounds, crs: meta.crs || 'EPSG:3857', bandCount: meta.bandCount || 0 }}
        : null;
      $('basemap-editor').hidden = false;
      $('basemap-editor-title').textContent = t(meta ? 'basemap.editorEdit' : 'basemap.editorAdd');
      $('basemap-form-name').value = meta?.name || '';
      $('basemap-form-type').value = meta?.type || 'xyz';
      $('basemap-form-provider').value = meta?.provider || '';
      $('basemap-form-url').value = meta?.url || '';
      $('basemap-form-subdomains').value = meta?.subdomains || '';
      $('basemap-form-layers').value = meta?.layers || '';
      $('basemap-form-styles').value = meta?.styles || '';
      $('basemap-form-version').value = meta?.type === 'wms' && meta?.version === '1.1.1' ? '1.1.1' : '1.3.0';
      $('basemap-form-matrix-set').value = meta?.tileMatrixSet || 'GoogleMapsCompatible';
      $('basemap-form-matrix-prefix').value = meta?.matrixPrefix || '';
      $('basemap-form-format').value = meta?.format || 'image/png';
      $('basemap-form-attribution').value = meta?.attribution || '';
      $('basemap-form-source-url').value = meta?.sourceUrl || '';
      $('basemap-form-min-zoom').value = meta?.minZoom ?? 0;
      $('basemap-form-max-zoom').value = meta?.maxZoom ?? 19;
      $('basemap-form-native-zoom').value = meta?.maxNativeZoom ?? 19;
      $('basemap-form-default').checked = Boolean(meta && meta.id === defaultBasemapId);
      testedBasemapSignature = '';
      $('basemap-save-btn').disabled = true;
      setBasemapFormStatus();
      updateBasemapTypeFields();
      $('basemap-form-name').focus();
      $('basemap-editor').scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
    }}
    function readBasemapForm() {{
      const type = String($('basemap-form-type').value || 'xyz').toLowerCase();
      const url = $('basemap-form-url').value;
      const cogDetails = type === 'cog' && testedCogDetails?.url === String(url || '').trim()
        ? testedCogDetails
        : {{}};
      return normalizeCustomBasemap({{
        id: basemapEditorId || createCustomBasemapId($('basemap-form-name').value),
        name: $('basemap-form-name').value,
        type,
        provider: $('basemap-form-provider').value,
        url,
        subdomains: $('basemap-form-subdomains').value,
        layers: $('basemap-form-layers').value,
        styles: $('basemap-form-styles').value,
        version: type === 'wmts' ? '1.0.0' : $('basemap-form-version').value,
        tileMatrixSet: $('basemap-form-matrix-set').value,
        matrixPrefix: $('basemap-form-matrix-prefix').value,
        format: $('basemap-form-format').value,
        attribution: $('basemap-form-attribution').value,
        sourceUrl: $('basemap-form-source-url').value,
        minZoom: $('basemap-form-min-zoom').value,
        maxZoom: $('basemap-form-max-zoom').value,
        maxNativeZoom: $('basemap-form-native-zoom').value,
        ...cogDetails,
        transparent: true,
      }});
    }}
    function validHttpTemplate(value) {{
      try {{
        const parsed = new URL(String(value || '').replace(/\{{[^}}]+\}}/g, 'tile'));
        return parsed.protocol === 'http:' || parsed.protocol === 'https:';
      }} catch {{
        return false;
      }}
    }}
    const SENSITIVE_URL_QUERY_NAMES = new Set(['access_key', 'access_token', 'accesskey', 'api_key', 'apikey', 'app_key', 'appkey', 'auth', 'authorization', 'client_secret', 'credential', 'key', 'passwd', 'password', 'private_key', 'secret', 'sig', 'signature', 'subscription_key', 'tk', 'token']);
    function sensitiveUrlParameterName(value) {{
      const name = String(value || '').trim().toLowerCase().replace(/-/g, '_');
      return SENSITIVE_URL_QUERY_NAMES.has(name) || ['_credential', '_key', '_password', '_secret', '_signature', '_token'].some(suffix => name.endsWith(suffix));
    }}
    function urlContainsCredentials(value) {{
      const text = String(value || '').trim();
      if (!text) return false;
      try {{
        const parsed = new URL(text.replace(/\{{[^}}]+\}}/g, 'tile'));
        if (parsed.username || parsed.password) return true;
        const parameterNames = `${{parsed.search.slice(1)}}&${{parsed.hash.slice(1)}}`
          .split(/[&;]/)
          .map(part => part.split('=', 1)[0]);
        return parameterNames.some(raw => {{
          let key = String(raw || '').replace(/\+/g, ' ');
          for (let count = 0; count < 2; count += 1) {{
            try {{ key = decodeURIComponent(key); }} catch {{ break; }}
          }}
          return sensitiveUrlParameterName(key);
        }});
      }} catch {{
        return false;
      }}
    }}
    function validateBasemapForm(meta) {{
      if (!String($('basemap-form-name').value || '').trim()) return 'basemap.nameRequired';
      const url = String($('basemap-form-url').value || '').trim();
      if (!url) return 'basemap.urlRequired';
      if (urlContainsCredentials(url) || urlContainsCredentials($('basemap-form-source-url').value)) return 'basemap.urlCredentialsBlocked';
      if (!meta || !validHttpTemplate(url)) return 'basemap.urlInvalid';
      if ((meta.type === 'xyz' || meta.type === 'tms') && !['{{z}}', '{{x}}', '{{y}}'].every(token => url.includes(token))) return 'basemap.urlInvalid';
      if ((meta.type === 'wms' || meta.type === 'wmts') && !meta.layers) return 'basemap.layersRequired';
      if (meta.type === 'wmts' && !meta.tileMatrixSet) return 'basemap.matrixRequired';
      return '';
    }}
    function invalidateBasemapTest() {{
      testedBasemapSignature = '';
      testedCogDetails = null;
      if ($('basemap-save-btn')) $('basemap-save-btn').disabled = true;
      setBasemapFormStatus();
    }}
    function testBasemapLayer(meta) {{
      return new Promise(resolve => {{
        let layer = null;
        let finished = false;
        let errors = 0;
        const finish = (ok, key) => {{
          if (finished) return;
          finished = true;
          window.clearTimeout(timer);
          window.setTimeout(() => {{
            if (layer && map.hasLayer(layer)) map.removeLayer(layer);
          }}, 0);
          resolve({{ ok, key }});
        }};
        const timer = window.setTimeout(() => finish(false, 'basemap.tileTimeout'), meta.type === 'cog' ? 15000 : 8000);
        try {{
          layer = createBasemapLayer(meta, {{ opacity: 0.001, maxZoom: Math.max(meta.maxZoom || 19, map.getZoom()), zIndex: -100 }});
          layer.on('tileload', () => finish(true, 'basemap.testPassed'));
          layer.on('tileerror', () => {{
            errors += 1;
            if (errors >= 4) finish(false, 'basemap.tileFailed');
          }});
          layer.addTo(map);
        }} catch {{
          finish(false, 'basemap.tileFailed');
        }}
      }});
    }}
    function currentViewTileCoordinates(zoom) {{
      const pixelBounds = map.getPixelBounds();
      const min = pixelBounds.min.divideBy(256).floor();
      const max = pixelBounds.max.divideBy(256).floor();
      const worldWidth = Math.pow(2, zoom);
      const coordinates = [];
      const seen = new Set();
      for (let y = min.y; y <= max.y; y += 1) {{
        if (y < 0 || y >= worldWidth) continue;
        for (let x = min.x; x <= max.x; x += 1) {{
          const wrappedX = ((x % worldWidth) + worldWidth) % worldWidth;
          const key = `${{zoom}}/${{wrappedX}}/${{y}}`;
          if (!seen.has(key)) {{
            seen.add(key);
            coordinates.push({{ z: zoom, x: wrappedX, y }});
          }}
        }}
      }}
      return coordinates.slice(0, 64);
    }}
    async function pmtilesHasVisibleRasterTile(archive, zoom) {{
      const coordinates = currentViewTileCoordinates(zoom);
      if (!coordinates.length) return false;
      let cursor = 0;
      let found = false;
      const worker = async () => {{
        while (!found && cursor < coordinates.length) {{
          const coordinate = coordinates[cursor];
          cursor += 1;
          const tile = await archive.getZxy(coordinate.z, coordinate.x, coordinate.y);
          if (tile?.data?.byteLength > 0) found = true;
        }}
      }};
      await Promise.all(Array.from({{ length: Math.min(4, coordinates.length) }}, worker));
      return found;
    }}
    async function inspectPmtilesArchive(meta, options = {{}}) {{
      if (!window.pmtiles?.PMTiles || !window.pmtiles?.leafletRasterLayer) {{
        return {{ ok: false, key: 'basemap.pmtilesUnavailable' }};
      }}
      let timeoutId = null;
      const timeout = new Promise(resolve => {{
        timeoutId = window.setTimeout(() => resolve({{ ok: false, key: 'basemap.pmtilesInspectFailed' }}), 10000);
      }});
      try {{
        const archive = getPmtilesArchive(meta.url, {{ refresh: options.refresh === true }});
        const inspection = (async () => {{
          const header = await archive.getHeader();
          if (![2, 3, 4, 5].includes(Number(header?.tileType))) {{
            return {{ ok: false, key: 'basemap.pmtilesRasterOnly' }};
          }}
          if (options.requireVisibleTile !== false) {{
            const zoom = Math.round(map.getZoom());
            if (zoom < Number(header.minZoom) || zoom > Number(header.maxZoom)) {{
              return {{ ok: false, key: 'basemap.pmtilesZoomOutside' }};
            }}
            const bounds = [header?.minLat, header?.minLon, header?.maxLat, header?.maxLon].map(Number);
            if (bounds.every(Number.isFinite)) {{
              const coverage = L.latLngBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]]);
              if (!map.getBounds().intersects(coverage)) return {{ ok: false, key: 'basemap.pmtilesOutsideView' }};
            }}
            if (!await pmtilesHasVisibleRasterTile(archive, zoom)) {{
              return {{ ok: false, key: 'basemap.pmtilesNoTile' }};
            }}
          }}
          return {{ ok: true, header }};
        }})();
        const result = await Promise.race([inspection, timeout]);
        if (!result.ok) discardPmtilesArchive(meta.url);
        return result;
      }} catch {{
        discardPmtilesArchive(meta.url);
        return {{ ok: false, key: 'basemap.pmtilesInspectFailed' }};
      }} finally {{
        if (timeoutId !== null) window.clearTimeout(timeoutId);
      }}
    }}
    async function inspectCogSource(meta, options = {{}}) {{
      let timeoutId = null;
      const timeout = new Promise(resolve => {{
        timeoutId = window.setTimeout(() => resolve({{ ok: false, key: 'basemap.cogInspectFailed' }}), 20000);
      }});
      try {{
        const inspection = (async () => {{
          await ensureCogEngine();
          const metadata = await getCogSourceMetadata(meta.url, {{ refresh: options.refresh === true }});
          const bounds = normalizeBasemapBounds(metadata?.bbox);
          const zooms = (Array.isArray(metadata?.images) ? metadata.images : [])
            .filter(image => !image?.isMask)
            .map(image => Number(image?.zoom))
            .filter(Number.isFinite);
          const maxZoom = zooms.length ? Math.max(...zooms) : Number(meta.maxNativeZoom || meta.maxZoom || 19);
          const bandCount = Array.isArray(metadata?.bitsPerSample) ? metadata.bitsPerSample.length : Number(meta.bandCount || 0);
          const details = {{
            url: meta.url,
            ...(bounds ? {{ bounds }} : {{}}),
            crs: 'EPSG:3857',
            bandCount,
            minZoom: 0,
            maxZoom: basemapZoom(maxZoom, 19),
            maxNativeZoom: basemapZoom(maxZoom, 19),
          }};
          const checkedMeta = normalizeCustomBasemap({{ ...meta, ...details }});
          if (!checkedMeta) return {{ ok: false, key: 'basemap.cogInspectFailed' }};
          if (options.requireVisibleTile !== false) {{
            if (bounds) {{
              const coverage = L.latLngBounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]]);
              if (!map.getBounds().intersects(coverage)) {{
                if (options.fitBounds === false) return {{ ok: false, key: 'basemap.cogOutsideView' }};
                await new Promise(resolve => {{
                  let finished = false;
                  const finish = () => {{
                    if (finished) return;
                    finished = true;
                    map.off('moveend', finish);
                    resolve();
                  }};
                  map.once('moveend', finish);
                  map.fitBounds(coverage, {{ padding: [42, 42], maxZoom: Math.min(details.maxNativeZoom, 17) }});
                  window.setTimeout(finish, 1400);
                }});
              }}
            }}
            const tileResult = await testBasemapLayer(checkedMeta);
            if (!tileResult.ok) return tileResult;
          }}
          return {{ ok: true, metadata, details, meta: checkedMeta }};
        }})();
        return await Promise.race([inspection, timeout]);
      }} catch (error) {{
        discardCogSource(meta.url);
        const message = String(error?.message || error || '').toLowerCase();
        const key = message.includes('3857') || message.includes('projection') || message.includes('projectedcstype')
          ? 'basemap.cogWebMercatorOnly'
          : cogEngineStatus === 'error'
            ? 'basemap.cogUnavailable'
            : 'basemap.cogInspectFailed';
        return {{ ok: false, key, error: message.slice(0, 200) }};
      }} finally {{
        if (timeoutId !== null) window.clearTimeout(timeoutId);
      }}
    }}
    async function testBasemapForm() {{
      let meta = readBasemapForm();
      const validationKey = validateBasemapForm(meta);
      testedBasemapSignature = '';
      $('basemap-save-btn').disabled = true;
      if (validationKey) {{
        setBasemapFormStatus(validationKey, {{}}, 'error');
        return false;
      }}
      $('basemap-test-btn').disabled = true;
      if (meta.type === 'pmtiles') {{
        setBasemapFormStatus('basemap.pmtilesInspecting');
        const inspection = await inspectPmtilesArchive(meta, {{ refresh: true }});
        if (!inspection.ok) {{
          $('basemap-test-btn').disabled = false;
          setBasemapFormStatus('basemap.testFailed', {{ message: t(inspection.key) }}, 'error');
          return false;
        }}
        const minZoom = Number(inspection.header?.minZoom);
        const maxZoom = Number(inspection.header?.maxZoom);
        if (Number.isFinite(minZoom)) $('basemap-form-min-zoom').value = minZoom;
        if (Number.isFinite(maxZoom)) {{
          $('basemap-form-max-zoom').value = maxZoom;
          $('basemap-form-native-zoom').value = maxZoom;
        }}
        meta = readBasemapForm();
        testedBasemapSignature = customBasemapSignature(meta);
        $('basemap-test-btn').disabled = false;
        $('basemap-save-btn').disabled = false;
        setBasemapFormStatus('basemap.testPassed', {{}}, 'success');
        return true;
      }}
      if (meta.type === 'cog') {{
        setBasemapFormStatus(cogEngineStatus === 'idle' ? 'basemap.cogLoading' : 'basemap.cogInspecting');
        const inspection = await inspectCogSource(meta, {{ refresh: true, requireVisibleTile: true, fitBounds: true }});
        if (!inspection.ok) {{
          $('basemap-test-btn').disabled = false;
          setBasemapFormStatus('basemap.testFailed', {{ message: t(inspection.key) }}, 'error');
          return false;
        }}
        testedCogDetails = inspection.details;
        $('basemap-form-min-zoom').value = inspection.details.minZoom;
        $('basemap-form-max-zoom').value = inspection.details.maxZoom;
        $('basemap-form-native-zoom').value = inspection.details.maxNativeZoom;
        meta = readBasemapForm();
        testedBasemapSignature = customBasemapSignature(meta);
        $('basemap-test-btn').disabled = false;
        $('basemap-save-btn').disabled = false;
        setBasemapFormStatus('basemap.testPassed', {{}}, 'success');
        return true;
      }}
      setBasemapFormStatus('basemap.testing');
      const result = await testBasemapLayer(meta);
      $('basemap-test-btn').disabled = false;
      if (result.ok) {{
        testedBasemapSignature = customBasemapSignature(meta);
        $('basemap-save-btn').disabled = false;
        setBasemapFormStatus('basemap.testPassed', {{}}, 'success');
        return true;
      }}
      setBasemapFormStatus('basemap.testFailed', {{ message: t(result.key) }}, 'error');
      return false;
    }}
    function saveBasemapForm() {{
      const meta = readBasemapForm();
      const validationKey = validateBasemapForm(meta);
      if (validationKey) {{
        setBasemapFormStatus(validationKey, {{}}, 'error');
        return false;
      }}
      if (!testedBasemapSignature || testedBasemapSignature !== customBasemapSignature(meta)) {{
        setBasemapFormStatus('basemap.testFirst', {{}}, 'error');
        $('basemap-save-btn').disabled = true;
        return false;
      }}
      const editing = Boolean(basemapEditorId);
      const index = customBasemaps.findIndex(item => item.id === meta.id);
      const previous = index >= 0 ? customBasemaps[index] : null;
      if (previous?.type === 'pmtiles' && (meta.type !== 'pmtiles' || previous.url !== meta.url)) {{
        discardPmtilesArchive(previous.url);
      }}
      if (previous?.type === 'cog' && (meta.type !== 'cog' || previous.url !== meta.url)) discardCogSource(previous.url);
      if (index >= 0) customBasemaps.splice(index, 1, meta);
      else customBasemaps.push(meta);
      customBasemaps = normalizeCustomBasemaps(customBasemaps);
      if ($('basemap-form-default').checked) defaultBasemapId = meta.id;
      rebuildBasemapRegistry(meta.id);
      reloadBasemapOverlays(meta.id);
      closeBasemapEditor();
      showMode(t(editing ? 'basemap.updated' : 'basemap.saved', {{ name: meta.name }}));
      syncSessionState(editing ? 'custom-basemap-updated' : 'custom-basemap-added');
      return true;
    }}
    function setDefaultBasemap(id) {{
      const meta = BASEMAPS.find(item => item.id === id);
      if (!meta) return false;
      if (isTiandituBasemap(meta) && !tiandituToken) return requestTiandituToken();
      defaultBasemapId = meta.id;
      renderBasemapChoices();
      showMode(t('basemap.defaultChanged', {{ name: basemapDisplayName(meta) }}));
      syncSessionState('default-basemap-changed');
      return true;
    }}
    function moveCustomBasemap(id, direction) {{
      const index = customBasemaps.findIndex(meta => meta.id === id);
      const target = index + Number(direction || 0);
      if (index < 0 || target < 0 || target >= customBasemaps.length) return false;
      [customBasemaps[index], customBasemaps[target]] = [customBasemaps[target], customBasemaps[index]];
      rebuildBasemapRegistry(currentBasemap);
      syncSessionState('custom-basemap-reordered');
      return true;
    }}
    function removeCustomBasemap(id, options = {{}}) {{
      const meta = customBasemaps.find(item => item.id === id);
      if (!meta) return false;
      if (options.confirm !== false && !window.confirm(t('basemap.removeConfirm', {{ name: meta.name }}))) return false;
      if (meta.type === 'pmtiles') discardPmtilesArchive(meta.url);
      if (meta.type === 'cog') discardCogSource(meta.url);
      STATE.layers.filter(layer => isBasemapOverlayLayer(layer) && layer.sourceId === id).forEach(layer => removeLayer(layer.id));
      customBasemaps = customBasemaps.filter(item => item.id !== id);
      if (defaultBasemapId === id) defaultBasemapId = 'OSM';
      if (basemapEditorId === id) closeBasemapEditor();
      rebuildBasemapRegistry(currentBasemap === id ? defaultBasemapId : currentBasemap);
      showMode(t('basemap.removed', {{ name: meta.name }}));
      syncSessionState('custom-basemap-removed');
      return true;
    }}
    function normalizeCatalogType(item) {{
      const raw = String(item.type || item.scale || '').toLowerCase();
      if (raw.includes('image_collection') || raw.includes('image collection')) return 'image_collection';
      if (raw.includes('image')) return 'image';
      if (raw.includes('table') || raw.includes('feature') || raw.includes('vector')) return 'table';
      return 'other';
    }}
    function catalogTypeLabel(type) {{
      const labels = {{
        all: 'catalog.typeAll',
        image_collection: 'catalog.typeImageCollection',
        image: 'catalog.typeImage',
        table: 'catalog.typeTable',
        other: 'catalog.typeOther',
      }};
      return t(labels[type] || labels.other);
    }}
    function catalogCategoryKey(item) {{
      const raw = String(item.category || '').trim().toLowerCase();
      const categoryMap = {{
        'satellite-imagery': 'imagery',
        imagery: 'imagery',
        orthophotos: 'imagery',
        radar: 'imagery',
        'analysis ready data': 'imagery',
        climate: 'climate-atmosphere',
        atmosphere: 'climate-atmosphere',
        precipitation: 'climate-atmosphere',
        'water-vapor': 'climate-atmosphere',
        'weather and climate layers': 'climate-atmosphere',
        'surface-ground-water': 'water-ocean',
        hydrology: 'water-ocean',
        water: 'water-ocean',
        ocean: 'water-ocean',
        oceans: 'water-ocean',
        'oceans and shorelines': 'water-ocean',
        'vegetation-indices': 'vegetation-ecosystems',
        'forest-biomass': 'vegetation-ecosystems',
        'plant-productivity': 'vegetation-ecosystems',
        ecosystems: 'vegetation-ecosystems',
        agriculture: 'vegetation-ecosystems',
        'agriculture and food security': 'vegetation-ecosystems',
        'agriculture vegetation and forestry': 'vegetation-ecosystems',
        'biodiversity ecosystems habitat layers': 'vegetation-ecosystems',
        'landuse-landcover': 'land-cover',
        'land-cover': 'land-cover',
        'land use land cover': 'land-cover',
        'regional land use and land cover': 'land-cover',
        'global land use and land cover': 'land-cover',
        'elevation-topography': 'terrain',
        elevation: 'terrain',
        topography: 'terrain',
        bathymetry: 'terrain',
        'elevation and bathymetry': 'terrain',
        'terrain and topography': 'terrain',
        population: 'human-built',
        'infrastructure-boundaries': 'human-built',
        'population-built': 'human-built',
        'infrastructure and boundaries': 'human-built',
        'population socioeconomic': 'human-built',
        'global utilities assets and amenities layers': 'human-built',
        soil: 'soil-geology',
        soils: 'soil-geology',
        geology: 'soil-geology',
        'soil properties': 'soil-geology',
        'geophysical biological biogeochemical': 'soil-geology',
        fire: 'hazards',
        disasters: 'hazards',
        'fire monitoring and analysis': 'hazards',
        'global events layers': 'hazards',
        cryosphere: 'cryosphere',
        other: 'other',
      }};
      const priority = [
        'imagery',
        'climate-atmosphere',
        'water-ocean',
        'vegetation-ecosystems',
        'land-cover',
        'terrain',
        'human-built',
        'soil-geology',
        'hazards',
        'cryosphere',
        'other',
      ];
      if (raw) {{
        const compactRaw = raw.replace(/&/g, 'and').replace(/[^a-z0-9]+/g, ' ').trim();
        const groups = raw
          .split(',')
          .map(part => part.trim())
          .filter(Boolean)
          .map(part => {{
            const compactPart = part.replace(/&/g, 'and').replace(/[^a-z0-9]+/g, ' ').trim();
            return categoryMap[part] || categoryMap[compactPart] || '';
          }})
          .filter(Boolean);
        const direct = categoryMap[raw] || categoryMap[compactRaw] || priority.find(group => groups.includes(group));
        if (direct && direct !== 'other') return direct;
      }}
      const haystack = datasetSearchText(item);
      if (/(climate|weather|temperature|precipitation|rain|era5|chirps|atmosphere|aerosol|ozone|water vapor)/.test(haystack)) return 'climate-atmosphere';
      if (/(water|hydro|flood|ocean|surface-ground-water|marine)/.test(haystack)) return 'water-ocean';
      if (/(ndvi|evi|vegetation|forest|biomass|ecosystem|crop|agriculture|productivity)/.test(haystack)) return 'vegetation-ecosystems';
      if (/(landcover|land cover|landuse|dynamic world|worldcover)/.test(haystack)) return 'land-cover';
      if (/(elevation|dem|terrain|topography|srtm)/.test(haystack)) return 'terrain';
      if (/(population|building|built|ghsl|worldpop|infrastructure|boundary|boundaries)/.test(haystack)) return 'human-built';
      if (/(soil|geology|geologic)/.test(haystack)) return 'soil-geology';
      if (/(fire|hazard|flood|disaster|burn)/.test(haystack)) return 'hazards';
      if (/(ice|snow|glacier|cryosphere)/.test(haystack)) return 'cryosphere';
      if (/(sentinel|landsat|modis|viirs|satellite-imagery|imagery|radar|sar|orthophoto)/.test(haystack)) return 'imagery';
      return 'other';
    }}
    function catalogCategoryLabel(key) {{
      const zh = {{
        all: '全部',
        imagery: '遥感影像',
        'climate-atmosphere': '气候与大气',
        'water-ocean': '水文与海洋',
        'vegetation-ecosystems': '植被与生态',
        'land-cover': '土地覆盖',
        terrain: '高程地形',
        'human-built': '人口与基础设施',
        'soil-geology': '土壤与地质',
        hazards: '灾害与火灾',
        cryosphere: '冰冻圈',
        other: '其他',
      }};
      const en = {{
        all: 'All',
        imagery: 'Remote sensing imagery',
        'climate-atmosphere': 'Climate and atmosphere',
        'water-ocean': 'Hydrology and ocean',
        'vegetation-ecosystems': 'Vegetation and ecosystems',
        'land-cover': 'Land cover',
        terrain: 'Elevation and terrain',
        'human-built': 'Population and infrastructure',
        'soil-geology': 'Soil and geology',
        hazards: 'Hazards and fire',
        cryosphere: 'Cryosphere',
        other: 'Other',
      }};
      const table = currentLang === 'zh' ? zh : en;
      if (table[key]) return table[key];
      if (currentLang === 'zh') return table.other;
      return String(key || 'other').split(/[-_]/).map(part => part ? part[0].toUpperCase() + part.slice(1) : part).join(' ');
    }}
    function datasetSearchText(item) {{
      return `${{item.id || ''}} ${{item.label || ''}} ${{item.tags || ''}} ${{item.description || ''}} ${{item.scale || ''}} ${{item.provider || ''}} ${{item.type || ''}} ${{item.category || ''}} ${{item.license || ''}}`.toLowerCase();
    }}
    function catalogSourceLabel(item) {{
      const source = String(item.source || '').toLowerCase();
      if (source === 'community') return t('catalog.sourceCommunity');
      if (source === 'curated') return t('catalog.sourceCurated');
      return t('catalog.sourceOfficial');
    }}
    function expandedDatasetTerms(query) {{
      const lower = query.trim().toLowerCase();
      if (!lower) return [];
      const expanded = [lower];
      Object.entries(DATASET_QUERY_ALIASES).forEach(([term, aliases]) => {{
        if (lower.includes(term)) expanded.push(aliases);
      }});
      return expanded.join(' ').split(/[\s,，;；|]+/).map(term => term.trim()).filter(Boolean);
    }}
    function searchMatchedCatalog() {{
      const query = $('dataset-search').value.trim().toLowerCase();
      const catalog = Array.isArray(STATE.catalog) ? STATE.catalog : [];
      const terms = expandedDatasetTerms(query);
      if (!terms.length) return catalog;
      return catalog
        .map(item => {{
          const haystack = datasetSearchText(item);
          const score = terms.reduce((total, term) => total + (haystack.includes(term) ? (haystack.includes(`${{term}}/`) || haystack.includes(`/${{term}}`) ? 3 : 1) : 0), 0);
          return {{ item, score }};
        }})
        .filter(record => record.score > 0)
        .sort((a, b) => b.score - a.score || String(a.item.label || a.item.id).localeCompare(String(b.item.label || b.item.id)))
        .map(record => record.item);
    }}
    function filteredCatalog() {{
      return searchMatchedCatalog()
        .filter(item => !catalogFavoriteFilter || isFavoriteDataset(item.id))
        .filter(item => catalogTypeFilter === 'all' || normalizeCatalogType(item) === catalogTypeFilter)
        .filter(item => catalogCategoryFilter === 'all' || catalogCategoryKey(item) === catalogCategoryFilter);
    }}
    function renderCatalogFacets() {{
      const searchItems = searchMatchedCatalog();
      const favoriteCount = favoriteCatalogItems(searchItems).length;
      const facetItems = catalogFavoriteFilter ? favoriteCatalogItems(searchItems) : searchItems;
      const typeCounts = facetItems.reduce((counts, item) => {{
        const type = normalizeCatalogType(item);
        counts[type] = (counts[type] || 0) + 1;
        counts.all = (counts.all || 0) + 1;
        return counts;
      }}, {{}});
      const typeOrder = ['all', 'image_collection', 'image', 'table', 'other'];
      const favoriteChip = `
            <button class="type-chip favorite-chip ${{catalogFavoriteFilter ? 'active' : ''}}" data-favorite-filter="true" type="button">
              ${{escapeHtml(t('catalog.favoriteChip', {{ count: favoriteCount }}))}}
            </button>
          `;
      $('type-chip-list').innerHTML = favoriteChip + typeOrder
        .filter(type => type === 'all' || typeCounts[type])
        .map(type => {{
          const label = type === 'all'
            ? catalogTypeLabel(type)
            : `${{catalogTypeLabel(type)}} (${{typeCounts[type] || 0}})`;
          return `
            <button class="type-chip ${{catalogTypeFilter === type ? 'active' : ''}}" data-type="${{escapeHtml(type)}}" type="button">
              ${{escapeHtml(label)}}
            </button>
          `;
        }}).join('');
      document.querySelectorAll('.type-chip').forEach(button => {{
        button.addEventListener('click', () => {{
          if (button.dataset.favoriteFilter) {{
            catalogFavoriteFilter = !catalogFavoriteFilter;
            renderDatasets(filteredCatalog());
            return;
          }}
          catalogTypeFilter = button.dataset.type;
          renderDatasets(filteredCatalog());
        }});
      }});

      const categoryBase = facetItems.filter(item => catalogTypeFilter === 'all' || normalizeCatalogType(item) === catalogTypeFilter);
      const categoryCounts = categoryBase.reduce((counts, item) => {{
        const category = catalogCategoryKey(item);
        counts[category] = (counts[category] || 0) + 1;
        counts.all = (counts.all || 0) + 1;
        return counts;
      }}, {{}});
      const query = catalogCategoryQuery.trim().toLowerCase();
      const categories = Object.entries(categoryCounts)
        .filter(([category]) => category === 'all' || !query || catalogCategoryLabel(category).toLowerCase().includes(query) || category.includes(query))
        .sort((a, b) => a[0] === 'all' ? -1 : b[0] === 'all' ? 1 : b[1] - a[1] || catalogCategoryLabel(a[0]).localeCompare(catalogCategoryLabel(b[0])));
      const favoriteCategory = !query || t('catalog.favorites').toLowerCase().includes(query) || 'favorites'.includes(query)
        ? `
        <button class="category-button favorite-filter ${{catalogFavoriteFilter ? 'active' : ''}}" data-favorite-category="true" type="button">
          <span>${{escapeHtml(t('catalog.favorites'))}}</span><span class="category-count">${{favoriteCount}}</span>
        </button>
      `
        : '';
      $('category-list').innerHTML = favoriteCategory + categories.map(([category, count]) => `
        <button class="category-button ${{!catalogFavoriteFilter && catalogCategoryFilter === category ? 'active' : ''}}" data-category="${{escapeHtml(category)}}" type="button">
          <span>${{escapeHtml(catalogCategoryLabel(category))}}</span><span class="category-count">${{count}}</span>
        </button>
      `).join('');
      document.querySelectorAll('.category-button').forEach(button => {{
        button.addEventListener('click', () => {{
          if (button.dataset.favoriteCategory) {{
            catalogFavoriteFilter = true;
            catalogTypeFilter = 'all';
            catalogCategoryFilter = 'all';
            renderDatasets(filteredCatalog());
            return;
          }}
          catalogFavoriteFilter = false;
          catalogCategoryFilter = button.dataset.category;
          renderDatasets(filteredCatalog());
        }});
      }});
    }}
    function datasetLayerIds(datasetId) {{
      return STATE.layers.filter(layer => layer.dataset === datasetId).map(layer => layer.id);
    }}
    function datasetById(datasetId) {{
      return (Array.isArray(STATE.catalog) ? STATE.catalog : []).find(item => item.id === datasetId) || null;
    }}
    function defaultPreviewRecipeForDataset(item) {{
      const datasetId = String(item?.id || '');
      const type = normalizeCatalogType(item || {{}});
      let operation = type === 'image_collection' ? 'imagecollection-median' : (type === 'image' ? 'image' : 'preview');
      const recipe = {{
        kind: 'preview',
        source: 'map-console-default-preview',
        datasetId,
        label: item?.label || datasetId,
        operation,
        startDate: STATE.startDate,
        endDate: STATE.endDate,
        aoi: hasAoi() ? 'currentAOI' : 'currentMapBounds',
        description: 'Default quick-preview recipe. Use an explicit recipe for analytical requests.',
      }};
      if (datasetId === 'MODIS/061/MOD13Q1') {{
        Object.assign(recipe, {{ band: 'NDVI', temporalReducer: 'median', scaleFactor: 0.0001, outputBand: 'NDVI' }});
      }} else if (datasetId === 'MODIS/061/MOD11A2') {{
        Object.assign(recipe, {{ band: 'LST_Day_1km', temporalReducer: 'median', scaleFactor: 0.02, offset: -273.15, outputBand: 'LST_Day_C' }});
      }} else if (datasetId === 'GOOGLE/DYNAMICWORLD/V1') {{
        Object.assign(recipe, {{ band: 'label', temporalReducer: 'mode', outputBand: 'label' }});
      }} else if (datasetId === 'COPERNICUS/S2_SR_HARMONIZED') {{
        Object.assign(recipe, {{ bands: ['B4', 'B3', 'B2'], temporalReducer: 'median', output: 'rgb' }});
      }}
      return recipe;
    }}
    function datasetContext(item) {{
      if (!item) return null;
      const explicitAoi = hasAoi() ? cloneAoi(STATE.aoi) : null;
      const processingAoi = currentProcessingAoi();
      const processingBounds = processingAoi ? processingAoi.bounds : null;
      return {{
        id: item.id,
        label: item.label || item.id,
        type: normalizeCatalogType(item),
        source: item.source || '',
        provider: datasetDetailValue(item.provider),
        license: datasetDetailValue(item.license),
        scale: datasetDetailValue(item.scale),
        dateRange: datasetDateText(item),
        startDate: datasetDetailValue(item.startDate),
        endDate: datasetDetailValue(item.endDate),
        tags: datasetDetailValue([item.category, item.tags].filter(Boolean).join(' · ')),
        catalogUrl: datasetDetailValue(item.url),
        sampleCode: datasetDetailValue(item.sampleCode),
        currentAoi: explicitAoi,
        currentBounds: processingBounds,
        hasExplicitAoi: Boolean(explicitAoi),
        processingAoi,
        processingBounds,
        mapDateRange: {{ startDate: STATE.startDate, endDate: STATE.endDate, cloudPct: STATE.cloudPct }},
        defaultRecipe: defaultPreviewRecipeForDataset(item),
      }};
    }}
    function selectedDatasetContext() {{
      return activeDatasetId ? datasetContext(datasetById(activeDatasetId)) : null;
    }}
    function recipeSummary(recipe) {{
      if (!recipe || typeof recipe !== 'object') return '-';
      const band = recipe.outputBand || recipe.band || recipe.output || recipe.operation || recipe.kind || 'recipe';
      const reducer = recipe.temporalReducer || recipe.operation || '';
      const period = recipe.periodLabel || (recipe.year && Array.isArray(recipe.months)
        ? `${{recipe.year}} months ${{recipe.months.join(',')}}`
        : [recipe.startDate, recipe.endDate].filter(Boolean).join('..'));
      return [band, reducer, period].filter(Boolean).join(' · ') || '-';
    }}
    function datasetDetailValue(value) {{
      const text = String(value || '').trim();
      if (!text || text.toLowerCase() === 'na' || text.toLowerCase() === 'none') return '';
      return text;
    }}
    function datasetDateText(item) {{
      const start = datasetDetailValue(item.startDate);
      const end = datasetDetailValue(item.endDate);
      if (start && end) return `${{start}} - ${{end}}`;
      return start || end || '';
    }}
    function datasetDurationText(item) {{
      const start = Date.parse(datasetDetailValue(item.startDate));
      const endText = datasetDetailValue(item.endDate);
      const end = endText ? Date.parse(endText) : Date.now();
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return '';
      const months = Math.max(1, Math.round((end - start) / (1000 * 60 * 60 * 24 * 30.4375)));
      if (months >= 24) return t('data.attrYear', {{ count: trimNumber((months / 12).toFixed(months >= 120 ? 0 : 1)) }});
      return t('data.attrMonth', {{ count: months }});
    }}
    function datasetResolutionText(item) {{
      const scale = datasetDetailValue(item.scale);
      if (!scale) return '';
      const lower = scale.toLowerCase();
      if (/^(image|image collection|table|feature|vector|catalog|ready layer|official catalog|community catalog)$/.test(lower)) return '';
      if (/\\b(\\d+(\\.\\d+)?\\s*(m|meter|meters|km|kilometer|kilometers|deg|degree|degrees|arcsec|arc-second|arcseconds)|scale)\\b/.test(lower)) return scale;
      return '';
    }}
    function datasetAttr(labelKey, value) {{
      const text = datasetDetailValue(value);
      if (!text) return '';
      return `<span class="dataset-attr"><strong>${{escapeHtml(t(labelKey))}}</strong> ${{escapeHtml(text)}}</span>`;
    }}
    function datasetAttrsHtml(item, typeLabel) {{
      const attrs = [
        datasetAttr('data.attrTime', datasetDateText(item)),
        datasetAttr('data.attrSpan', datasetDurationText(item)),
        datasetAttr('data.attrResolution', datasetResolutionText(item)),
        datasetAttr('data.attrType', typeLabel),
      ].filter(Boolean);
      return attrs.length ? `<div class="dataset-attrs">${{attrs.join('')}}</div>` : '';
    }}
    function datasetDetailSection(labelKey, value) {{
      const text = datasetDetailValue(value);
      if (!text) return '';
      return `
        <section class="dataset-detail-section">
          <div class="dataset-detail-label">${{escapeHtml(t(labelKey))}}</div>
          <div class="dataset-detail-text">${{escapeHtml(text)}}</div>
        </section>
      `;
    }}
    function datasetDetailHtml(item) {{
      const typeLabel = catalogTypeLabel(normalizeCatalogType(item));
      const sourceLabel = catalogSourceLabel(item);
      const category = catalogCategoryLabel(catalogCategoryKey(item));
      const license = datasetDetailValue(item.license);
      const provider = datasetDetailValue(item.provider);
      const dates = datasetDateText(item);
      const description = datasetDetailValue(item.description) || t('data.detailNoDescription');
      const tags = datasetDetailValue([item.category, item.tags].filter(Boolean).join(' · '));
      const thumb = datasetDetailValue(item.thumbnail);
      const catalogUrl = datasetDetailValue(item.url);
      const sampleCode = datasetDetailValue(item.sampleCode);
      const previewRecipe = recipeSummary(defaultPreviewRecipeForDataset(item));
      return `
        <div class="dataset-detail-head">
          <div>
            <div class="dataset-detail-title">${{escapeHtml(item.label || item.id)}}</div>
            <div class="dataset-detail-id">${{escapeHtml(item.id || '')}}</div>
          </div>
          <button class="dataset-detail-close" id="dataset-detail-close" title="${{escapeHtml(t('tool.close'))}}" aria-label="${{escapeHtml(t('tool.close'))}}" type="button">&times;</button>
        </div>
        <div class="dataset-detail-body">
          ${{thumb ? `<img class="dataset-detail-thumb" src="${{escapeHtml(thumb)}}" alt="">` : ''}}
          <div class="dataset-detail-badges">
            <span class="dataset-detail-badge">${{escapeHtml(sourceLabel)}}</span>
            <span class="dataset-detail-badge">${{escapeHtml(typeLabel)}}</span>
            <span class="dataset-detail-badge">${{escapeHtml(category)}}</span>
            ${{license ? `<span class="dataset-detail-badge">${{escapeHtml(license)}}</span>` : ''}}
          </div>
          ${{datasetDetailSection('data.detailDescription', description)}}
          ${{datasetDetailSection('data.detailProvider', provider)}}
          ${{datasetDetailSection('data.detailDates', dates)}}
          ${{datasetDetailSection('data.detailTags', tags)}}
          ${{datasetDetailSection('data.previewRecipe', previewRecipe)}}
          <div class="dataset-detail-actions">
            <button class="dataset-detail-command primary" id="dataset-detail-add" type="button">${{escapeHtml(t('data.addFromDetail'))}}</button>
            <button class="dataset-detail-command" id="dataset-detail-copy" type="button">${{escapeHtml(t('data.copyId'))}}</button>
            <button class="dataset-detail-command" id="dataset-detail-copy-context" type="button">${{escapeHtml(t('data.copyContext'))}}</button>
            ${{catalogUrl ? `<a class="dataset-detail-link" href="${{escapeHtml(catalogUrl)}}" target="_blank" rel="noreferrer">${{escapeHtml(t('data.openCatalog'))}}</a>` : ''}}
            ${{sampleCode ? `<a class="dataset-detail-link" href="${{escapeHtml(sampleCode)}}" target="_blank" rel="noreferrer">${{escapeHtml(t('data.openSample'))}}</a>` : ''}}
          </div>
        </div>
      `;
    }}
    function closeDatasetDetail() {{
      const detail = $('dataset-detail');
      detail.classList.remove('open');
      detail.innerHTML = '';
      document.querySelector('.data-panel').classList.remove('detail-open');
    }}
    function renderDatasetDetail(datasetId) {{
      const item = datasetById(datasetId);
      if (!item) {{
        closeDatasetDetail();
        return;
      }}
      const detail = $('dataset-detail');
      detail.innerHTML = datasetDetailHtml(item);
      detail.classList.add('open');
      document.querySelector('.data-panel').classList.add('detail-open');
      $('dataset-detail-close')?.addEventListener('click', closeDatasetDetail);
      $('dataset-detail-add')?.addEventListener('click', () => importDatasetToMap(item.id));
      $('dataset-detail-copy')?.addEventListener('click', async () => {{
        try {{
          await navigator.clipboard.writeText(item.id || '');
          showModeKey('data.detailCopied');
        }} catch (error) {{
          showModeKey('log.clipboardUnavailable');
        }}
      }});
      $('dataset-detail-copy-context')?.addEventListener('click', async () => {{
        try {{
          await navigator.clipboard.writeText(JSON.stringify(datasetContext(item), null, 2));
          showModeKey('data.contextCopied');
        }} catch (error) {{
          showModeKey('log.clipboardUnavailable');
        }}
      }});
    }}
    function setActiveDataset(datasetId) {{
      activeDatasetId = datasetId;
      document.querySelectorAll('.dataset-item').forEach(item => item.classList.toggle('active', item.dataset.dataset === datasetId));
      renderDatasetDetail(datasetId);
      syncSessionState('selected-dataset');
      logMsg('log.datasetSelected', {{ dataset: datasetId }});
    }}
    function setLanguage(lang) {{
      currentLang = lang;
      localStorage.setItem('easygee-lang', currentLang);
      applyI18n();
      renderDatasets(filteredCatalog());
      if (activeDatasetId && $('dataset-detail')?.classList.contains('open')) {{
        renderDatasetDetail(activeDatasetId);
      }}
      renderLayers();
      renderTasks();
      setActiveLayer(activeLayerId, {{ reveal: false }});
      updateScaleLine();
      syncToolState();
      logMsg('log.language');
    }}
    function quotaRows() {{
      return STATE.quota && Array.isArray(STATE.quota.rows) ? STATE.quota.rows : [];
    }}
    function quotaWarningText() {{
      const warnings = Array.isArray(STATE.quota?.warnings) ? STATE.quota.warnings.join(' ').toLowerCase() : '';
      if (!warnings) return '';
      if (warnings.includes('active account selected') || warnings.includes('gcloud auth login')) return t('quota.issueCloudLogin');
      if (warnings.includes('cloudquotas.googleapis.com') && warnings.includes('not been used')) return t('quota.issueCloudQuotasApi');
      if (warnings.includes('cloudquotas.quotas.get') || warnings.includes('permission_denied') || warnings.includes('permission denied')) return t('quota.issueQuotaPermission');
      if (warnings.includes('monitoring.timeseries.list')) return t('quota.issueMonitoringPermission');
      if (warnings.includes('command group installed') || warnings.includes('components:') || warnings.includes('sslerror')) return t('quota.issueQuotaNetwork');
      return t('quota.issueLiveUnavailable');
    }}
    function quotaSummaryText() {{
      if (!quotaRows().length) return t('quota.summaryEmpty');
      if (STATE.quota?.status === 'live-with-usage') return t('quota.summaryLiveUsage');
      if (STATE.quota?.status === 'live-limit-only') return t('quota.summaryLiveLimit');
      return quotaWarningText() || t('quota.summaryDefault');
    }}
    function quotaValue(value) {{
      const text = String(value || '').trim();
      return text && text !== 'N/A' ? text : t('quota.notAvailable');
    }}
    function parseQuotaNumber(value) {{
      const text = String(value || '').replace(/,/g, '').trim();
      if (!text || text === 'N/A' || text === '-' || text.toLowerCase().includes('unlimited')) return null;
      const match = text.match(/-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/i);
      if (!match) return null;
      const number = Number(match[0]);
      if (number >= 9e18) return null;
      return Number.isFinite(number) ? number : null;
    }}
    function trimNumber(text) {{
      return String(text).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
    }}
    function compactQuotaNumber(number) {{
      const abs = Math.abs(number);
      if (abs >= 1e12) return number.toExponential(2).replace('e+', 'e');
      if (currentLang === 'zh') {{
        if (abs >= 1e8) return `${{trimNumber((number / 1e8).toFixed(abs >= 1e9 ? 1 : 2))}}亿`;
        if (abs >= 1e4) return `${{trimNumber((number / 1e4).toFixed(abs >= 1e5 ? 1 : 2))}}万`;
      }} else {{
        if (abs >= 1e9) return `${{trimNumber((number / 1e9).toFixed(abs >= 1e10 ? 1 : 2))}}B`;
        if (abs >= 1e6) return `${{trimNumber((number / 1e6).toFixed(abs >= 1e7 ? 1 : 2))}}M`;
        if (abs >= 1e3) return `${{trimNumber((number / 1e3).toFixed(abs >= 1e4 ? 1 : 2))}}k`;
      }}
      if (abs >= 100) return trimNumber(number.toFixed(0));
      if (abs >= 10) return trimNumber(number.toFixed(1));
      return trimNumber(number.toFixed(2));
    }}
    function quotaUnitLabel(unit) {{
      const text = String(unit || '').trim();
      if (currentLang !== 'zh') return text;
      if (text === 's{{CPU}}') return 'CPU秒';
      if (text === 'slot-seconds/day (350 slot-hours)') return '槽秒/日';
      if (text === 'seconds/day') return '秒/日';
      if (text === 'concurrent requests') return '并发请求';
      if (text === 'requests') return '请求';
      if (text === 'assets') return '项';
      return text;
    }}
    function compactQuotaValue(value) {{
      const text = String(value || '').trim();
      if (!text || text === 'N/A') return t('quota.notAvailable');
      if (text.toLowerCase().includes('unlimited') || text === '∞') return t('quota.unlimited');
      const number = parseQuotaNumber(text);
      if (number === null) return text;
      const suffix = text.replace(/^[\s,0-9.eE+\-]+/, '').trim();
      const unit = quotaUnitLabel(suffix);
      return `${{compactQuotaNumber(number)}}${{unit ? ` ${{unit}}` : ''}}`;
    }}
    function quotaPercentText(percent) {{
      if (!Number.isFinite(percent)) return t('quota.unknown');
      if (percent > 0 && percent < 0.1) return '<0.1%';
      if (percent >= 10) return `${{trimNumber(percent.toFixed(0))}}%`;
      return `${{trimNumber(percent.toFixed(1))}}%`;
    }}
    function quotaName(row) {{
      return currentLang === 'zh' ? (row.nameZh || row.name) : (row.nameEn || row.name);
    }}
    function knownQuotaValue(value) {{
      const text = String(value || '').trim();
      return Boolean(text && text !== 'N/A' && text !== '-');
    }}
    function quotaTierText() {{
      const tier = STATE.quota?.tier;
      if (!tier || !tier.name) return t('quota.tierUnknown');
      const name = currentLang === 'zh' ? (tier.nameZh || tier.name) : (tier.nameEn || tier.name);
      return t(tier.inferred ? 'quota.tierInferred' : 'quota.tier', {{ tier: name }});
    }}
    function quotaPercentForRow(row) {{
      if (row.unlimited) return null;
      const used = parseQuotaNumber(row.used);
      const limit = parseQuotaNumber(row.limit);
      if (used !== null && limit !== null && limit > 0) return Math.max(0, (used / limit) * 100);
      const raw = row.percent;
      if (raw === null || raw === undefined || raw === '') return null;
      const percent = Number(raw);
      return Number.isFinite(percent) ? percent : null;
    }}
    function renderQuota() {{
      const rows = quotaRows();
      const summary = quotaSummaryText();
      const measuredRows = rows.filter(row => quotaPercentForRow(row) !== null);
      const alertCount = measuredRows.filter(row => quotaPercentForRow(row) >= 80).length;
      const maxPercent = measuredRows.length ? Math.max(...measuredRows.map(row => quotaPercentForRow(row))) : null;
      $('quota-project').textContent = t('quota.project', {{ project: STATE.project }});
      $('quota-tier').textContent = quotaTierText();
      $('quota-count').textContent = rows.length || 0;
      $('quota-used-summary').textContent = rows.length
        ? t('quota.measuredOfTotal', {{ count: measuredRows.length, total: rows.length }})
        : t('quota.notAvailable');
      $('quota-remaining-summary').textContent = alertCount
        ? t('quota.alertCount', {{ count: alertCount }})
        : t('quota.noAlerts');
      $('quota-summary').textContent = maxPercent === null
        ? summary
        : `${{summary}} · ${{t('quota.maxUsed', {{ percent: quotaPercentText(maxPercent) }})}}`;
      const indicator = document.querySelector('.quota-indicator');
      if (indicator) {{
        indicator.classList.remove('ok', 'warn', 'muted');
        indicator.classList.add(STATE.quota?.indicator || (rows.length ? 'warn' : 'muted'));
      }}
      const quotaTitle = `${{t('tool.quota')}} - ${{summary}}`;
      $('quota-btn').title = quotaTitle;
      $('quota-btn').setAttribute('aria-label', quotaTitle);
      const usageSourceAvailable = Boolean(STATE.quota?.usageSource);
      $('quota-list').innerHTML = rows.length ? rows.slice(0, 5).map(row => {{
        const percent = quotaPercentForRow(row);
        const hasPercent = percent !== null;
        const hasUsage = knownQuotaValue(row.used) && row.usageKnown !== false;
        const name = quotaName(row);
        const safePercent = hasPercent ? Math.max(0, Math.min(100, percent)) : 0;
        const barPercent = safePercent > 0 && safePercent < 0.1 ? 0.1 : safePercent;
        const meterWidth = hasPercent && safePercent > 0 ? `max(2px, ${{trimNumber(barPercent.toFixed(2))}}%)` : '0';
        const rowClass = `${{escapeHtml(row.status || 'unknown')}} ${{hasPercent ? 'measured' : 'unknown'}}`;
        const usage = row.unlimited && hasUsage
          ? t('quota.usedUnlimited', {{ used: compactQuotaValue(row.used) }})
          : hasPercent
          ? t('quota.usedOfTotal', {{
              used: compactQuotaValue(row.used),
              total: compactQuotaValue(row.limit),
              percent: quotaPercentText(percent),
            }})
          : t('quota.totalOnly', {{ total: compactQuotaValue(row.limit) }});
        const remaining = row.unlimited
          ? t('quota.remainingUnlimited')
          : hasPercent
          ? t('quota.remainingValue', {{ remaining: compactQuotaValue(row.remaining) }})
          : t(row.inferredZeroUsage ? 'quota.noUsageYet' : usageSourceAvailable ? 'quota.usageUnavailable' : 'quota.usageMissing');
        const status = row.unlimited
          ? t('quota.unlimitedState')
          : hasPercent
          ? (percent >= 80 ? t('quota.warnState') : t('quota.okState'))
          : t(row.inferredZeroUsage ? 'quota.noUsageState' : 'quota.limitOnlyState');
        return `
          <div class="quota-row ${{rowClass}}">
            <div class="quota-row-head">
              <div class="quota-name" title="${{escapeHtml(name)}}">${{escapeHtml(name)}}</div>
              <div class="quota-usage" title="${{escapeHtml(usage)}}">${{escapeHtml(usage)}}</div>
            </div>
            <div class="quota-meter" aria-hidden="true"><span style="width:${{meterWidth}}"></span></div>
            <div class="quota-row-foot"><span>${{escapeHtml(remaining)}}</span><span>${{escapeHtml(status)}}</span></div>
          </div>
        `;
      }}).join('') : `<div class="quota-note">${{escapeHtml(t('quota.summaryEmpty'))}}</div>`;
    }}

    if (!window.L) {{
      document.body.innerHTML = '<main style="padding:24px;font-family:Segoe UI,Arial,sans-serif"><h1>Leaflet failed to load</h1><p>Check network access to the Leaflet CDN, then reload this local page.</p></main>';
      throw new Error('Leaflet missing');
    }}

    $('quota-link').href = STATE.quota?.consoleUrl || `https://console.cloud.google.com/iam-admin/quotas?service=earthengine.googleapis.com&project=${{encodeURIComponent(STATE.project)}}`;
    initializePersistentState();
    if (!activeLayerId && hasMeasurements()) activeLayerId = MEASUREMENTS_LAYER_ID;
    if (!activeLayerId && hasAoi()) activeLayerId = AOI_LAYER_ID;
    if (!activeLayerId) activeLayerId = PRIMARY_BASEMAP_LAYER_ID;

    const map = L.map('map', {{ zoomControl: false, attributionControl: false }}).setView(STATE.center, STATE.zoom);
    map.createPane(PRIMARY_BASEMAP_PANE);
    map.getPane(PRIMARY_BASEMAP_PANE).style.zIndex = '150';
    map.getPane(PRIMARY_BASEMAP_PANE).style.pointerEvents = 'none';
    const CUSTOM_BASEMAP_TYPES = new Set(['xyz', 'tms', 'arcgis', 'wms', 'wmts', 'pmtiles', 'cog']);
    const pmtilesArchives = new Map();
    const cogMetadataCache = new Map();
    const basemapPerformanceSamples = new Map();
    const seenBasemapSources = new Set();
    const lazyAssetPromises = new Map();
    let cogEnginePromise = null;
    let cogEngineStatus = 'idle';
    let cogEngineError = '';
    function basemapPerformanceSourceKey(meta) {{
      return `${{String(meta?.type || 'xyz').toLowerCase()}}:${{String(meta?.url || meta?.id || '')}}`;
    }}
    function basemapResourceMatcher(meta) {{
      const template = String(meta?.url || '').trim();
      if (!template) return () => false;
      try {{
        const replacement = '__easygee_tile__';
        const parsed = new URL(template.replace(/[{{][^}}]+[}}]/g, replacement), window.location.href);
        const templatedHost = parsed.hostname.startsWith(`${{replacement}}.`);
        const hostSuffix = templatedHost ? parsed.hostname.slice(replacement.length + 1) : parsed.hostname;
        const marker = parsed.pathname.indexOf(replacement);
        const pathPrefix = marker >= 0 ? parsed.pathname.slice(0, marker) : parsed.pathname;
        return name => {{
          try {{
            const entry = new URL(name, window.location.href);
            const hostMatches = templatedHost ? entry.hostname.endsWith(`.${{hostSuffix}}`) : entry.hostname === hostSuffix;
            const pathMatches = marker >= 0 ? entry.pathname.startsWith(pathPrefix) : entry.pathname === parsed.pathname;
            return entry.protocol === parsed.protocol && hostMatches && pathMatches;
          }} catch {{
            return false;
          }}
        }};
      }} catch {{
        return () => false;
      }}
    }}
    function collectBasemapNetworkPerformance(meta, sample) {{
      if (!sample || typeof performance?.getEntriesByType !== 'function') return;
      const matches = basemapResourceMatcher(meta);
      const entries = performance.getEntriesByType('resource').filter(entry => (
        Number(entry.startTime) >= sample.startedAt - 1 && matches(entry.name)
      ));
      if (!entries.length) return;
      sample.sourceRequests = entries.length;
      const transferredBytes = entries.reduce((total, entry) => total + Math.max(0, Number(entry.transferSize) || 0), 0);
      if (transferredBytes > 0) sample.transferredBytes = Math.round(transferredBytes);
    }}
    function publicBasemapPerformance(meta) {{
      const sample = basemapPerformanceSamples.get(meta?.id);
      if (!sample) return null;
      return {{
        status: sample.status,
        cache: sample.cache,
        ...(Number.isFinite(sample.firstRenderMs) ? {{ firstRenderMs: Math.round(sample.firstRenderMs) }} : {{}}),
        ...(Number.isFinite(sample.readyMs) ? {{ readyMs: Math.round(sample.readyMs) }} : {{}}),
        renderedBlocks: Math.max(0, Math.round(sample.renderedBlocks || 0)),
        ...(Number.isFinite(sample.sourceRequests) ? {{ sourceRequests: Math.max(0, Math.round(sample.sourceRequests)) }} : {{}}),
        ...(Number.isFinite(sample.transferredBytes) ? {{ transferredBytes: Math.max(0, Math.round(sample.transferredBytes)) }} : {{}}),
      }};
    }}
    function updateBasemapPerformance(meta, phase) {{
      const sample = basemapPerformanceSamples.get(meta?.id);
      if (!sample || sample.status === 'error' || sample.status === 'ready') return;
      const elapsed = Math.max(0, performance.now() - sample.startedAt);
      if (phase === 'tile') {{
        sample.renderedBlocks += 1;
        if (!Number.isFinite(sample.firstRenderMs)) sample.firstRenderMs = elapsed;
      }}
      if (phase === 'ready') {{
        if (!Number.isFinite(sample.firstRenderMs)) sample.firstRenderMs = elapsed;
        sample.readyMs = elapsed;
        sample.status = 'ready';
        seenBasemapSources.add(sample.sourceKey);
        collectBasemapNetworkPerformance(meta, sample);
      }}
      if (meta?.id === currentBasemap) renderBasemapSourceDetails();
    }}
    function failBasemapPerformance(meta) {{
      const sample = basemapPerformanceSamples.get(meta?.id);
      if (!sample) return;
      sample.status = 'error';
      collectBasemapNetworkPerformance(meta, sample);
      if (meta?.id === currentBasemap) renderBasemapSourceDetails();
    }}
    function beginBasemapPerformance(meta, layer) {{
      if (!meta || !layer) return;
      const sourceKey = basemapPerformanceSourceKey(meta);
      const sample = {{
        status: 'loading',
        cache: seenBasemapSources.has(sourceKey) ? 'warm' : 'cold',
        sourceKey,
        startedAt: performance.now(),
        firstRenderMs: null,
        readyMs: null,
        renderedBlocks: 0,
        sourceRequests: null,
        transferredBytes: null,
      }};
      basemapPerformanceSamples.set(meta.id, sample);
      if (meta.id === currentBasemap) renderBasemapSourceDetails();
      if (String(meta.type || '').toLowerCase() === 'cog') {{
        window.requestAnimationFrame(() => {{
          try {{
            const glMap = layer._easygeeCogLayer?.getMaplibreMap?.();
            if (basemapPerformanceSamples.get(meta.id) === sample && glMap?.getSource('easygee-cog-source') && glMap.isSourceLoaded('easygee-cog-source')) {{
              updateBasemapPerformance(meta, 'tile');
              updateBasemapPerformance(meta, 'ready');
            }}
          }} catch {{}}
        }});
      }}
    }}
    function bindBasemapPerformance(meta, layer) {{
      if (!layer || layer._easygeePerformanceBound) return layer;
      layer._easygeePerformanceBound = true;
      layer.on('tileload', () => updateBasemapPerformance(meta, 'tile'));
      layer.on('load', () => updateBasemapPerformance(meta, 'ready'));
      return layer;
    }}
    function createRegisteredBasemapLayer(meta, opacity = 1) {{
      return bindBasemapPerformance(meta, createBasemapLayer(meta, {{ pane: PRIMARY_BASEMAP_PANE, opacity }}));
    }}
    function loadLazyStyle(key, href) {{
      if (document.querySelector(`link[data-easygee-engine="${{key}}"]`)) return Promise.resolve();
      return new Promise((resolve, reject) => {{
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = href;
        link.dataset.easygeeEngine = key;
        link.addEventListener('load', () => resolve(), {{ once: true }});
        link.addEventListener('error', () => {{ link.remove(); reject(new Error(`Failed to load ${{key}}`)); }}, {{ once: true }});
        document.head.appendChild(link);
      }});
    }}
    function loadLazyScript(key, src, ready) {{
      if (ready()) return Promise.resolve();
      if (lazyAssetPromises.has(key)) return lazyAssetPromises.get(key);
      const promise = new Promise((resolve, reject) => {{
        let script = document.querySelector(`script[data-easygee-engine="${{key}}"]`);
        if (script && script.dataset.easygeeLoaded === 'true') script.remove();
        script = document.querySelector(`script[data-easygee-engine="${{key}}"]`) || document.createElement('script');
        const finish = () => {{
          script.dataset.easygeeLoaded = 'true';
          if (ready()) resolve();
          else {{ script.remove(); reject(new Error(`Invalid ${{key}} asset`)); }}
        }};
        const fail = () => {{ script.remove(); reject(new Error(`Failed to load ${{key}}`)); }};
        script.addEventListener('load', finish, {{ once: true }});
        script.addEventListener('error', fail, {{ once: true }});
        if (!script.isConnected) {{
          script.src = src;
          script.crossOrigin = 'anonymous';
          script.dataset.easygeeEngine = key;
          document.head.appendChild(script);
        }}
      }});
      const tracked = promise.catch(error => {{ lazyAssetPromises.delete(key); throw error; }});
      lazyAssetPromises.set(key, tracked);
      return tracked;
    }}
    function cogEngineReady() {{
      return Boolean(window.maplibregl?.Map && window.MaplibreCOGProtocol?.cogProtocol && window.MaplibreCOGProtocol?.getCogMetadata && L.maplibreGL);
    }}
    async function ensureCogEngine() {{
      if (cogEngineReady() && window.__easygeeCogProtocolRegistered) {{
        cogEngineStatus = 'ready';
        return true;
      }}
      if (cogEnginePromise) return cogEnginePromise;
      cogEngineStatus = 'loading';
      cogEngineError = '';
      cogEnginePromise = (async () => {{
        await Promise.all([
          loadLazyStyle('maplibre-css', COG_ENGINE_ASSETS.maplibreCss),
          loadLazyScript('maplibre-js', COG_ENGINE_ASSETS.maplibreJs, () => Boolean(window.maplibregl?.Map)),
        ]);
        await Promise.all([
          loadLazyScript('cog-protocol', COG_ENGINE_ASSETS.cogProtocolJs, () => Boolean(window.MaplibreCOGProtocol?.cogProtocol && window.MaplibreCOGProtocol?.getCogMetadata)),
          loadLazyScript('maplibre-leaflet', COG_ENGINE_ASSETS.leafletAdapterJs, () => Boolean(L.maplibreGL)),
        ]);
        if (typeof window.maplibregl.supported === 'function' && !window.maplibregl.supported()) throw new Error('WebGL unavailable');
        if (!window.__easygeeCogProtocolRegistered) {{
          window.maplibregl.addProtocol('cog', window.MaplibreCOGProtocol.cogProtocol);
          window.__easygeeCogProtocolRegistered = true;
        }}
        cogEngineStatus = 'ready';
        return true;
      }})().catch(error => {{
        cogEnginePromise = null;
        cogEngineStatus = 'error';
        cogEngineError = String(error?.message || error || 'COG engine unavailable').slice(0, 200);
        throw error;
      }});
      return cogEnginePromise;
    }}
    function basemapZoom(value, fallback) {{
      const number = Number(value);
      return Number.isFinite(number) ? Math.max(0, Math.min(24, Math.round(number))) : fallback;
    }}
    function normalizeBasemapBounds(value) {{
      if (!Array.isArray(value) || value.length !== 4) return null;
      const bounds = value.map(Number);
      if (!bounds.every(Number.isFinite)) return null;
      const [west, south, east, north] = bounds;
      if (west < -180 || east > 180 || south < -90 || north > 90 || west >= east || south >= north) return null;
      return bounds;
    }}
    function customBasemapIdentifier(value, fallback = '') {{
      let id = String(value || fallback || '').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/-+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80);
      if (!id.startsWith('custom-')) id = `custom-${{id || Date.now().toString(36)}}`;
      return id;
    }}
    function normalizeCustomBasemap(raw, index = 0) {{
      if (!raw || typeof raw !== 'object') return null;
      const type = String(raw.type || 'xyz').trim().toLowerCase();
      const name = String(raw.name || '').trim().slice(0, 120);
      const url = String(raw.url || '').trim().slice(0, 4096);
      const sourceUrl = String(raw.sourceUrl || '').trim().slice(0, 4096);
      if (!CUSTOM_BASEMAP_TYPES.has(type) || !name || !url || urlContainsCredentials(url) || urlContainsCredentials(sourceUrl)) return null;
      const minZoom = basemapZoom(raw.minZoom, 0);
      const maxZoom = Math.max(minZoom, basemapZoom(raw.maxZoom, 19));
      const maxNativeZoom = Math.max(minZoom, Math.min(maxZoom, basemapZoom(raw.maxNativeZoom, maxZoom)));
      const id = customBasemapIdentifier(raw.id, `custom-${{index + 1}}`);
      const subdomains = String(raw.subdomains || '').trim().slice(0, 120);
      const attribution = String(raw.attribution || '').trim().slice(0, 1000);
      const bounds = normalizeBasemapBounds(raw.bounds);
      const bandCount = Math.max(0, Math.min(1024, Math.round(Number(raw.bandCount) || 0)));
      const options = {{ minZoom, maxZoom, maxNativeZoom, attribution, tms: type === 'tms' }};
      if (subdomains) options.subdomains = subdomains.split(/[\s,]+/).filter(Boolean);
      return {{
        id,
        name,
        type,
        custom: true,
        thumb: `custom-${{type}}`,
        url,
        provider: String(raw.provider || '').trim().slice(0, 240),
        service: String(raw.service || (type === 'pmtiles'
          ? 'PMTiles raster archive · HTTP Range'
          : type === 'cog'
            ? 'Cloud Optimized GeoTIFF · HTTP Range'
            : `${{type.toUpperCase()}} service`)).trim().slice(0, 240),
        attribution,
        sourceUrl,
        note: String(raw.note || '').trim().slice(0, 240),
        subdomains,
        layers: String(raw.layers || '').trim().slice(0, 500),
        styles: String(raw.styles || '').trim().slice(0, 500),
        format: String(raw.format || 'image/png').trim().slice(0, 80),
        version: String(raw.version || (type === 'wmts' ? '1.0.0' : '1.3.0')).trim().slice(0, 20),
        tileMatrixSet: String(raw.tileMatrixSet || 'GoogleMapsCompatible').trim().slice(0, 160),
        matrixPrefix: String(raw.matrixPrefix || '').trim().slice(0, 160),
        minZoom,
        maxZoom,
        maxNativeZoom,
        ...(bounds ? {{ bounds }} : {{}}),
        ...(type === 'cog' ? {{ crs: String(raw.crs || 'EPSG:3857').trim().slice(0, 80), bandCount }} : {{}}),
        transparent: raw.transparent !== false,
        options,
      }};
    }}
    function normalizeCustomBasemaps(value) {{
      const seen = new Set();
      return (Array.isArray(value) ? value : []).slice(0, 100).map(normalizeCustomBasemap).filter(meta => {{
        if (!meta || seen.has(meta.id)) return false;
        seen.add(meta.id);
        return true;
      }});
    }}
    function serializableCustomBasemap(meta) {{
      const fields = ['id', 'name', 'type', 'url', 'provider', 'attribution', 'sourceUrl', 'note', 'subdomains', 'layers', 'styles', 'format', 'version', 'tileMatrixSet', 'matrixPrefix', 'minZoom', 'maxZoom', 'maxNativeZoom', 'bounds', 'crs', 'bandCount', 'transparent'];
      return Object.fromEntries(fields.map(key => [key, meta?.[key]]).filter(([, value]) => value !== undefined && value !== ''));
    }}
    function customBasemapSignature(meta) {{
      return JSON.stringify(serializableCustomBasemap(meta));
    }}
    function appendTilePath(url, path) {{
      const parts = String(url || '').split('?');
      const base = parts.shift().replace(/\/+$/, '');
      const query = parts.join('?');
      return `${{base}}${{path}}${{query ? `?${{query}}` : ''}}`;
    }}
    function arcgisTileUrl(meta) {{
      const url = String(meta.url || '').trim();
      return /\/tile\/\{{z\}}\/\{{y\}}\/\{{x\}}/i.test(url) ? url : appendTilePath(url, '/tile/{{z}}/{{y}}/{{x}}');
    }}
    function wmtsTileUrl(meta) {{
      const source = String(meta.url || '').trim();
      if (/\{{(?:TileMatrix|TileRow|TileCol)\}}/i.test(source)) {{
        return source
          .replace(/\{{TileMatrix\}}/gi, `${{meta.matrixPrefix || ''}}{{z}}`)
          .replace(/\{{TileRow\}}/gi, '{{y}}')
          .replace(/\{{TileCol\}}/gi, '{{x}}');
      }}
      const separator = source.includes('?') ? '&' : '?';
      const params = [
        'service=WMTS',
        'request=GetTile',
        `version=${{encodeURIComponent(meta.version || '1.0.0')}}`,
        `layer=${{encodeURIComponent(meta.layers || '')}}`,
        `style=${{encodeURIComponent(meta.styles || '')}}`,
        `tilematrixset=${{encodeURIComponent(meta.tileMatrixSet || 'GoogleMapsCompatible')}}`,
        `format=${{encodeURIComponent(meta.format || 'image/png')}}`,
        `tilematrix=${{encodeURIComponent(meta.matrixPrefix || '')}}{{z}}`,
        'tilerow={{y}}',
        'tilecol={{x}}',
      ];
      return `${{source}}${{separator}}${{params.join('&')}}`;
    }}
    function discardPmtilesArchive(url) {{
      const key = String(url || '').trim();
      if (key) pmtilesArchives.delete(key);
    }}
    function getPmtilesArchive(url, options = {{}}) {{
      if (!window.pmtiles?.PMTiles || !window.pmtiles?.leafletRasterLayer) {{
        throw new Error('PMTiles engine unavailable');
      }}
      const key = String(url || '').trim();
      if (options.refresh === true) pmtilesArchives.delete(key);
      if (!pmtilesArchives.has(key)) pmtilesArchives.set(key, new window.pmtiles.PMTiles(key));
      return pmtilesArchives.get(key);
    }}
    function discardCogSource(url) {{
      const key = String(url || '').trim();
      if (key) cogMetadataCache.delete(key);
    }}
    async function getCogSourceMetadata(url, options = {{}}) {{
      const key = String(url || '').trim();
      if (!key) throw new Error('COG URL is required');
      await ensureCogEngine();
      if (options.refresh === true) cogMetadataCache.delete(key);
      if (!cogMetadataCache.has(key)) {{
        const request = window.MaplibreCOGProtocol.getCogMetadata(key).catch(error => {{
          cogMetadataCache.delete(key);
          throw error;
        }});
        cogMetadataCache.set(key, request);
      }}
      return cogMetadataCache.get(key);
    }}
    function cogMapStyle(meta, overrideOptions = {{}}) {{
      const sourceId = 'easygee-cog-source';
      const layerId = 'easygee-cog-raster';
      const opacity = Math.max(0, Math.min(1, Number(overrideOptions.opacity ?? 1)));
      return {{
        version: 8,
        sources: {{
          [sourceId]: {{
            type: 'raster',
            url: `cog://${{meta.url}}`,
            tileSize: 256,
            ...(meta.attribution ? {{ attribution: meta.attribution }} : {{}}),
          }},
        }},
        layers: [{{
          id: layerId,
          source: sourceId,
          type: 'raster',
          paint: {{
            'raster-opacity': opacity,
            'raster-fade-duration': 0,
            'raster-resampling': 'linear',
          }},
        }}],
      }};
    }}
    function bindCogLayerEvents(group, glLayer) {{
      const glMap = glLayer?.getMaplibreMap?.();
      if (!glMap || glMap.__easygeeCogBound) return;
      glMap.__easygeeCogBound = true;
      let loaded = false;
      let ready = false;
      const markLoaded = event => {{
        if (loaded) return;
        if (event?.sourceId && event.sourceId !== 'easygee-cog-source') return;
        if (event?.sourceDataType && event.sourceDataType !== 'content') return;
        loaded = true;
        group.fire('tileload', {{ source: 'cog', event }});
      }};
      glMap.on('sourcedata', markLoaded);
      glMap.on('idle', () => {{
        try {{
          if (!glMap.getSource('easygee-cog-source') || !glMap.isSourceLoaded('easygee-cog-source')) return;
          markLoaded({{ sourceId: 'easygee-cog-source', sourceDataType: 'content' }});
          if (!ready) {{
            ready = true;
            group.fire('load', {{ source: 'cog' }});
          }}
        }} catch {{}}
      }});
      glMap.on('error', event => group.fire('tileerror', {{ source: 'cog', error: event?.error || event }}));
    }}
    function createCogBasemapLayer(meta, overrideOptions = {{}}) {{
      const group = L.layerGroup();
      group._easygeeCogLayer = null;
      group._easygeeCogMount = null;
      group._easygeeOpacity = Math.max(0, Math.min(1, Number(overrideOptions.opacity ?? 1)));
      const mount = async () => {{
        if (group._easygeeCogLayer) {{
          window.requestAnimationFrame(() => bindCogLayerEvents(group, group._easygeeCogLayer));
          return group._easygeeCogLayer;
        }}
        if (group._easygeeCogMount) return group._easygeeCogMount;
        group._easygeeCogMount = ensureCogEngine().then(() => {{
          const glLayer = L.maplibreGL({{
            style: cogMapStyle(meta, {{ ...overrideOptions, opacity: group._easygeeOpacity }}),
            interactive: false,
            pane: overrideOptions.pane || 'tilePane',
            attributionControl: false,
            className: 'easygee-cog-canvas',
            fadeDuration: 0,
          }});
          group._easygeeCogLayer = glLayer;
          group.addLayer(glLayer);
          if (map.hasLayer(group)) window.requestAnimationFrame(() => bindCogLayerEvents(group, glLayer));
          return glLayer;
        }}).catch(error => {{
          group._easygeeCogMount = null;
          group.fire('tileerror', {{ source: 'cog', error }});
          if (currentBasemap === meta.id && map.hasLayer(group)) handleBasemapRuntimeFailure(meta, error);
          throw error;
        }});
        return group._easygeeCogMount;
      }};
      group.on('add', () => {{ mount().catch(() => {{}}); }});
      group.setOpacity = value => {{
        group._easygeeOpacity = Math.max(0, Math.min(1, Number(value)));
        const glMap = group._easygeeCogLayer?.getMaplibreMap?.();
        try {{
          if (glMap?.getLayer('easygee-cog-raster')) glMap.setPaintProperty('easygee-cog-raster', 'raster-opacity', group._easygeeOpacity);
        }} catch {{}}
        return group;
      }};
      return group;
    }}
    function tiandituWmtsUrl(layer, token) {{
      return `https://t{{s}}.tianditu.gov.cn/${{layer}}_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=${{layer}}&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={{z}}&TILEROW={{y}}&TILECOL={{x}}&tk=${{encodeURIComponent(token)}}`;
    }}
    function createTiandituBasemapLayer(meta, overrideOptions = {{}}) {{
      if (!tiandituToken) throw new Error('Tianditu key required');
      const options = {{ ...(meta.options || {{}}), ...overrideOptions, subdomains: '01234567' }};
      const base = L.tileLayer(tiandituWmtsUrl(meta.tiandituBase, tiandituToken), {{ ...options, zIndex: 0 }});
      const labels = L.tileLayer(tiandituWmtsUrl(meta.tiandituLabels, tiandituToken), {{ ...options, zIndex: 1 }});
      const group = L.layerGroup([base, labels]);
      [base, labels].forEach(layer => {{
        layer.on('tileload', event => group.fire('tileload', event));
        layer.on('load', event => group.fire('load', event));
        layer.on('tileerror', event => group.fire('tileerror', event));
      }});
      group.setOpacity = value => {{
        const opacity = Math.max(0, Math.min(1, Number(value)));
        base.setOpacity(opacity);
        labels.setOpacity(opacity);
        return group;
      }};
      return group;
    }}
    function createBasemapLayer(meta, overrideOptions = {{}}) {{
      const options = {{ ...(meta.options || {{}}), ...overrideOptions }};
      if (isTiandituBasemap(meta)) return createTiandituBasemapLayer(meta, options);
      if (meta.custom && meta.type === 'pmtiles') {{
        return window.pmtiles.leafletRasterLayer(getPmtilesArchive(meta.url), options);
      }}
      if (meta.custom && meta.type === 'cog') return createCogBasemapLayer(meta, options);
      if (meta.custom && meta.type === 'wms') {{
        return L.tileLayer.wms(meta.url, {{
          ...options,
          layers: meta.layers,
          styles: meta.styles || '',
          format: meta.format || 'image/png',
          version: meta.version || '1.3.0',
          transparent: meta.transparent !== false,
        }});
      }}
      const tileUrl = meta.custom && meta.type === 'arcgis'
        ? arcgisTileUrl(meta)
        : meta.custom && meta.type === 'wmts'
          ? wmtsTileUrl(meta)
          : meta.url;
      return L.tileLayer(tileUrl, options);
    }}
    function tryCreateBasemapLayer(meta, overrideOptions = {{}}) {{
      try {{
        return createBasemapLayer(meta, overrideOptions);
      }} catch {{
        return null;
      }}
    }}
    function setRasterLayerOpacity(layer, value) {{
      const opacity = Math.max(0, Math.min(1, Number(value)));
      if (!layer || !Number.isFinite(opacity)) return false;
      if (typeof layer.setOpacity === 'function') {{
        layer.setOpacity(opacity);
        return true;
      }}
      if (typeof layer.eachLayer === 'function') {{
        layer.eachLayer(child => {{
          if (typeof child?.setOpacity === 'function') child.setOpacity(opacity);
        }});
        return true;
      }}
      return false;
    }}

    const BUILTIN_BASEMAPS = [
      {{
        id: 'OSM',
        nameKey: 'basemap.osm',
        noteKey: 'basemap.osmNote',
        thumb: 'osm',
        provider: 'OpenStreetMap contributors',
        service: 'OpenStreetMap Standard',
        sourceUrl: 'https://www.openstreetmap.org/copyright',
        url: 'https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
        options: {{ maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }}
      }},
      {{
        id: 'CartoLight',
        nameKey: 'basemap.light',
        noteKey: 'basemap.lightNote',
        thumb: 'light',
        provider: 'CARTO · OpenStreetMap contributors',
        service: 'CARTO Positron',
        sourceUrl: 'https://carto.com/basemaps/',
        url: 'https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}.png',
        options: {{ maxZoom: 20, attribution: '&copy; OpenStreetMap contributors &copy; CARTO' }}
      }},
      {{
        id: 'CartoDark',
        nameKey: 'basemap.dark',
        noteKey: 'basemap.darkNote',
        thumb: 'dark',
        provider: 'CARTO · OpenStreetMap contributors',
        service: 'CARTO Dark Matter',
        sourceUrl: 'https://carto.com/basemaps/',
        url: 'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}.png',
        options: {{ maxZoom: 20, attribution: '&copy; OpenStreetMap contributors &copy; CARTO' }}
      }},
      {{
        id: 'CartoVoyager',
        nameKey: 'basemap.voyager',
        noteKey: 'basemap.voyagerNote',
        thumb: 'voyager',
        provider: 'CARTO · OpenStreetMap contributors',
        service: 'CARTO Voyager',
        sourceUrl: 'https://carto.com/basemaps/',
        url: 'https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}.png',
        options: {{ maxZoom: 20, attribution: '&copy; OpenStreetMap contributors &copy; CARTO' }}
      }},
      {{
        id: 'EsriTopo',
        nameKey: 'basemap.topo',
        noteKey: 'basemap.topoNote',
        thumb: 'topo',
        provider: 'Esri',
        serviceKey: 'basemap.topoCoverage',
        sourceUrl: 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer',
        url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{{z}}/{{y}}/{{x}}',
        options: {{ maxZoom: 19, maxNativeZoom: 13, attribution: 'Tiles &copy; Esri' }}
      }},
      {{
        id: 'Imagery',
        nameKey: 'basemap.imagery',
        noteKey: 'basemap.imageryNote',
        thumb: 'imagery',
        provider: 'Esri',
        service: 'World Imagery',
        sourceUrl: 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer',
        url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
        options: {{ maxZoom: 19, attribution: 'Tiles &copy; Esri' }}
      }},
      {{
        id: 'EsriClarity',
        nameKey: 'basemap.esriClarity',
        noteKey: 'basemap.esriClarityNote',
        thumb: 'clarity',
        provider: 'Esri',
        service: 'World Imagery Clarity',
        sourceUrl: 'https://clarity.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer',
        url: 'https://clarity.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
        options: {{ maxZoom: 19, attribution: 'Tiles &copy; Esri (World Imagery Clarity)' }}
      }},
      {{
        id: 'TiandituVector',
        nameKey: 'basemap.tiandituVector',
        noteKey: 'basemap.tiandituVectorNote',
        thumb: 'tianditu-vector',
        provider: '国家基础地理信息中心 · 天地图',
        service: 'WMTS vec_w + cva_w',
        sourceUrl: 'https://lbs.tianditu.gov.cn/server/MapService.html',
        tiandituBase: 'vec',
        tiandituLabels: 'cva',
        options: {{ maxZoom: 22, maxNativeZoom: 18, attribution: '&copy; 天地图' }}
      }},
      {{
        id: 'TiandituImagery',
        nameKey: 'basemap.tiandituImagery',
        noteKey: 'basemap.tiandituImageryNote',
        thumb: 'tianditu-imagery',
        provider: '国家基础地理信息中心 · 天地图',
        service: 'WMTS img_w + cia_w',
        sourceUrl: 'https://lbs.tianditu.gov.cn/server/MapService.html',
        tiandituBase: 'img',
        tiandituLabels: 'cia',
        options: {{ maxZoom: 22, maxNativeZoom: 18, attribution: '&copy; 天地图' }}
      }},
      {{
        id: 'TiandituTerrain',
        nameKey: 'basemap.tiandituTerrain',
        noteKey: 'basemap.tiandituTerrainNote',
        thumb: 'tianditu-terrain',
        provider: '国家基础地理信息中心 · 天地图',
        service: 'WMTS ter_w + cta_w',
        sourceUrl: 'https://lbs.tianditu.gov.cn/server/MapService.html',
        tiandituBase: 'ter',
        tiandituLabels: 'cta',
        options: {{ maxZoom: 22, maxNativeZoom: 18, attribution: '&copy; 天地图' }}
      }}
    ];
    let customBasemaps = [];
    let defaultBasemapId = 'OSM';
    let BASEMAPS = [...BUILTIN_BASEMAPS];
    let primaryBasemapShown = STATE.basemapShown !== false;
    let primaryBasemapOpacity = Number.isFinite(Number(STATE.basemapOpacity))
      ? Math.max(0, Math.min(1, Number(STATE.basemapOpacity)))
      : 1;
    const basemapLayers = new Map();
    BASEMAPS.forEach(meta => {{
      const layer = tryCreateBasemapLayer(meta, {{ pane: PRIMARY_BASEMAP_PANE, opacity: primaryBasemapOpacity }});
      if (layer) basemapLayers.set(meta.id, bindBasemapPerformance(meta, layer));
    }});
    let currentBasemap = 'OSM';
    let basemapEditorId = null;
    let testedBasemapSignature = '';
    let testedCogDetails = null;
    beginBasemapPerformance(BASEMAPS.find(meta => meta.id === currentBasemap), basemapLayers.get(currentBasemap));
    if (primaryBasemapShown) basemapLayers.get(currentBasemap).addTo(map);
    function handleBasemapRuntimeFailure(meta, error) {{
      if (!meta || currentBasemap !== meta.id) return false;
      failBasemapPerformance(meta);
      const failedLayer = basemapLayers.get(meta.id);
      if (failedLayer && map.hasLayer(failedLayer)) map.removeLayer(failedLayer);
      const fallbackId = defaultBasemapId !== meta.id && basemapLayers.has(defaultBasemapId) ? defaultBasemapId : 'OSM';
      const fallbackLayer = basemapLayers.get(fallbackId);
      if (!fallbackLayer) return false;
      const fallbackMeta = BASEMAPS.find(item => item.id === fallbackId);
      beginBasemapPerformance(fallbackMeta, fallbackLayer);
      setRasterLayerOpacity(fallbackLayer, primaryBasemapOpacity);
      if (primaryBasemapShown && !map.hasLayer(fallbackLayer)) fallbackLayer.addTo(map);
      currentBasemap = fallbackId;
      cogEngineError = String(error?.message || error || 'COG layer failed').slice(0, 200);
      renderBasemapChoices();
      renderLayers();
      updateInspector();
      showModeKey('basemap.testFailed', {{ message: t('basemap.cogUnavailable') }}, true);
      syncSessionState('cog-basemap-fallback');
      return true;
    }}
    function rebuildBasemapRegistry(preferredBasemap = currentBasemap) {{
      const nextBasemaps = [...BUILTIN_BASEMAPS, ...customBasemaps];
      const nextLayers = new Map();
      nextBasemaps.forEach(meta => {{
        const layer = tryCreateBasemapLayer(meta, {{ pane: PRIMARY_BASEMAP_PANE, opacity: primaryBasemapOpacity }});
        bindBasemapPerformance(meta, layer);
        if (layer) nextLayers.set(meta.id, layer);
      }});
      const fallback = nextLayers.has(defaultBasemapId) ? defaultBasemapId : 'OSM';
      let nextBasemap = nextLayers.has(preferredBasemap) ? preferredBasemap : fallback;
      let nextLayer = nextLayers.get(nextBasemap) || nextLayers.get('OSM');
      if (!nextLayer) return currentBasemap;
      let nextMeta = nextBasemaps.find(item => item.id === nextBasemap);
      beginBasemapPerformance(nextMeta, nextLayer);
      fitCogBasemapBounds(nextMeta);
      try {{
        if (primaryBasemapShown) nextLayer.addTo(map);
      }} catch {{
        failBasemapPerformance(nextMeta);
        nextBasemap = 'OSM';
        nextLayer = nextLayers.get('OSM');
        if (!nextLayer) return currentBasemap;
        nextMeta = nextBasemaps.find(item => item.id === nextBasemap);
        beginBasemapPerformance(nextMeta, nextLayer);
        if (primaryBasemapShown) nextLayer.addTo(map);
      }}
      basemapLayers.forEach(layer => {{
        if (layer !== nextLayer && map.hasLayer(layer)) map.removeLayer(layer);
      }});
      BASEMAPS = nextBasemaps;
      basemapLayers.clear();
      nextLayers.forEach((layer, id) => basemapLayers.set(id, layer));
      currentBasemap = nextBasemap;
      if ($('basemap-list')) renderBasemapChoices();
      if ($('detail-name')) updateInspector();
      return currentBasemap;
    }}
    let aoiLayer = null;

    function basemapMetaById(id) {{
      const sourceId = String(id || '');
      return [...BUILTIN_BASEMAPS, ...customBasemaps].find(meta => meta.id === sourceId) || null;
    }}
    function isBasemapOverlayLayer(meta) {{
      return String(meta?.type || '').toLowerCase() === 'basemap-overlay';
    }}
    function basemapLayerDataset(meta) {{
      if (!meta) return '';
      const service = meta.serviceKey ? t(meta.serviceKey) : (meta.service || basemapDisplayNote(meta));
      return [meta.provider, service].filter(Boolean).join(' · ');
    }}
    function primaryBasemapLayerModel() {{
      const meta = currentBasemapMeta();
      return {{
        id: PRIMARY_BASEMAP_LAYER_ID,
        name: basemapDisplayName(meta),
        dataset: basemapLayerDataset(meta),
        type: 'primary-basemap',
        role: 'base',
        sourceId: meta?.id || currentBasemap,
        shown: primaryBasemapShown,
        opacity: primaryBasemapOpacity,
        styleProfile: 'basemap',
      }};
    }}

    function registerLayer(meta) {{
      const normalized = normalizeStateLayer(meta);
      if (!normalized) return null;
      operationalMapOrderDirty = true;
      if (isBasemapOverlayLayer(normalized)) {{
        const source = basemapMetaById(normalized.sourceId);
        if (!source) return null;
        const tile = tryCreateBasemapLayer(source, {{ opacity: normalized.opacity, pane: 'tilePane' }});
        if (!tile) return null;
        layerRegistry.set(normalized.id, {{ meta: normalized, tile, sourceId: source.id }});
        if (normalized.shown) tile.addTo(map);
        return tile;
      }}
      if (normalized.type === 'ee-restore-pending') {{
        const group = L.layerGroup();
        layerRegistry.set(normalized.id, {{ meta: normalized, tile: group }});
        if (normalized.shown) group.addTo(map);
        return group;
      }}
      if (isUploadPlaceholderLayer(normalized)) {{
        const group = L.layerGroup();
        layerRegistry.set(normalized.id, {{ meta: normalized, tile: group, refresh: () => {{}} }});
        if (normalized.shown) group.addTo(map);
        return group;
      }}
      if (isLocalVectorLayer(normalized)) {{
        const vector = createLocalVectorLayer(normalized);
        layerRegistry.set(normalized.id, {{ meta: normalized, tile: vector.layer, refresh: vector.refresh }});
        if (normalized.shown) vector.layer.addTo(map);
        return vector.layer;
      }}
      const tile = L.tileLayer(normalized.tileUrl, {{ opacity: normalized.opacity, attribution: 'Google Earth Engine' }});
      layerRegistry.set(normalized.id, {{ meta: normalized, tile }});
      if (normalized.shown) tile.addTo(map);
      return tile;
    }}
    STATE.layers.forEach(meta => {{
      registerLayer(meta);
    }});

    function isReorderableLayer(id) {{
      return Boolean(id) && id !== PRIMARY_BASEMAP_LAYER_ID
        && rawOperationalLayerModels().some(layer => String(layer.id) === String(id));
    }}
    function rawOperationalLayerModels() {{
      return [measurementsLayerModel(), aoiLayerModel(), ...STATE.layers].filter(Boolean);
    }}
    function normalizedOperationalLayerOrder(order = operationalLayerOrder) {{
      const available = rawOperationalLayerModels().map(layer => String(layer.id));
      const availableSet = new Set(available);
      const requested = Array.isArray(order) ? order.map(value => String(value)) : [];
      const known = [...new Set(requested)].filter(id => availableSet.has(id));
      return [...known, ...available.filter(id => !known.includes(id))];
    }}
    function syncOperationalLayerOrder() {{
      const next = normalizedOperationalLayerOrder(operationalLayerOrder);
      if (JSON.stringify(next) !== JSON.stringify(operationalLayerOrder)) operationalMapOrderDirty = true;
      operationalLayerOrder = next;
      return operationalLayerOrder;
    }}
    function placeOperationalLayer(id, position = 'front') {{
      const next = syncOperationalLayerOrder().filter(item => item !== String(id));
      if (position === 'front') next.unshift(String(id));
      else next.push(String(id));
      operationalLayerOrder = normalizedOperationalLayerOrder(next);
      operationalMapOrderDirty = true;
    }}
    function removeOperationalLayerOrder(id) {{
      operationalLayerOrder = normalizedOperationalLayerOrder(syncOperationalLayerOrder().filter(item => item !== String(id)));
      operationalMapOrderDirty = true;
    }}
    function operationalMapLayer(id) {{
      if (id === AOI_LAYER_ID) return aoiLayer;
      if (id === MEASUREMENTS_LAYER_ID) return measureLayer;
      return layerRegistry.get(id)?.tile || null;
    }}
    function syncLayerOrderToMap() {{
      const models = operationalLayerModels();
      if (!operationalMapOrderDirty) return;
      models.forEach(layer => {{
        const mapLayer = operationalMapLayer(layer.id);
        if (mapLayer && map.hasLayer(mapLayer)) map.removeLayer(mapLayer);
      }});
      [...models].reverse().forEach(layer => {{
        const mapLayer = operationalMapLayer(layer.id);
        if (layer.shown !== false && mapLayer && !map.hasLayer(mapLayer)) mapLayer.addTo(map);
      }});
      operationalMapOrderDirty = false;
    }}
    function reorderLayer(sourceId, targetId) {{
      if (!isReorderableLayer(sourceId) || !isReorderableLayer(targetId) || sourceId === targetId) return false;
      const order = syncOperationalLayerOrder().filter(id => id !== String(sourceId));
      const targetIndex = order.indexOf(String(targetId));
      if (targetIndex < 0) return false;
      order.splice(targetIndex, 0, String(sourceId));
      operationalLayerOrder = normalizedOperationalLayerOrder(order);
      operationalMapOrderDirty = true;
      const moved = rawOperationalLayerModels().find(layer => String(layer.id) === String(sourceId));
      syncLayerOrderToMap();
      renderLayers();
      setActiveLayer(sourceId, {{ reveal: false }});
      showModeKey('mode.layerReordered');
      logMsg('log.layerReordered', {{ layer: moved?.name || sourceId }});
      syncSessionState('layer-reordered');
      return true;
    }}

    function addGeneratedLayer(meta, options = {{}}) {{
      const existingIndex = STATE.layers.findIndex(layer => layer.id === meta.id);
      if (existingIndex >= 0) {{
        const existing = layerRegistry.get(meta.id);
        if (existing && map.hasLayer(existing.tile)) map.removeLayer(existing.tile);
        STATE.layers.splice(existingIndex, 1);
        removeOperationalLayerOrder(meta.id);
      }}
      const nextMeta = normalizeStateLayer({{ ...meta, shown: options.shown === undefined ? true : options.shown !== false }});
      STATE.layers.unshift(nextMeta);
      placeOperationalLayer(nextMeta.id, 'front');
      const tile = registerLayer(nextMeta);
      if (nextMeta.shown && !map.hasLayer(tile)) tile.addTo(map);
      $('layer-count').textContent = t('pill.layers', {{ count: layerCount() }});
      renderLayers();
      renderDatasets(filteredCatalog());
      if (options.activate !== false) setActiveLayer(nextMeta.id);
      if (options.sync !== false) syncSessionState('layer-added');
      return nextMeta;
    }}

    function revealLayerPanel(id) {{
      document.querySelector('.data-panel').classList.remove('open');
      document.querySelector('.upload-panel').classList.remove('open');
      document.querySelector('.basemap-panel').classList.remove('open');
      document.querySelector('.right').classList.remove('open');
      document.querySelector('.bottom').classList.remove('open');
      document.querySelector('.layers-panel').classList.add('open');
      syncToolState();
      if (id) setActiveLayer(id);
    }}
    function addBasemapOverlay(sourceId) {{
      const meta = basemapMetaById(sourceId);
      if (!meta) return false;
      if (isTiandituBasemap(meta) && !tiandituToken) return requestTiandituToken();
      const existing = STATE.layers.find(layer => isBasemapOverlayLayer(layer) && layer.sourceId === meta.id);
      if (existing) {{
        setLayerVisibility(existing.id, true, {{ reveal: false, reason: 'basemap-overlay-visible' }});
        revealLayerPanel(existing.id);
        renderBasemapChoices();
        return existing.id;
      }}
      const safeSourceId = String(meta.id || 'basemap').replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+|-+$/g, '').slice(0, 48) || 'basemap';
      const nextMeta = normalizeStateLayer({{
        id: `basemap-overlay-${{safeSourceId}}-${{Date.now().toString(36)}}`,
        name: basemapDisplayName(meta),
        dataset: basemapLayerDataset(meta),
        type: 'basemap-overlay',
        role: 'overlay',
        sourceId: meta.id,
        shown: true,
        opacity: 1,
        styleProfile: 'basemap',
      }});
      const tile = registerLayer(nextMeta);
      if (!tile) return false;
      STATE.layers.unshift(nextMeta);
      placeOperationalLayer(nextMeta.id, 'front');
      renderLayers();
      renderBasemapChoices();
      revealLayerPanel(nextMeta.id);
      showModeKey('mode.basemapOverlayAdded', {{ basemap: nextMeta.name }});
      logMsg('log.basemapOverlayAdded', {{ basemap: nextMeta.name }});
      syncSessionState('basemap-overlay-added');
      return nextMeta.id;
    }}
    function reloadBasemapOverlays(sourceId) {{
      const overlays = STATE.layers.filter(layer => isBasemapOverlayLayer(layer) && layer.sourceId === sourceId);
      overlays.forEach(meta => {{
        const record = layerRegistry.get(meta.id);
        if (record && map.hasLayer(record.tile)) map.removeLayer(record.tile);
        layerRegistry.delete(meta.id);
        registerLayer(meta);
      }});
      if (overlays.length) renderLayers();
      return overlays.length;
    }}

    function aoiLayerModel() {{
      if (!hasAoi()) return null;
      return {{
        id: AOI_LAYER_ID,
        name: 'AOI',
        dataset: STATE.aoi.type === 'polygon' ? 'Drawn polygon AOI' : 'Drawn rectangle AOI',
        type: 'aoi',
        shown: STATE.aoiShown !== false,
        opacity: STATE.aoiStyle.opacity,
        styleProfile: 'aoi',
        legend: [[STATE.aoiStyle.color, 'AOI boundary']],
      }};
    }}
    function hasMeasurements() {{
      return measurementSummary().count > 0;
    }}
    function measurementsLayerModel() {{
      const summary = measurementSummary();
      if (!summary.count) return null;
      return {{
        id: MEASUREMENTS_LAYER_ID,
        name: t('measurements.layerName'),
        dataset: t('measurements.layerDataset', {{ count: summary.count }}),
        type: 'measurements',
        shown: STATE.measurementsShown !== false,
        opacity: normalizeMeasurementsOpacity(STATE.measurementsOpacity),
        styleProfile: 'measurements',
        legend: [[DEFAULT_MEASUREMENTS_STYLE.color, t('measurements.legend')]],
        summary,
      }};
    }}
    function operationalLayerModels() {{
      const available = new Map(rawOperationalLayerModels().map(layer => [String(layer.id), layer]));
      return syncOperationalLayerOrder().map(id => available.get(id)).filter(Boolean);
    }}
    function layerModels() {{
      return [...operationalLayerModels(), primaryBasemapLayerModel()];
    }}
    function layerCount() {{
      return layerModels().length;
    }}
    function renderAoiLayer() {{
      if (aoiLayer && map.hasLayer(aoiLayer)) map.removeLayer(aoiLayer);
      aoiLayer = null;
      operationalMapOrderDirty = true;
      if (!hasAoi() || STATE.aoiShown === false) {{
        syncLayerOrderToMap();
        return;
      }}
      STATE.aoiStyle = normalizeAoiStyle(STATE.aoiStyle);
      const options = {{
        color: STATE.aoiStyle.color,
        weight: STATE.aoiStyle.weight,
        opacity: STATE.aoiStyle.opacity,
        fill: true,
        fillColor: STATE.aoiStyle.fillColor,
        fillOpacity: STATE.aoiStyle.fillOpacity,
      }};
      if (STATE.aoi.type === 'polygon') {{
        aoiLayer = L.polygon(STATE.aoi.coordinates, options).addTo(map);
      }} else {{
        aoiLayer = L.rectangle(STATE.aoi.bounds, options).addTo(map);
      }}
      syncLayerOrderToMap();
    }}

    const measureLayer = L.layerGroup().addTo(map);
    const measureDraftLayer = L.layerGroup().addTo(map);
    const drawAoiLayer = L.layerGroup().addTo(map);
    let drawAoiMode = false;
    let drawPolygonMode = false;
    let drawAoiStart = null;
    let drawAoiPreview = null;
    let drawPolygonPoints = [];
    let polygonDoubleClickZoomWasEnabled = false;
    let measureMode = false;
    let measurementLayerNotice = false;
    let measurePoints = [];

    function chooseScaleDistance(maxMeters) {{
      if (!Number.isFinite(maxMeters) || maxMeters <= 0) return 1;
      const exponent = Math.floor(Math.log10(maxMeters));
      for (let exp = exponent; exp >= -1; exp -= 1) {{
        for (const base of [5, 2, 1]) {{
          const candidate = base * (10 ** exp);
          if (candidate <= maxMeters) return candidate;
        }}
      }}
      return 1;
    }}
    function updateScaleLine() {{
      const size = map.getSize();
      if (!size.x || !size.y) return;
      const targetPx = 88;
      const y = Math.max(0, size.y - 20);
      const start = map.containerPointToLatLng([58, y]);
      const end = map.containerPointToLatLng([58 + targetPx, y]);
      const maxMeters = distanceMeters(start, end);
      const meters = chooseScaleDistance(maxMeters);
      const px = Math.max(34, Math.min(targetPx, Math.round((meters / maxMeters) * targetPx)));
      $('scale-track').style.width = `${{px}}px`;
      $('scale-label').style.width = `${{px}}px`;
      $('scale-label').textContent = formatScaleDistance(meters);
    }}

    function datasetItemHtml(item) {{
      const readyCount = datasetLayerIds(item.id).length;
      const ready = readyCount > 0;
      const pending = pendingDatasetIds.has(item.id);
      const failed = failedDatasetIds.has(item.id);
      const addTitle = pending ? t('data.processing') : t('data.addTitle');
      const provider = item.provider ? `<div class="dataset-provider">${{escapeHtml(item.provider)}}</div>` : '';
      const tagsText = [catalogCategoryLabel(catalogCategoryKey(item)), item.tags, item.license].filter(Boolean).join(' · ');
      const tags = tagsText ? `<div class="dataset-tags">${{escapeHtml(tagsText)}}</div>` : '';
      const statusKey = pending ? 'data.processing' : failed ? 'data.failed' : ready ? 'data.ready' : '';
      const statusText = ready ? t(statusKey, {{ count: readyCount }}) : statusKey ? t(statusKey) : '';
      const statusClass = pending ? 'pending' : failed ? 'error' : ready ? '' : 'muted';
      const typeLabel = catalogTypeLabel(normalizeCatalogType(item));
      const attrs = datasetAttrsHtml(item, typeLabel);
      const favorite = isFavoriteDataset(item.id);
      const favoriteTitle = favorite ? t('data.unfavoriteTitle') : t('data.favoriteTitle');
      const sourceLabel = catalogSourceLabel(item);
      return `
        <div class="dataset-item ${{activeDatasetId === item.id ? 'active' : ''}}" data-dataset="${{escapeHtml(item.id)}}" role="button" tabindex="0">
          <div>
            <div class="dataset-name">${{escapeHtml(item.label)}}</div>
            <div class="dataset-meta">${{escapeHtml(item.id)}} | ${{escapeHtml(typeLabel)}} | ${{escapeHtml(sourceLabel)}} | ${{escapeHtml(item.scale || item.category || '')}}</div>
            ${{attrs}}
            ${{tags}}
            ${{provider}}
            ${{statusText ? `<div class="dataset-status ${{statusClass}}">${{escapeHtml(statusText)}}</div>` : ''}}
          </div>
          <div class="dataset-actions">
            <button class="dataset-favorite icon-btn ${{favorite ? 'active' : ''}}" data-action="favorite" title="${{escapeHtml(favoriteTitle)}}" aria-label="${{escapeHtml(favoriteTitle)}}" aria-pressed="${{favorite ? 'true' : 'false'}}" type="button">{svg_icon("favorite")}</button>
            <button class="dataset-add icon-btn" data-action="add" title="${{escapeHtml(addTitle)}}" aria-label="${{escapeHtml(addTitle)}}" type="button" ${{pending ? 'disabled' : ''}}>{svg_icon("add")}</button>
          </div>
        </div>
      `;
    }}

    function updateCatalogCount() {{
      const total = Array.isArray(STATE.catalog) ? STATE.catalog.length : 0;
      const matches = catalogListItems.length;
      const shown = Math.min(catalogRenderedCount, matches);
      $('catalog-count').textContent = matches === total
        ? t('pill.datasetLoaded', {{ shown, matches }})
        : t('pill.datasetLoadedFiltered', {{ shown, matches, total }});
    }}

    function bindDatasetItems(scope) {{
      scope.querySelectorAll('.dataset-item:not([data-bound])').forEach(item => {{
        item.dataset.bound = 'true';
        item.addEventListener('click', event => {{
          if (event.target.closest('[data-action="add"], [data-action="favorite"]')) return;
          document.querySelectorAll('.dataset-item').forEach(item => item.classList.remove('active'));
          item.classList.add('active');
          setActiveDataset(item.dataset.dataset);
        }});
        item.addEventListener('keydown', event => {{
          if (event.key !== 'Enter' && event.key !== ' ') return;
          event.preventDefault();
          setActiveDataset(item.dataset.dataset);
        }});
        item.querySelector('[data-action="add"]').addEventListener('click', event => {{
          event.stopPropagation();
          importDatasetToMap(item.dataset.dataset);
        }});
        item.querySelector('[data-action="favorite"]').addEventListener('click', event => {{
          event.stopPropagation();
          toggleFavoriteDataset(item.dataset.dataset);
        }});
      }});
    }}

    function appendDatasetBatch() {{
      const list = $('dataset-list');
      if (!catalogListItems.length || catalogRenderedCount >= catalogListItems.length) return;
      const start = catalogRenderedCount;
      catalogRenderedCount = Math.min(catalogRenderedCount + CATALOG_RENDER_BATCH, catalogListItems.length);
      const nextItems = catalogListItems.slice(start, catalogRenderedCount);
      list.querySelector('.dataset-loading')?.remove();
      list.insertAdjacentHTML('beforeend', nextItems.map(datasetItemHtml).join(''));
      bindDatasetItems(list);
      updateCatalogCount();
      if (catalogRenderedCount < catalogListItems.length) {{
        list.insertAdjacentHTML('beforeend', `<div class="dataset-loading">${{escapeHtml(t('data.loadingMore'))}}</div>`);
      }}
    }}

    function maybeLoadMoreDatasets() {{
      const list = $('dataset-list');
      if (catalogRenderedCount >= catalogListItems.length) return;
      if (list.scrollTop + list.clientHeight >= list.scrollHeight - 160) {{
        appendDatasetBatch();
      }}
    }}

    function renderDatasets(items) {{
      renderCatalogFacets();
      catalogListItems = items;
      catalogRenderedCount = 0;
      const list = $('dataset-list');
      if (activeDatasetId && !datasetById(activeDatasetId)) {{
        activeDatasetId = null;
        closeDatasetDetail();
        syncSessionState('selected-dataset');
      }}
      if (!items.length) {{
        updateCatalogCount();
        list.innerHTML = `<div class="dataset-empty">${{escapeHtml(t(catalogFavoriteFilter ? 'data.noFavorites' : 'data.noResults'))}}</div>`;
        return;
      }}
      list.innerHTML = '';
      appendDatasetBatch();
      list.scrollTop = 0;
    }}

    async function requestCatalogLayer(datasetId) {{
      const item = (Array.isArray(STATE.catalog) ? STATE.catalog : []).find(entry => entry.id === datasetId) || {{ id: datasetId }};
      pendingDatasetIds.add(datasetId);
      failedDatasetIds.delete(datasetId);
      renderDatasets(filteredCatalog());
      showModeKey('mode.datasetBuilding', {{ dataset: datasetId }}, true);
      logMsg('log.datasetBuilding', {{ dataset: datasetId }});
      try {{
        const response = await fetch('/api/layer', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            project: STATE.project,
            datasetId,
            catalogItem: item,
            recipe: defaultPreviewRecipeForDataset(item),
            aoi: currentProcessingAoi(),
            bounds: currentProcessingBounds(),
            startDate: STATE.startDate,
            endDate: STATE.endDate,
            cloudPct: STATE.cloudPct,
            zoom: map.getZoom(),
            center: [map.getCenter().lat, map.getCenter().lng],
          }}),
        }});
        const payload = await response.json().catch(() => ({{ ok: false, error: response.statusText || 'request failed' }}));
        if (!response.ok || !payload.ok || !payload.layer) {{
          throw new Error(payload.error || `HTTP ${{response.status}}`);
        }}
        addGeneratedLayer(payload.layer);
        showModeKey('mode.datasetAdded', {{ count: 1 }});
        logMsg('log.datasetAdded', {{ dataset: datasetId }});
        return true;
      }} catch (error) {{
        const message = error && error.message ? error.message : String(error);
        failedDatasetIds.set(datasetId, message);
        showModeKey('mode.datasetFailed', {{ message: message.slice(0, 90) }}, true);
        logMsg('log.datasetFailed', {{ dataset: datasetId }});
        return false;
      }} finally {{
        pendingDatasetIds.delete(datasetId);
        renderDatasets(filteredCatalog());
        syncToolState();
      }}
    }}

    async function importDatasetToMap(datasetId) {{
      setActiveDataset(datasetId);
      const ids = datasetLayerIds(datasetId);
      if (!ids.length) {{
        return requestCatalogLayer(datasetId);
      }}
      ids.forEach(id => {{
        const record = layerRegistry.get(id);
        if (!record) return;
        record.meta.shown = true;
        if (!map.hasLayer(record.tile)) record.tile.addTo(map);
      }});
      renderLayers();
      setActiveLayer(ids[0]);
      showModeKey('mode.datasetAdded', {{ count: ids.length }});
      logMsg('log.datasetAdded', {{ dataset: datasetId }});
      return true;
    }}

    async function refreshCatalogFromApi() {{
      try {{
        const response = await fetch('/api/catalog');
        if (!response.ok) return false;
        const payload = await response.json();
        if (!payload || !Array.isArray(payload.catalog) || !payload.catalog.length) return false;
        STATE.catalog = payload.catalog;
        STATE.catalogSource = payload.source || STATE.catalogSource;
        renderDatasets(filteredCatalog());
        logMsg('log.catalogLoaded', {{ count: STATE.catalog.length }});
        return true;
      }} catch {{
        return false;
      }}
    }}

    function clearAoi() {{
      STATE.aoi = null;
      STATE.bounds = null;
      STATE.aoiShown = true;
      removeOperationalLayerOrder(AOI_LAYER_ID);
      STATE.aoiStyle = normalizeAoiStyle(STATE.aoiStyle);
      persistAoi();
      renderAoiLayer();
      renderLayers();
      if (activeLayerId === AOI_LAYER_ID) setActiveLayer(STATE.layers[0]?.id || PRIMARY_BASEMAP_LAYER_ID, {{ reveal: false }});
      syncSessionState('aoi-cleared');
      logMsg('log.aoiCleared');
      return true;
    }}
    function removeLayer(id) {{
      if (id === PRIMARY_BASEMAP_LAYER_ID) return false;
      if (id === AOI_LAYER_ID) return clearAoi();
      if (id === MEASUREMENTS_LAYER_ID) return clearMeasurements();
      const index = STATE.layers.findIndex(layer => layer.id === id);
      if (index < 0) return false;
      const [layer] = STATE.layers.splice(index, 1);
      removeOperationalLayerOrder(id);
      const record = layerRegistry.get(id);
      if (record && map.hasLayer(record.tile)) map.removeLayer(record.tile);
      layerRegistry.delete(id);
      let nextActive = null;
      if (activeLayerId === id) {{
        nextActive = measurementsLayerModel()?.id || aoiLayerModel()?.id || STATE.layers.find(item => item.shown)?.id || STATE.layers[0]?.id || PRIMARY_BASEMAP_LAYER_ID;
        activeLayerId = null;
      }}
      renderLayers();
      if (nextActive) setActiveLayer(nextActive, {{ reveal: false }});
      else updateInspector();
      renderDatasets(filteredCatalog());
      logMsg('log.layerRemoved', {{ layer: layer.name }});
      syncSessionState('layer-removed');
      return true;
    }}

    function refreshLayer(id, options = {{}}) {{
      if (!id) return false;
      if (id === PRIMARY_BASEMAP_LAYER_ID) {{
        rebuildBasemapRegistry(currentBasemap);
        renderLayers();
        if (activeLayerId === id) updateInspector();
        syncSessionState(options.reason || 'basemap-refreshed');
        return true;
      }}
      if (id === AOI_LAYER_ID) {{
        if (!hasAoi()) return false;
        const layer = aoiLayerModel();
        renderAoiLayer();
        renderLayers();
        if (activeLayerId === AOI_LAYER_ID) updateInspector();
        logMsg('log.layerRefreshed', {{ layer: layer?.name || 'AOI' }});
        syncSessionState(options.reason || 'aoi-refreshed');
        return true;
      }}
      if (id === MEASUREMENTS_LAYER_ID) {{
        if (!hasMeasurements()) return false;
        const layer = measurementsLayerModel();
        renderMeasurements();
        renderLayers();
        if (activeLayerId === MEASUREMENTS_LAYER_ID) updateInspector();
        logMsg('log.layerRefreshed', {{ layer: layer?.name || 'Measurements' }});
        syncSessionState(options.reason || 'measurements-refreshed');
        return true;
      }}
      const index = STATE.layers.findIndex(layer => layer.id === id);
      if (index < 0) return false;
      const meta = STATE.layers[index];
      if (meta.type === 'ee-restore-pending') {{
        showModeKey('mode.datasetBuilding', {{ dataset: meta.dataset || meta.name }}, true);
        rebuildProfileLayer(meta).then(restored => {{
          if (restored) {{
            renderLayers();
            setActiveLayer(id, {{ reveal: false }});
            showModeKey('mode.datasetAdded', {{ count: 1 }});
            syncSessionState('layer-restored');
          }} else {{
            showModeKey('mode.datasetFailed', {{ message: String(meta.dataset || meta.name).slice(0, 90) }}, true);
          }}
        }});
        return true;
      }}
      const previousRecord = layerRegistry.get(id);
      const shouldShow = previousRecord ? map.hasLayer(previousRecord.tile) : meta.shown !== false;
      if (previousRecord && map.hasLayer(previousRecord.tile)) map.removeLayer(previousRecord.tile);
      layerRegistry.delete(id);
      const token = Date.now();
      layerRefreshTokens.set(id, token);
      meta.shown = shouldShow;
      const refreshMeta = meta.tileUrl
        ? {{ ...meta, tileUrl: appendCacheBust(meta.tileUrl, token), shown: shouldShow }}
        : {{ ...meta, shown: shouldShow }};
      const tile = registerLayer(refreshMeta);
      if (shouldShow && tile && !map.hasLayer(tile)) tile.addTo(map);
      renderLayers();
      if (activeLayerId === id) setActiveLayer(id, {{ reveal: false }});
      else updateInspector();
      logMsg('log.layerRefreshed', {{ layer: meta.name }});
      syncSessionState(options.reason || 'layer-refreshed');
      return true;
    }}

    function setLayerVisibility(id, shown, options = {{}}) {{
      const nextShown = shown !== false;
      if (id === PRIMARY_BASEMAP_LAYER_ID) {{
        const layer = basemapLayers.get(currentBasemap);
        if (!layer) return false;
        primaryBasemapShown = nextShown;
        if (nextShown) {{
          setRasterLayerOpacity(layer, primaryBasemapOpacity);
          if (!map.hasLayer(layer)) layer.addTo(map);
          logMsg('log.layerOn', {{ layer: basemapDisplayName(currentBasemapMeta()) }});
        }} else {{
          if (map.hasLayer(layer)) map.removeLayer(layer);
          logMsg('log.layerOff', {{ layer: basemapDisplayName(currentBasemapMeta()) }});
        }}
        renderLayers();
        if (options.activate !== false) setActiveLayer(PRIMARY_BASEMAP_LAYER_ID, {{ reveal: options.reveal !== false }});
        else updateInspector();
        syncSessionState(options.reason || 'basemap-visibility');
        return true;
      }}
      operationalMapOrderDirty = true;
      if (id === AOI_LAYER_ID) {{
        if (!hasAoi()) return false;
        STATE.aoiShown = nextShown;
        STATE.aoiStyle = normalizeAoiStyle({{ ...STATE.aoiStyle, shown: nextShown }});
        renderAoiLayer();
        renderLayers();
        if (nextShown && options.activate !== false) {{
          setActiveLayer(AOI_LAYER_ID, {{ reveal: options.reveal !== false }});
        }} else if (!nextShown && activeLayerId === AOI_LAYER_ID) {{
          setActiveLayer(STATE.layers.find(item => item.shown)?.id || STATE.layers[0]?.id || PRIMARY_BASEMAP_LAYER_ID, {{ reveal: false }});
        }} else {{
          updateInspector();
        }}
        syncSessionState(options.reason || 'aoi-visibility');
        return true;
      }}
      if (id === MEASUREMENTS_LAYER_ID) {{
        if (!hasMeasurements()) return false;
        STATE.measurementsShown = nextShown;
        renderMeasurements();
        renderLayers();
        if (nextShown && options.activate !== false) {{
          setActiveLayer(MEASUREMENTS_LAYER_ID, {{ reveal: options.reveal !== false }});
        }} else if (!nextShown && activeLayerId === MEASUREMENTS_LAYER_ID) {{
          setActiveLayer(aoiLayerModel()?.id || STATE.layers.find(item => item.shown)?.id || STATE.layers[0]?.id || PRIMARY_BASEMAP_LAYER_ID, {{ reveal: false }});
        }} else {{
          updateInspector();
        }}
        syncSessionState(options.reason || 'measurements-visibility');
        return true;
      }}
      const record = layerRegistry.get(id);
      if (!record) return false;
      const stateLayer = STATE.layers.find(item => item.id === id);
      if (stateLayer) stateLayer.shown = nextShown;
      record.meta.shown = nextShown;
      if (nextShown) {{
        if (!map.hasLayer(record.tile)) record.tile.addTo(map);
        logMsg('log.layerOn', {{ layer: record.meta.name }});
      }} else {{
        if (map.hasLayer(record.tile)) map.removeLayer(record.tile);
        logMsg('log.layerOff', {{ layer: record.meta.name }});
      }}
      renderLayers();
      if (nextShown && options.activate !== false) {{
        setActiveLayer(id, {{ reveal: options.reveal !== false }});
      }} else if (!nextShown && activeLayerId === id) {{
        setActiveLayer(measurementsLayerModel()?.id || aoiLayerModel()?.id || STATE.layers.find(item => item.shown)?.id || STATE.layers[0]?.id || PRIMARY_BASEMAP_LAYER_ID, {{ reveal: false }});
      }} else {{
        updateInspector();
      }}
      syncSessionState(options.reason || 'layer-visibility');
      return true;
    }}

    function setLayerOpacity(id, value, options = {{}}) {{
      const opacity = Math.max(0, Math.min(1, Number(value)));
      if (!Number.isFinite(opacity)) return false;
      if (id === PRIMARY_BASEMAP_LAYER_ID) {{
        const layer = basemapLayers.get(currentBasemap);
        if (!layer) return false;
        primaryBasemapOpacity = opacity;
        setRasterLayerOpacity(layer, opacity);
        if (options.render !== false) renderLayers();
        if (activeLayerId === id) updateInspector();
        syncSessionState(options.reason || 'basemap-opacity');
        return true;
      }}
      if (id === AOI_LAYER_ID) {{
        if (!hasAoi()) return false;
        STATE.aoiStyle = normalizeAoiStyle({{ ...STATE.aoiStyle, opacity }});
        renderAoiLayer();
        if (options.render !== false) renderLayers();
        if (activeLayerId === id) updateInspector();
        syncSessionState(options.reason || 'aoi-opacity');
        return true;
      }}
      if (id === MEASUREMENTS_LAYER_ID) {{
        if (!hasMeasurements()) return false;
        STATE.measurementsOpacity = opacity;
        renderMeasurements();
        if (options.render !== false) renderLayers();
        if (activeLayerId === id) updateInspector();
        syncSessionState(options.reason || 'measurements-opacity');
        return true;
      }}
      const record = layerRegistry.get(id);
      if (!record) return false;
      const stateLayer = STATE.layers.find(item => item.id === id);
      if (stateLayer) stateLayer.opacity = opacity;
      record.meta.opacity = opacity;
      if (typeof record.tile.setOpacity === 'function') {{
        record.tile.setOpacity(opacity);
      }} else if (typeof record.refresh === 'function') {{
        record.refresh();
      }}
      if (options.render !== false) renderLayers();
      if (activeLayerId === id) updateInspector();
      syncSessionState(options.reason || 'layer-opacity');
      return true;
    }}

    function usableLayerBounds(bounds) {{
      try {{
        return Boolean(bounds && typeof bounds.isValid === 'function' && bounds.isValid());
      }} catch {{
        return false;
      }}
    }}
    function layerBoundsFromValue(value) {{
      if (usableLayerBounds(value)) return value;
      const normalized = normalizeBounds(value);
      if (normalized) return L.latLngBounds(normalized);
      if (!Array.isArray(value) || value.length !== 4) return null;
      const [west, south, east, north] = value.map(Number);
      if (![west, south, east, north].every(Number.isFinite)) return null;
      if (west >= east || south >= north || west < -180 || east > 180 || south < -90 || north > 90) return null;
      return L.latLngBounds([[south, west], [north, east]]);
    }}
    function renderedVectorBounds(record) {{
      const candidates = [record?.tile?.__vectorOverlay, record?.tile];
      for (const candidate of candidates) {{
        if (!candidate || typeof candidate.getBounds !== 'function') continue;
        try {{
          const bounds = candidate.getBounds();
          if (usableLayerBounds(bounds)) return bounds;
        }} catch {{}}
      }}
      const layers = typeof record?.tile?.getLayers === 'function' ? record.tile.getLayers() : [];
      if (!layers.length) return null;
      try {{
        const bounds = L.featureGroup(layers).getBounds();
        return usableLayerBounds(bounds) ? bounds : null;
      }} catch {{
        return null;
      }}
    }}
    function measurementsLayerBounds() {{
      const points = STATE.measurements.flatMap(item => [normalizeLatLngPair(item.start), normalizeLatLngPair(item.end)]).filter(Boolean);
      if (!points.length) return null;
      const bounds = L.latLngBounds(points);
      return usableLayerBounds(bounds) ? bounds : null;
    }}
    function normalizedLayerZoom(value, fallback = 18) {{
      const zoom = Number(value);
      return Number.isFinite(zoom) ? Math.max(0, Math.min(22, zoom)) : fallback;
    }}
    function layerModelById(id) {{
      if (id === PRIMARY_BASEMAP_LAYER_ID) return primaryBasemapLayerModel();
      if (id === AOI_LAYER_ID) return aoiLayerModel();
      if (id === MEASUREMENTS_LAYER_ID) return measurementsLayerModel();
      return STATE.layers.find(layer => layer.id === id) || null;
    }}
    async function basemapLayerExtent(meta) {{
      if (!meta) return null;
      const explicit = layerBoundsFromValue(meta.bounds) || cogBasemapBounds(meta);
      if (usableLayerBounds(explicit)) {{
        return {{ bounds: explicit, maxZoom: Math.min(normalizedLayerZoom(meta.maxNativeZoom ?? meta.maxZoom), 18) }};
      }}
      if (meta.custom && meta.type === 'pmtiles') {{
        const inspection = await inspectPmtilesArchive(meta, {{ requireVisibleTile: false }});
        if (!inspection.ok) return null;
        const header = inspection.header || {{}};
        const values = [header.minLon, header.minLat, header.maxLon, header.maxLat].map(Number);
        const bounds = layerBoundsFromValue(values);
        if (!usableLayerBounds(bounds)) return null;
        return {{ bounds, maxZoom: Math.min(normalizedLayerZoom(header.maxZoom ?? meta.maxNativeZoom), 18) }};
      }}
      if (meta.custom && meta.type === 'cog') return null;
      return {{ bounds: L.latLngBounds([[-85.05112878, -180], [85.05112878, 180]]), maxZoom: 18 }};
    }}
    async function layerExtentById(id) {{
      if (id === PRIMARY_BASEMAP_LAYER_ID) return basemapLayerExtent(currentBasemapMeta());
      if (id === AOI_LAYER_ID) {{
        const bounds = layerBoundsFromValue(STATE.aoi?.bounds);
        return usableLayerBounds(bounds) ? {{ bounds, maxZoom: 18 }} : null;
      }}
      if (id === MEASUREMENTS_LAYER_ID) {{
        const bounds = measurementsLayerBounds();
        return usableLayerBounds(bounds) ? {{ bounds, maxZoom: 18 }} : null;
      }}
      const layer = STATE.layers.find(item => item.id === id);
      if (!layer) return null;
      if (isBasemapOverlayLayer(layer)) return basemapLayerExtent(basemapMetaById(layer.sourceId));
      const record = layerRegistry.get(id);
      if (isLocalVectorLayer(layer) && record?.tile?.__vectorReady) await record.tile.__vectorReady;
      const rendered = renderedVectorBounds(record);
      if (usableLayerBounds(rendered)) return {{ bounds: rendered, maxZoom: 18 }};
      const candidates = [
        layer.aoi?.bounds,
        layer.bounds,
        layer.recipe?.aoi?.bounds,
        layer.recipe?.bounds,
        layer.summary?.bounds,
      ];
      for (const candidate of candidates) {{
        const bounds = layerBoundsFromValue(candidate);
        if (usableLayerBounds(bounds)) return {{ bounds, maxZoom: 18 }};
      }}
      return null;
    }}
    async function zoomToLayer(id, options = {{}}) {{
      const layerId = String(id || activeLayerId || '');
      const layer = layerModelById(layerId);
      if (!layer) return false;
      showModeKey('mode.layerZooming', {{ layer: layer.name }}, true);
      let extent = null;
      try {{
        extent = await layerExtentById(layerId);
      }} catch {{
        extent = null;
      }}
      if (!extent || !usableLayerBounds(extent.bounds)) {{
        showModeKey('mode.layerExtentUnavailable', {{ layer: layer.name }});
        logMsg('log.layerExtentUnavailable', {{ layer: layer.name }});
        return false;
      }}
      const rawPadding = Number(options.padding ?? 36);
      const padding = Number.isFinite(rawPadding) ? Math.max(0, Math.min(120, rawPadding)) : 36;
      map.fitBounds(extent.bounds, {{
        padding: [padding, padding],
        maxZoom: normalizedLayerZoom(options.maxZoom ?? extent.maxZoom),
        animate: options.animate !== false,
        duration: 0.35,
      }});
      setActiveLayer(layerId, {{ reveal: false }});
      updateScaleLine();
      showModeKey('mode.layerZoomed', {{ layer: layer.name }});
      logMsg('log.layerZoomed', {{ layer: layer.name }});
      return true;
    }}

    function selectLayer(id, options = {{}}) {{
      if (id === PRIMARY_BASEMAP_LAYER_ID) {{
        setActiveLayer(PRIMARY_BASEMAP_LAYER_ID, {{ reveal: options.reveal !== false }});
        syncSessionState(options.reason || 'layer-selected');
        return true;
      }}
      if (id === AOI_LAYER_ID) {{
        if (!hasAoi()) return false;
        setActiveLayer(AOI_LAYER_ID, {{ reveal: options.reveal !== false }});
        syncSessionState(options.reason || 'layer-selected');
        return true;
      }}
      if (id === MEASUREMENTS_LAYER_ID) {{
        if (!hasMeasurements()) return false;
        setActiveLayer(MEASUREMENTS_LAYER_ID, {{ reveal: options.reveal !== false }});
        syncSessionState(options.reason || 'layer-selected');
        return true;
      }}
      if (!layerRegistry.has(id)) return false;
      setActiveLayer(id, {{ reveal: options.reveal !== false }});
      syncSessionState(options.reason || 'layer-selected');
      return true;
    }}
    async function applyLayerPreset(id, presetId) {{
      const record = layerRegistry.get(id);
      if (!record) return false;
      const preset = stylePresetForLayer(record.meta, presetId);
      const profile = layerStyleProfile(record.meta);
      if (isLocalVectorLayer(record.meta)) {{
        record.meta = {{
          ...record.meta,
          styleProfile: profile,
          stylePreset: preset.id,
          legend: preset.legend || record.meta.legend,
        }};
        const stateIndex = STATE.layers.findIndex(layer => layer.id === id);
        if (stateIndex >= 0) STATE.layers[stateIndex] = record.meta;
        if (typeof record.refresh === 'function') record.refresh();
        visualPreferences[profile] = preset.id;
        renderLayers();
        updateInspector();
        syncSessionState('layer-style');
        return true;
      }}
      showModeKey('mode.styleBuilding', {{ layer: record.meta.name }}, true);
      try {{
        const response = await fetch('/api/layer', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            project: STATE.project,
            datasetId: record.meta.dataset,
            catalogItem: {{ id: record.meta.dataset, label: record.meta.name, type: record.meta.type }},
            recipe: record.meta.recipe || null,
            aoi: record.meta.aoi || currentProcessingAoi(),
            bounds: record.meta.bounds || currentProcessingBounds(),
            startDate: record.meta.summary?.startDate || STATE.startDate,
            endDate: record.meta.summary?.endDate || STATE.endDate,
            cloudPct: record.meta.summary?.cloudPct ?? STATE.cloudPct,
            styleProfile: profile,
            visParams: sanitizeVisParams(preset.visParams),
            legend: preset.legend,
            stylePreset: preset.id,
          }}),
        }});
        const payload = await response.json().catch(() => ({{ ok: false, error: response.statusText || 'request failed' }}));
        if (!response.ok || !payload.ok || !payload.layer) {{
          throw new Error(payload.error || `HTTP ${{response.status}}`);
        }}
        const wasShown = map.hasLayer(record.tile);
        if (wasShown) map.removeLayer(record.tile);
        const nextMeta = {{
          ...record.meta,
          ...payload.layer,
          id: record.meta.id,
          shown: record.meta.shown,
          opacity: record.meta.opacity,
          styleProfile: profile,
          stylePreset: preset.id,
          visParams: sanitizeVisParams(preset.visParams),
          legend: preset.legend || payload.layer.legend || record.meta.legend,
        }};
        record.meta = nextMeta;
        const stateIndex = STATE.layers.findIndex(layer => layer.id === id);
        if (stateIndex >= 0) STATE.layers[stateIndex] = nextMeta;
        record.tile = L.tileLayer(nextMeta.tileUrl, {{ opacity: nextMeta.opacity, attribution: 'Google Earth Engine' }});
        if (wasShown || nextMeta.shown) record.tile.addTo(map);
        visualPreferences[profile] = preset.id;
        renderLayers();
        updateInspector();
        showModeKey('mode.styleApplied', {{ layer: nextMeta.name }});
        logMsg('log.layerStyled', {{ layer: nextMeta.name }});
        syncSessionState('layer-style');
        return true;
      }} catch (error) {{
        const message = error && error.message ? error.message : String(error);
        showModeKey('mode.styleFailed', {{ message: message.slice(0, 90) }}, true);
        logMsg('log.layerStyleFailed', {{ layer: record.meta.name }});
        renderLayers();
        return false;
      }}
    }}
    function renderLayers() {{
      const operationalModels = operationalLayerModels();
      const primaryModel = primaryBasemapLayerModel();
      const models = [...operationalModels, primaryModel];
      $('layer-count').textContent = t('pill.layersWithBasemap', {{ count: operationalModels.length }});
      const layerCardHtml = layer => {{
        const kind = layerKind(layer);
        const isAoi = layer.id === AOI_LAYER_ID;
        const isMeasurements = layer.id === MEASUREMENTS_LAYER_ID;
        const isPrimaryBasemap = layer.id === PRIMARY_BASEMAP_LAYER_ID;
        const isBasemapOverlay = isBasemapOverlayLayer(layer);
        const isBasemapLayer = isPrimaryBasemap || isBasemapOverlay;
        const canReorder = isReorderableLayer(layer.id);
        const dragAttrs = canReorder ? ' data-reorderable="true"' : '';
        const dragHandle = canReorder ? `<span class="layer-drag-handle" draggable="true" title="${{escapeHtml(t('tool.dragLayer'))}}" aria-label="${{escapeHtml(t('tool.dragLayer'))}}" role="img">{svg_icon("grip")}</span>` : '';
        const presets = isAoi || isBasemapLayer ? [] : stylePresetOptions(layer);
        let selectedPreset = layer.stylePreset || visualPreferences[layerStyleProfile(layer)] || 'default';
        const preset = isAoi || isBasemapLayer ? null : stylePresetForLayer(layer, selectedPreset);
        if (preset) selectedPreset = preset.id;
        const palette = isAoi ? [STATE.aoiStyle.color] : isMeasurements ? [DEFAULT_MEASUREMENTS_STYLE.color] : (preset?.visParams?.palette || layer.visParams?.palette || []);
        const styleControl = isBasemapLayer
          ? ''
          : isAoi
          ? `<div class="layer-style-row"><span>${{escapeHtml(t('label.color'))}}</span><input type="color" data-action="aoi-color" value="${{escapeHtml(STATE.aoiStyle.color)}}"></div>`
          : isMeasurements
            ? `<div class="layer-style-row"><span>${{escapeHtml(t('measurements.count'))}}</span><span>${{escapeHtml(t('measurements.summary', {{ count: layer.summary.count, total: layer.summary.totalLabel }}))}}</span></div>${{palettePreviewHtml(palette)}}`
            : `<div class="layer-style-row"><span>${{escapeHtml(t('label.palette'))}}</span><select data-action="style-preset">${{presets.map(item => `<option value="${{escapeHtml(item.id)}}" ${{item.id === selectedPreset ? 'selected' : ''}}>${{escapeHtml(item.label)}}</option>`).join('')}}</select></div>${{palettePreviewHtml(palette)}}`;
        const removeTitle = isAoi ? t('tool.clearAoi') : isMeasurements ? t('tool.clearMeasurements') : t('tool.removeLayer');
        const refreshTitle = t('tool.refreshLayer');
        const zoomButton = `<button class="layer-action icon-btn" data-action="zoom" title="${{escapeHtml(t('tool.zoomToLayer'))}}" aria-label="${{escapeHtml(t('tool.zoomToLayer'))}}" type="button">{svg_icon("zoom-layer")}</button>`;
        const styleButton = isMeasurements || isBasemapLayer ? '' : `<button class="layer-action icon-btn" data-action="style-focus" title="${{escapeHtml(t('tool.styleLayer'))}}" aria-label="${{escapeHtml(t('tool.styleLayer'))}}" type="button">{svg_icon("style")}</button>`;
        const sourceButton = isBasemapLayer ? `<button class="layer-action icon-btn" data-action="source" title="${{escapeHtml(t('tool.basemapSource'))}}" aria-label="${{escapeHtml(t('tool.basemapSource'))}}" type="button">{svg_icon("info")}</button>` : '';
        const refreshButton = isPrimaryBasemap ? '' : `<button class="layer-action icon-btn" data-action="refresh" title="${{escapeHtml(refreshTitle)}}" aria-label="${{escapeHtml(refreshTitle)}}" type="button">{svg_icon("refresh")}</button>`;
        const removeButton = isPrimaryBasemap ? '' : `<button class="layer-action icon-btn danger" data-action="remove" title="${{escapeHtml(removeTitle)}}" aria-label="${{escapeHtml(removeTitle)}}" type="button">{svg_icon("trash")}</button>`;
        const itemClass = isPrimaryBasemap ? ' primary-basemap' : isBasemapOverlay ? ' basemap-overlay' : '';
        return `
        <div class="layer-item${{itemClass}}${{layer.id === activeLayerId ? ' active' : ''}}" data-layer="${{escapeHtml(layer.id)}}"${{dragAttrs}}>
          <div class="layer-top">
            <input type="checkbox" data-action="toggle" ${{layer.shown ? 'checked' : ''}} aria-label="${{escapeHtml(layer.name)}}">
            <div class="layer-copy">
              <div class="layer-title-row">${{dragHandle}}<span class="type-dot ${{kind.className}}">${{kind.label}}</span><div class="layer-name">${{escapeHtml(layer.name)}}</div></div>
              <div class="layer-dataset">${{escapeHtml(layer.dataset)}}</div>
            </div>
            <div class="layer-actions">
              ${{zoomButton}}
              ${{styleButton}}
              ${{sourceButton}}
              ${{refreshButton}}
              ${{removeButton}}
            </div>
          </div>
          ${{styleControl}}
          <div class="opacity-row">
            <span>${{escapeHtml(t('label.opacity'))}}</span>
            <input type="range" min="0" max="1" step="0.01" value="${{layer.opacity}}" data-action="opacity">
            <span data-opacity-label>${{Math.round(layer.opacity * 100)}}%</span>
          </div>
        </div>
      `;
      }};
      const operationalHtml = operationalModels.length
        ? operationalModels.map(layerCardHtml).join('')
        : `<div class="empty-list">${{escapeHtml(t('layers.emptyOperational'))}}</div>`;
      $('layer-list').innerHTML = `
        <section class="layer-stack-group">
          <div class="layer-group-heading">${{escapeHtml(t('section.operationalLayers'))}}<span>${{escapeHtml(t('section.layerReorderHint'))}} · ${{escapeHtml(t('pill.layers', {{ count: operationalModels.length }}))}}</span></div>
          ${{operationalHtml}}
        </section>
        <section class="layer-stack-group">
          <div class="layer-group-heading">${{escapeHtml(t('section.primaryBasemap'))}}<span>${{escapeHtml(t('section.primaryBasemapHint'))}}</span></div>
          ${{layerCardHtml(primaryModel)}}
        </section>`;
      document.querySelectorAll('.layer-item').forEach(item => {{
        const id = item.dataset.layer;
        if (item.dataset.reorderable === 'true') {{
          const handle = item.querySelector('.layer-drag-handle');
          handle?.addEventListener('dragstart', event => {{
            draggedLayerId = id;
            item.classList.add('dragging');
            if (event.dataTransfer) {{
              event.dataTransfer.effectAllowed = 'move';
              event.dataTransfer.setData('text/plain', id);
            }}
          }});
          item.addEventListener('dragover', event => {{
            if (!draggedLayerId || draggedLayerId === id || !isReorderableLayer(id)) return;
            event.preventDefault();
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
            item.classList.add('drag-over');
          }});
          item.addEventListener('dragleave', () => item.classList.remove('drag-over'));
          item.addEventListener('drop', event => {{
            event.preventDefault();
            const sourceId = draggedLayerId || event.dataTransfer?.getData('text/plain');
            item.classList.remove('drag-over');
            if (sourceId) reorderLayer(sourceId, id);
            draggedLayerId = null;
          }});
          handle?.addEventListener('dragend', () => {{
            draggedLayerId = null;
            item.classList.remove('dragging', 'drag-over');
          }});
        }}
        item.addEventListener('click', event => {{
          if (event.target.closest('[data-action]')) return;
          setActiveLayer(id);
        }});
        item.querySelector('[data-action="toggle"]').addEventListener('change', event => {{
          const reason = id === PRIMARY_BASEMAP_LAYER_ID ? 'basemap-visibility' : id === AOI_LAYER_ID ? 'aoi-visibility' : id === MEASUREMENTS_LAYER_ID ? 'measurements-visibility' : 'layer-toggle';
          setLayerVisibility(id, event.target.checked, {{ reason }});
        }});
        item.querySelector('[data-action="zoom"]')?.addEventListener('click', async event => {{
          event.stopPropagation();
          const button = event.currentTarget;
          button.disabled = true;
          try {{
            await zoomToLayer(id);
          }} finally {{
            button.disabled = false;
          }}
        }});
        item.querySelector('[data-action="opacity"]').addEventListener('input', event => {{
          const value = Number(event.target.value);
          const reason = id === PRIMARY_BASEMAP_LAYER_ID ? 'basemap-opacity' : id === AOI_LAYER_ID ? 'aoi-style' : id === MEASUREMENTS_LAYER_ID ? 'measurements-opacity' : 'layer-opacity';
          if (!setLayerOpacity(id, value, {{ render: false, reason }})) return;
          item.querySelector('[data-opacity-label]').textContent = `${{Math.round(value * 100)}}%`;
        }});
        item.querySelector('[data-action="remove"]')?.addEventListener('click', event => {{
          event.stopPropagation();
          removeLayer(id);
        }});
        item.querySelector('[data-action="refresh"]')?.addEventListener('click', event => {{
          event.stopPropagation();
          refreshLayer(id);
        }});
        item.querySelector('[data-action="source"]')?.addEventListener('click', event => {{
          event.stopPropagation();
          const layer = models.find(model => model.id === id);
          setActiveLayer(id, {{ reveal: false }});
          setBasemapSourceOpen(true, layer?.sourceId || currentBasemap);
        }});
        item.querySelector('[data-action="style-focus"]')?.addEventListener('click', event => {{
          event.stopPropagation();
          setActiveLayer(id);
          item.querySelector('[data-action="aoi-color"], [data-action="style-preset"]')?.focus();
        }});
        const colorInput = item.querySelector('[data-action="aoi-color"]');
        if (colorInput) {{
          colorInput.addEventListener('input', event => {{
            const color = event.target.value;
            if (!isHexColor(color)) return;
            STATE.aoiStyle = normalizeAoiStyle({{ ...STATE.aoiStyle, color, fillColor: color }});
            renderAoiLayer();
            renderLayers();
            setActiveLayer(AOI_LAYER_ID, {{ reveal: false }});
            syncSessionState('aoi-style');
          }});
        }}
        const styleSelect = item.querySelector('[data-action="style-preset"]');
        if (styleSelect) {{
          styleSelect.addEventListener('change', event => {{
            applyLayerPreset(id, event.target.value);
          }});
        }}
      }});
      syncLayerOrderToMap();
    }}

    function setActiveLayer(id, options = {{}}) {{
      activeLayerId = id || null;
      document.querySelectorAll('.layer-item').forEach(item => {{
        item.classList.toggle('active', item.dataset.layer === id);
      }});
      updateInspector();
      if (activeLayerId && options.reveal !== false) revealActiveBadge();
    }}

    function updateInspector() {{
      if (activeLayerId === PRIMARY_BASEMAP_LAYER_ID) {{
        const layer = primaryBasemapLayerModel();
        $('active-name').textContent = layer.name;
        $('active-dataset').textContent = layerBadgeDataset(layer.dataset);
        setActiveBadgeLabel(layerBadgeTitle(layer.name, layer.dataset));
        $('detail-name').textContent = layer.name;
        $('detail-dataset').textContent = layer.dataset;
        $('detail-type').textContent = t('basemap.primaryRole');
        $('detail-recipe').textContent = '-';
        $('detail-opacity').textContent = `${{Math.round(layer.opacity * 100)}}%`;
        $('legend').innerHTML = `<div class="empty-list">${{escapeHtml(t('section.primaryBasemapHint'))}}</div>`;
        return;
      }}
      if (activeLayerId === AOI_LAYER_ID && hasAoi()) {{
        const layer = aoiLayerModel();
        $('active-name').textContent = layer.name;
        $('active-dataset').textContent = layerBadgeDataset(layer.dataset);
        const badgeLabel = layerBadgeTitle(layer.name, layer.dataset);
        setActiveBadgeLabel(badgeLabel);
        $('detail-name').textContent = layer.name;
        $('detail-dataset').textContent = layer.dataset;
        $('detail-type').textContent = 'AOI';
        $('detail-recipe').textContent = '-';
        $('detail-opacity').textContent = `${{Math.round(layer.opacity * 100)}}%`;
        $('legend').innerHTML = `<div class="legend-row"><span class="swatch" style="background:${{escapeHtml(STATE.aoiStyle.color)}}"></span><span>AOI</span></div>`;
        return;
      }}
      if (activeLayerId === MEASUREMENTS_LAYER_ID && hasMeasurements()) {{
        const layer = measurementsLayerModel();
        const summary = layer.summary;
        $('active-name').textContent = layer.name;
        $('active-dataset').textContent = layerBadgeDataset(layer.dataset);
        const badgeLabel = layerBadgeTitle(layer.name, layer.dataset);
        setActiveBadgeLabel(badgeLabel);
        $('detail-name').textContent = layer.name;
        $('detail-dataset').textContent = t('measurements.summary', {{ count: summary.count, total: summary.totalLabel }});
        $('detail-type').textContent = 'Measurements';
        $('detail-recipe').textContent = '-';
        $('detail-opacity').textContent = `${{Math.round(layer.opacity * 100)}}%`;
        $('legend').innerHTML = `<div class="legend-row"><span class="swatch" style="background:${{escapeHtml(DEFAULT_MEASUREMENTS_STYLE.color)}}"></span><span>${{escapeHtml(t('measurements.legend'))}}</span></div>`;
        return;
      }}
      const record = layerRegistry.get(activeLayerId);
      if (!record) {{
        const noLayer = t('layer.none');
        const basemapLabel = fullBasemapBadge();
        $('active-name').textContent = 'EasyGEE';
        $('active-dataset').textContent = basemapLabel;
        const badgeLabel = `${{t('badge.noLayer')}} - ${{basemapLabel}}`;
        setActiveBadgeLabel(badgeLabel);
        $('detail-name').textContent = noLayer;
        $('detail-dataset').textContent = displayBasemapSource();
        $('detail-type').textContent = '-';
        $('detail-recipe').textContent = '-';
        $('detail-opacity').textContent = '-';
        $('legend').innerHTML = `<div class="empty-list">${{escapeHtml(noLayer)}}</div>`;
        return;
      }}
      const layer = record.meta;
      $('active-name').textContent = layer.name;
      $('active-dataset').textContent = layerBadgeDataset(layer.dataset);
      const badgeLabel = layerBadgeTitle(layer.name, layer.dataset);
      setActiveBadgeLabel(badgeLabel);
      $('detail-name').textContent = layer.name;
      $('detail-dataset').textContent = layer.dataset;
      $('detail-type').textContent = isBasemapOverlayLayer(layer) ? t('basemap.overlayRole') : layer.type;
      $('detail-recipe').textContent = recipeSummary(layer.recipe);
      $('detail-opacity').textContent = `${{Math.round(layer.opacity * 100)}}%`;
      $('legend').innerHTML = (layer.legend || []).map(([color, label]) => `
        <div class="legend-row"><span class="swatch" style="background:${{escapeHtml(color)}}"></span><span>${{escapeHtml(label)}}</span></div>
      `).join('') || (isBasemapOverlayLayer(layer) ? `<div class="empty-list">${{escapeHtml(layer.dataset)}}</div>` : '');
    }}

    function boundsFromCorners(a, b) {{
      const south = Math.min(a.lat, b.lat);
      const north = Math.max(a.lat, b.lat);
      const west = Math.min(a.lng, b.lng);
      const east = Math.max(a.lng, b.lng);
      return [[south, west], [north, east]];
    }}
    function boundsTooSmall(bounds) {{
      return Math.abs(bounds[1][0] - bounds[0][0]) < 0.000001 || Math.abs(bounds[1][1] - bounds[0][1]) < 0.000001;
    }}
    function boundsLabel(bounds) {{
      return `${{fmt(bounds[0][0], 4)}}, ${{fmt(bounds[0][1], 4)}} - ${{fmt(bounds[1][0], 4)}}, ${{fmt(bounds[1][1], 4)}}`;
    }}
    function closeFloatingPanels() {{
      quotaFocus = false;
      document.querySelector('.data-panel').classList.remove('open');
      document.querySelector('.upload-panel').classList.remove('open');
      document.querySelector('.layers-panel').classList.remove('open');
      document.querySelector('.right').classList.remove('open');
      document.querySelector('.bottom').classList.remove('open');
      document.querySelector('.basemap-panel').classList.remove('open');
    }}
    function clearAoiPreview() {{
      drawAoiLayer.clearLayers();
      drawAoiPreview = null;
      drawPolygonPoints = [];
    }}
    function stopDrawAoiMode(announce = true) {{
      const wasActive = drawAoiMode || drawAoiStart || drawPolygonMode || drawPolygonPoints.length;
      drawAoiMode = false;
      drawPolygonMode = false;
      drawAoiStart = null;
      if (polygonDoubleClickZoomWasEnabled) map.doubleClickZoom.enable();
      polygonDoubleClickZoomWasEnabled = false;
      clearAoiPreview();
      map.getContainer().classList.remove('draw-aoi', 'draw-polygon');
      syncToolState();
      if (announce && wasActive) {{
        showModeKey('mode.aoiOff', {{}}, false);
        logMsg('log.aoiOff');
      }}
    }}
    function startRectangleAoiMode() {{
      if (drawAoiMode && !drawPolygonMode) {{
        stopDrawAoiMode(true);
        return;
      }}
      measureMode = false;
      measurePoints = [];
      measureDraftLayer.clearLayers();
      closeFloatingPanels();
      stopDrawAoiMode(false);
      drawAoiMode = true;
      drawAoiStart = null;
      map.getContainer().classList.add('draw-aoi');
      syncToolState();
      showModeKey('mode.aoiStart', {{}}, true);
      logMsg('log.aoiOn');
    }}
    function startPolygonAoiMode() {{
      if (drawPolygonMode) {{
        stopDrawAoiMode(true);
        return;
      }}
      measureMode = false;
      measurePoints = [];
      measureDraftLayer.clearLayers();
      closeFloatingPanels();
      stopDrawAoiMode(false);
      drawPolygonMode = true;
      drawAoiMode = false;
      drawPolygonPoints = [];
      polygonDoubleClickZoomWasEnabled = map.doubleClickZoom.enabled();
      if (polygonDoubleClickZoomWasEnabled) map.doubleClickZoom.disable();
      map.getContainer().classList.add('draw-polygon');
      syncToolState();
      showModeKey('mode.polygonStart', {{}}, true);
      logMsg('log.aoiOn');
    }}
    function toggleDrawAoiMode(polygon = false) {{
      if (polygon) startPolygonAoiMode();
      else startRectangleAoiMode();
    }}
    function updateAoi(aoi, options = {{ persist: true }}) {{
      const hadAoi = hasAoi();
      const normalized = normalizeAoi(aoi);
      if (!normalized) return false;
      STATE.aoi = normalized;
      STATE.bounds = normalized.bounds;
      STATE.aoiShown = true;
      if (!hadAoi) placeOperationalLayer(AOI_LAYER_ID, 'front');
      renderAoiLayer();
      renderLayers();
      setActiveLayer(AOI_LAYER_ID, {{ reveal: false }});
      if (options.persist !== false) persistAoi();
      syncSessionState('aoi');
      return true;
    }}
    function updateAoiBounds(bounds) {{
      return updateAoi(aoiFromBounds(bounds));
    }}
    function handleDrawAoiMove(event) {{
      if (!drawAoiMode || !drawAoiStart) return;
      const bounds = boundsFromCorners(drawAoiStart, event.latlng);
      if (!drawAoiPreview) {{
        drawAoiPreview = L.rectangle(bounds, {{
          color: '#16734d',
          weight: 2,
          dashArray: '6 5',
          fill: true,
          fillColor: '#16734d',
          fillOpacity: 0.12,
          interactive: false,
        }}).addTo(drawAoiLayer);
      }} else {{
        drawAoiPreview.setBounds(bounds);
      }}
    }}
    function renderPolygonPreview(nextPoint = null) {{
      if (!drawPolygonMode) return;
      drawAoiLayer.clearLayers();
      drawPolygonPoints.forEach(point => {{
        L.circleMarker(point, {{
          radius: 4,
          color: '#16734d',
          fillColor: '#16734d',
          fillOpacity: 1,
          weight: 2,
          interactive: false,
        }}).addTo(drawAoiLayer);
      }});
      const previewPoints = nextPoint ? [...drawPolygonPoints, nextPoint] : drawPolygonPoints;
      if (previewPoints.length >= 2) {{
        L.polyline(previewPoints, {{ color: '#16734d', weight: 2, dashArray: '6 5', interactive: false }}).addTo(drawAoiLayer);
      }}
      if (previewPoints.length >= 3) {{
        L.polygon(previewPoints, {{
          color: '#16734d',
          weight: 2,
          dashArray: '6 5',
          fill: true,
          fillColor: '#16734d',
          fillOpacity: 0.10,
          interactive: false,
        }}).addTo(drawAoiLayer);
      }}
    }}
    function handleDrawPolygonMove(event) {{
      if (!drawPolygonMode) return;
      renderPolygonPreview(event.latlng);
    }}
    function handleDrawPolygonClick(event) {{
      if (!drawPolygonMode) return false;
      drawPolygonPoints.push(event.latlng);
      renderPolygonPreview();
      showModeKey('mode.polygonVertex', {{ count: drawPolygonPoints.length }}, true);
      return true;
    }}
    function finishPolygonAoi() {{
      if (!drawPolygonMode) return false;
      if (drawPolygonPoints.length < 3) {{
        showModeKey('mode.polygonTooSmall', {{}}, true);
        return true;
      }}
      const coordinates = drawPolygonPoints.map(point => [point.lat, point.lng]);
      updateAoi({{ type: 'polygon', coordinates, coordinateOrder: 'latlng' }});
      const bounds = STATE.aoi.bounds;
      stopDrawAoiMode(false);
      showModeKey('mode.aoiDone', {{}}, false);
      logMsg('log.aoiDrawn', {{ bounds: boundsLabel(bounds) }});
      return true;
    }}
    function handleDrawAoiClick(event) {{
      if (!drawAoiMode) return false;
      if (!drawAoiStart) {{
        drawAoiStart = event.latlng;
        L.circleMarker(drawAoiStart, {{
          radius: 4,
          color: '#16734d',
          fillColor: '#16734d',
          fillOpacity: 1,
          weight: 2,
          interactive: false,
        }}).addTo(drawAoiLayer);
        showModeKey('mode.aoiCorner', {{}}, true);
        return true;
      }}
      const bounds = boundsFromCorners(drawAoiStart, event.latlng);
      if (boundsTooSmall(bounds)) {{
        showModeKey('mode.aoiTooSmall', {{}}, true);
        return true;
      }}
      updateAoiBounds(bounds);
      stopDrawAoiMode(false);
      showModeKey('mode.aoiDone', {{}}, false);
      logMsg('log.aoiDrawn', {{ bounds: boundsLabel(bounds) }});
      return true;
    }}

    function clamp(value, min, max) {{
      return Math.max(min, Math.min(max, value));
    }}
    function installPanelResizers() {{
      const configs = [
        {{ selector: '.data-panel', anchor: 'left', minWidth: 360, minHeight: 220, handles: ['e', 's', 'se'] }},
        {{ selector: '.layers-panel', anchor: 'left', minWidth: 260, minHeight: 220, handles: ['e', 's', 'se'] }},
        {{ selector: '.right', anchor: 'right', minWidth: 260, minHeight: 220, handles: ['w', 's', 'sw'] }},
        {{ selector: '.bottom', anchor: 'right', minWidth: 300, minHeight: 260, handles: ['w', 's', 'sw'] }},
        {{ selector: '.basemap-panel', anchor: 'left', minWidth: 220, minHeight: 132, handles: ['e', 's', 'se'] }},
        {{ selector: '.upload-panel', anchor: 'left', minWidth: 320, minHeight: 230, handles: ['e', 's', 'se'] }},
      ];
      configs.forEach(config => {{
        const panel = document.querySelector(config.selector);
        if (!panel || panel.dataset.resizableReady) return;
        panel.dataset.resizableReady = 'true';
        panel.classList.add('resizable-panel');
        config.handles.forEach(edge => {{
          const handle = document.createElement('span');
          handle.className = `panel-resize-handle ${{edge.length === 1 ? `edge-${{edge}}` : `corner-${{edge}}`}}`;
          handle.setAttribute('aria-hidden', 'true');
          handle.addEventListener('pointerdown', event => startPanelResize(event, panel, config, edge));
          panel.appendChild(handle);
        }});
      }});
    }}
    function startPanelResize(event, panel, config, edge) {{
      event.preventDefault();
      event.stopPropagation();
      const rect = panel.getBoundingClientRect();
      const startX = event.clientX;
      const startY = event.clientY;
      const startWidth = rect.width;
      const startHeight = rect.height;
      const rightGap = Math.max(0, window.innerWidth - rect.right);
      const leftGap = Math.max(0, rect.left);
      const maxWidth = config.anchor === 'right'
        ? Math.max(config.minWidth, rect.right - 8)
        : Math.max(config.minWidth, window.innerWidth - rect.left - 8);
      const maxHeight = Math.max(config.minHeight, window.innerHeight - rect.top - 8);
      panel.setPointerCapture?.(event.pointerId);
      function move(moveEvent) {{
        const dx = moveEvent.clientX - startX;
        const dy = moveEvent.clientY - startY;
        if (edge.includes('e') || edge.includes('w')) {{
          const rawWidth = edge.includes('w') ? startWidth - dx : startWidth + dx;
          panel.style.width = `${{Math.round(clamp(rawWidth, config.minWidth, maxWidth))}}px`;
          panel.style.maxWidth = 'none';
          if (config.anchor === 'right') {{
            panel.style.right = `${{rightGap}}px`;
            panel.style.left = 'auto';
          }} else {{
            panel.style.left = `${{leftGap}}px`;
          }}
        }}
        if (edge.includes('s')) {{
          const rawHeight = startHeight + dy;
          panel.style.height = `${{Math.round(clamp(rawHeight, config.minHeight, maxHeight))}}px`;
          panel.style.maxHeight = 'none';
          panel.style.bottom = 'auto';
        }}
      }}
      function up(upEvent) {{
        panel.releasePointerCapture?.(upEvent.pointerId);
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
      }}
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up, {{ once: true }});
    }}

    function renderMeasurements() {{
      measureLayer.clearLayers();
      if (STATE.measurementsShown === false) {{
        syncLayerOrderToMap();
        return;
      }}
      const opacity = normalizeMeasurementsOpacity(STATE.measurementsOpacity);
      (STATE.measurements || []).forEach(item => {{
        const start = L.latLng(item.start[0], item.start[1]);
        const end = L.latLng(item.end[0], item.end[1]);
        L.polyline([start, end], {{ color: DEFAULT_MEASUREMENTS_STYLE.color, weight: DEFAULT_MEASUREMENTS_STYLE.weight, opacity, dashArray: '6 5' }})
          .bindTooltip(item.lengthLabel || formatDistance(item.lengthMeters), {{
            permanent: true,
            direction: 'center',
            className: 'measure-label',
            opacity,
          }})
          .addTo(measureLayer);
        [start, end].forEach(point => {{
          L.circleMarker(point, {{
            radius: 3,
            color: DEFAULT_MEASUREMENTS_STYLE.color,
            fillColor: DEFAULT_MEASUREMENTS_STYLE.color,
            fillOpacity: opacity,
            opacity,
            weight: 1.5,
            interactive: false,
          }}).addTo(measureLayer);
        }});
      }});
      syncLayerOrderToMap();
    }}
    function renderMeasureDraft() {{
      measureDraftLayer.clearLayers();
      measurePoints.forEach(point => L.circleMarker(point, {{
        radius: 4,
        color: '#16734d',
        fillColor: '#16734d',
        fillOpacity: 1,
        weight: 2,
      }}).addTo(measureDraftLayer));
    }}
    function saveMeasurement(start, end) {{
      const hadMeasurements = hasMeasurements();
      const meters = distanceMeters(start, end);
      const row = {{
        id: `measure-${{Date.now().toString(36)}}-${{Math.random().toString(36).slice(2, 7)}}`,
        start: [start.lat, start.lng],
        end: [end.lat, end.lng],
        lengthMeters: meters,
        lengthLabel: formatDistance(meters),
        createdAt: new Date().toISOString(),
      }};
      STATE.measurements.push(row);
      STATE.measurementsShown = true;
      measurementLayerNotice = true;
      if (!hadMeasurements) placeOperationalLayer(MEASUREMENTS_LAYER_ID, 'front');
      persistMeasurements();
      renderMeasurements();
      const summary = measurementSummary();
      renderLayers();
      setActiveLayer(MEASUREMENTS_LAYER_ID, {{ reveal: false }});
      revealActiveBadge(4200);
      syncToolState();
      showModeKey('mode.measureSaved', {{ distance: row.lengthLabel, count: summary.count, mean: summary.meanLabel }}, true);
      logMsg('log.measureSummary', {{ count: summary.count, mean: summary.meanLabel }});
      syncSessionState('measurement');
      return row;
    }}
    function undoLastMeasurement() {{
      if (measurePoints.length) {{
        measurePoints.pop();
        renderMeasureDraft();
        showModeKey('mode.measureUndoDraft', {{}}, true);
        syncToolState();
        return true;
      }}
      if (!Array.isArray(STATE.measurements) || !STATE.measurements.length) {{
        showModeKey('mode.measureUndoEmpty', {{}}, true);
        syncToolState();
        return false;
      }}
      const row = STATE.measurements.pop();
      persistMeasurements();
      renderMeasurements();
      measurementLayerNotice = STATE.measurements.length > 0;
      renderLayers();
      if (STATE.measurements.length) {{
        setActiveLayer(MEASUREMENTS_LAYER_ID, {{ reveal: false }});
      }} else if (activeLayerId === MEASUREMENTS_LAYER_ID) {{
        setActiveLayer(aoiLayerModel()?.id || STATE.layers.find(item => item.shown)?.id || STATE.layers[0]?.id || PRIMARY_BASEMAP_LAYER_ID, {{ reveal: false }});
      }}
      const distance = row?.lengthLabel || formatDistance(row?.lengthMeters || 0);
      showModeKey('mode.measureUndoSaved', {{ distance }}, true);
      logMsg('log.measureUndo', {{ distance }});
      syncToolState();
      syncSessionState('measurement-undo');
      return true;
    }}
    function clearMeasurements() {{
      const count = Array.isArray(STATE.measurements) ? STATE.measurements.length : 0;
      STATE.measurements = [];
      removeOperationalLayerOrder(MEASUREMENTS_LAYER_ID);
      persistMeasurements();
      measureLayer.clearLayers();
      measureDraftLayer.clearLayers();
      measurePoints = [];
      measureMode = false;
      measurementLayerNotice = false;
      syncToolState();
      renderLayers();
      if (activeLayerId === MEASUREMENTS_LAYER_ID) setActiveLayer(aoiLayerModel()?.id || STATE.layers.find(item => item.shown)?.id || STATE.layers[0]?.id || PRIMARY_BASEMAP_LAYER_ID, {{ reveal: false }});
      showModeKey('mode.measureCleared', {{}}, false);
      logMsg('log.measureCleared', {{ count }});
      syncSessionState('measurements-cleared');
      return measurementSummary();
    }}
    async function extractNdviForCurrentAoi(options = {{}}) {{
      if (!hasAoi()) {{
        showModeKey('mode.ndviNoAoi', {{}}, true);
        return {{ ok: false, error: 'AOI is required' }};
      }}
      showModeKey('mode.ndviBuilding', {{}}, true);
      logMsg('log.ndviStarted');
      try {{
        const response = await fetch('/api/analysis/ndvi', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            project: STATE.project,
            aoi: cloneAoi(STATE.aoi),
            bounds: STATE.aoi.bounds,
            startDate: options.startDate || STATE.startDate,
            endDate: options.endDate || STATE.endDate,
            cloudPct: options.cloudPct ?? STATE.cloudPct,
            scale: options.scale || 10,
          }}),
        }});
        const payload = await response.json().catch(() => ({{ ok: false, error: response.statusText || 'request failed' }}));
        if (!response.ok || !payload.ok || !payload.layer) {{
          throw new Error(payload.error || `HTTP ${{response.status}}`);
        }}
        addGeneratedLayer(payload.layer);
        const mean = Number(payload.summary?.mean);
        const count = Number(payload.summary?.count || 0);
        const meanText = Number.isFinite(mean) ? mean.toFixed(3) : '-';
        showModeKey('mode.ndviDone', {{ mean: meanText, count }});
        logMsg('log.ndviDone', {{ mean: meanText }});
        return payload;
      }} catch (error) {{
        const message = error && error.message ? error.message : String(error);
        showModeKey('mode.ndviFailed', {{ message: message.slice(0, 90) }}, true);
        logMsg('log.ndviFailed');
        return {{ ok: false, error: message }};
      }} finally {{
        syncToolState();
      }}
    }}
    async function exportNdviToDrive(options = {{}}) {{
      if (!hasAoi()) {{
        showModeKey('mode.ndviNoAoi', {{}}, true);
        return {{ ok: false, error: 'AOI is required' }};
      }}
      showModeKey('mode.driveExportBuilding', {{}}, true);
      logMsg('log.driveExportStarted');
      try {{
        const response = await fetch('/api/export/ndvi-drive', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            project: STATE.project,
            aoi: cloneAoi(STATE.aoi),
            bounds: STATE.aoi.bounds,
            startDate: options.startDate || STATE.startDate,
            endDate: options.endDate || STATE.endDate,
            cloudPct: options.cloudPct ?? STATE.cloudPct,
            scale: options.scale || 10,
            folder: options.folder || 'EasyGEE',
            fileNamePrefix: options.fileNamePrefix,
            description: options.description,
            fileFormat: options.fileFormat || 'GeoTIFF',
            cloudOptimized: options.cloudOptimized !== false,
            maxPixels: options.maxPixels || 1000000000,
            start: options.start !== false,
          }}),
        }});
        const payload = await response.json().catch(() => ({{ ok: false, error: response.statusText || 'request failed' }}));
        if (!response.ok || !payload.ok || !(payload.task || payload.export)) {{
          throw new Error(payload.error || `HTTP ${{response.status}}`);
        }}
        const task = payload.task || payload.export;
        addTask(task, {{ logKey: 'log.driveExportDone', reason: 'drive-export' }});
        showModeKey('mode.driveExportDone', {{ task: task.fileNamePrefix || task.taskId || task.title || 'Drive' }});
        return payload;
      }} catch (error) {{
        const message = error && error.message ? error.message : String(error);
        showModeKey('mode.driveExportFailed', {{ message: message.slice(0, 90) }}, true);
        logMsg('log.driveExportFailed');
        return {{ ok: false, error: message }};
      }} finally {{
        syncToolState();
      }}
    }}

    function currentPerformanceEngine() {{
      const meta = currentBasemapMeta();
      const type = String(meta?.type || 'xyz').toLowerCase();
      const diagnostics = publicBasemapPerformance(meta);
      if (meta?.custom && type === 'cog') return {{
        id: 'maplibre-cog',
        renderer: `MapLibre {MAPLIBRE_VERSION}`,
        protocol: `COG {COG_PROTOCOL_VERSION}`,
        access: 'HTTP Range',
        status: cogEngineStatus,
        lazy: true,
        crs: meta.crs || 'EPSG:3857',
        ...(diagnostics ? {{ diagnostics }} : {{}}),
      }};
      if (meta?.custom && type === 'pmtiles') return {{
        id: 'leaflet-pmtiles',
        renderer: 'Leaflet',
        protocol: `PMTiles {PMTILES_VERSION}`,
        access: 'HTTP Range',
        status: window.pmtiles?.PMTiles ? 'ready' : 'unavailable',
        lazy: false,
        ...(diagnostics ? {{ diagnostics }} : {{}}),
      }};
      return {{
        id: 'leaflet-tiles',
        renderer: 'Leaflet',
        protocol: type.toUpperCase(),
        access: 'XYZ tiles',
        status: 'ready',
        lazy: false,
        ...(diagnostics ? {{ diagnostics }} : {{}}),
      }};
    }}
    function buildProjectState() {{
      const explicitAoi = hasAoi() ? cloneAoi(STATE.aoi) : null;
      const processingAoi = currentProcessingAoi();
      const processingBounds = processingAoi ? processingAoi.bounds : null;
      return {{
        title: STATE.title,
        project: STATE.project,
        projectSource: STATE.projectSource || 'unknown',
        agentProtocolVersion: AGENT_PROTOCOL_VERSION,
        startDate: STATE.startDate,
        endDate: STATE.endDate,
        cloudPct: STATE.cloudPct,
        center: [map.getCenter().lat, map.getCenter().lng],
        zoom: map.getZoom(),
        basemap: currentBasemap,
        basemapShown: primaryBasemapShown,
        basemapOpacity: primaryBasemapOpacity,
        defaultBasemap: defaultBasemapId,
        customBasemaps: customBasemaps.map(serializableCustomBasemap),
        performanceEngine: currentPerformanceEngine(),
        activeLayerId,
        bounds: processingBounds,
        aoiBounds: explicitAoi ? explicitAoi.bounds : null,
        aoi: explicitAoi,
        hasExplicitAoi: Boolean(explicitAoi),
        processingAoi,
        processingBounds,
        aoiShown: STATE.aoiShown !== false,
        aoiStyle: normalizeAoiStyle(STATE.aoiStyle),
        measurements: STATE.measurements.map(item => ({{ ...item }})),
        measurementsShown: STATE.measurementsShown !== false,
        measurementsOpacity: normalizeMeasurementsOpacity(STATE.measurementsOpacity),
        measurementSummary: measurementSummary(),
        language: currentLang,
        selectedDataset: selectedDatasetContext(),
        favoriteDatasets: [...favoriteDatasetIds].sort(),
        visualPreferences: {{ ...visualPreferences }},
        uploadCapabilities: {{ ...UPLOAD_CAPABILITIES }},
        uploads: (STATE.uploads || []).map(item => normalizeUploadRecord(item)).filter(Boolean),
        quota: STATE.quota,
        tasks: STATE.tasks.map(item => ({{ ...item }})),
        layerOrder: [...normalizedOperationalLayerOrder(operationalLayerOrder)],
        layers: STATE.layers.map(layer => ({{
          id: layer.id,
          name: layer.name,
          dataset: layer.dataset,
          type: layer.type,
          ...(layer.role ? {{ role: layer.role }} : {{}}),
          ...(layer.sourceId ? {{ sourceId: layer.sourceId }} : {{}}),
          shown: layerRegistry.has(layer.id) ? map.hasLayer(layerRegistry.get(layer.id).tile) : Boolean(layer.shown),
          opacity: layer.opacity,
          styleProfile: layer.styleProfile || layerStyleProfile(layer),
          stylePreset: layer.stylePreset || 'default',
          ...(layer.visParams ? {{ visParams: layer.visParams }} : {{}}),
          ...(layer.legend ? {{ legend: layer.legend }} : {{}}),
          ...(layer.recipe ? {{ recipe: layer.recipe }} : {{}}),
          ...(layer.summary ? {{ summary: layer.summary }} : {{}}),
          ...(layer.aoi ? {{ aoi: layer.aoi }} : {{}}),
        }}))
      }};
    }}

    async function syncSessionState(reason = 'update') {{
      if (sessionSyncBusy) return false;
      let state;
      try {{
        state = buildProjectState();
      }} catch {{
        return false;
      }}
      const text = JSON.stringify(state);
      if (text === lastSessionStateText) return true;
      lastSessionStateText = text;
      state.sessionReason = reason;
      state.sessionUpdatedAt = new Date().toISOString();
      sessionSyncBusy = true;
      try {{
        const response = await fetch('/api/session/state', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ state }}),
        }});
        return response.ok;
      }} catch {{
        return false;
      }} finally {{
        sessionSyncBusy = false;
      }}
    }}
    async function executeSessionAction(action) {{
      const type = String(action?.type || action?.action || '').toLowerCase();
      if (type === 'setbasemap' || type === 'set-basemap') {{
        return setBasemap(String(action.basemapId || action.id || action.basemap || ''));
      }}
      if (type === 'addbasemapoverlay' || type === 'add-basemap-overlay') {{
        return addBasemapOverlay(String(action.basemapId || action.sourceId || action.id || action.basemap || ''));
      }}
      if (type === 'setdefaultbasemap' || type === 'set-default-basemap') {{
        return setDefaultBasemap(String(action.basemapId || action.id || action.basemap || ''));
      }}
      if (type === 'addcustombasemap' || type === 'add-custom-basemap' || type === 'updatecustombasemap' || type === 'update-custom-basemap') {{
        const raw = action.basemap && typeof action.basemap === 'object' ? action.basemap : action;
        const requestedId = String(raw.id || action.basemapId || '').trim();
        const editing = type.startsWith('update');
        let meta = normalizeCustomBasemap({{ ...raw, id: requestedId || createCustomBasemapId(raw.name) }}, customBasemaps.length);
        if (!meta || !validHttpTemplate(meta.url)) return false;
        const index = customBasemaps.findIndex(item => item.id === meta.id);
        if (editing && index < 0) return false;
        const previous = index >= 0 ? customBasemaps[index] : null;
        const willActivate = action.activate !== false || currentBasemap === meta.id;
        if (meta.type === 'pmtiles') {{
          const inspection = await inspectPmtilesArchive(meta, {{ refresh: true, requireVisibleTile: willActivate }});
          if (!inspection.ok) return false;
          meta = normalizeCustomBasemap({{
            ...meta,
            minZoom: inspection.header?.minZoom,
            maxZoom: inspection.header?.maxZoom,
            maxNativeZoom: inspection.header?.maxZoom,
          }}, customBasemaps.length);
          if (!meta) return false;
        }}
        if (meta.type === 'cog') {{
          const inspection = await inspectCogSource(meta, {{ refresh: true, requireVisibleTile: willActivate, fitBounds: willActivate }});
          if (!inspection.ok) return false;
          meta = inspection.meta;
          if (!meta) return false;
        }}
        if (previous?.type === 'pmtiles' && (meta.type !== 'pmtiles' || previous.url !== meta.url)) {{
          discardPmtilesArchive(previous.url);
        }}
        if (previous?.type === 'cog' && (meta.type !== 'cog' || previous.url !== meta.url)) discardCogSource(previous.url);
        if (index >= 0) customBasemaps.splice(index, 1, meta);
        else customBasemaps.push(meta);
        customBasemaps = normalizeCustomBasemaps(customBasemaps);
        rebuildBasemapRegistry(action.activate === false ? currentBasemap : meta.id);
        syncSessionState(editing ? 'custom-basemap-updated' : 'custom-basemap-added');
        return true;
      }}
      if (type === 'removecustombasemap' || type === 'remove-custom-basemap') {{
        return removeCustomBasemap(String(action.basemapId || action.id || ''), {{ confirm: false }});
      }}
      if (type === 'addlayer' || type === 'add-layer') {{
        if (action.layer) {{
          addGeneratedLayer(action.layer);
          showModeKey('mode.datasetAdded', {{ count: 1 }});
          return true;
        }}
        return false;
      }}
      if (type === 'selectdataset' || type === 'select-dataset') {{
        const datasetId = String(action.datasetId || action.id || '');
        if (datasetId && datasetById(datasetId)) {{
          setActiveDataset(datasetId);
          return true;
        }}
        return false;
      }}
      if (type === 'setaoi' || type === 'set-aoi') {{
        if (action.aoi && updateAoi(action.aoi)) {{
          resetHomeView();
          return true;
        }}
        return false;
      }}
      if (type === 'clearaoi' || type === 'clear-aoi') {{
        clearAoi();
        return true;
      }}
      if (type === 'removelayer' || type === 'remove-layer') {{
        if (action.layerId || action.id) return removeLayer(String(action.layerId || action.id));
        return false;
      }}
      if (type === 'removeupload' || type === 'remove-upload') {{
        if (action.uploadId || action.id) return removeUpload(String(action.uploadId || action.id));
        return false;
      }}
      if (type === 'selectlayer' || type === 'select-layer') {{
        const layerId = String(action.layerId || action.id || activeLayerId || '');
        if (!layerId) return false;
        return selectLayer(layerId, {{ reveal: action.reveal !== false }});
      }}
      if (type === 'zoomtolayer' || type === 'zoom-to-layer' || type === 'zoomlayer' || type === 'zoom-layer') {{
        const layerId = String(action.layerId || action.id || activeLayerId || '');
        if (!layerId) return false;
        return zoomToLayer(layerId, action.options || action);
      }}
      if (type === 'refreshlayer' || type === 'refresh-layer' || type === 'reloadlayer' || type === 'reload-layer') {{
        const layerId = String(action.layerId || action.id || activeLayerId || '');
        if (!layerId) return false;
        return refreshLayer(layerId, {{ reason: 'layer-refresh-action' }});
      }}
      if (type === 'showlayer' || type === 'show-layer' || type === 'hidelayer' || type === 'hide-layer' || type === 'setlayervisibility' || type === 'set-layer-visibility') {{
        const layerId = String(action.layerId || action.id || activeLayerId || '');
        if (!layerId) return false;
        const shown = type === 'showlayer' || type === 'show-layer'
          ? true
          : type === 'hidelayer' || type === 'hide-layer'
            ? false
            : action.shown !== false;
        return setLayerVisibility(layerId, shown, {{ activate: action.activate !== false, reveal: action.reveal !== false }});
      }}
      if (type === 'setlayeropacity' || type === 'set-layer-opacity' || type === 'setopacity' || type === 'set-opacity') {{
        const layerId = String(action.layerId || action.id || activeLayerId || '');
        if (!layerId) return false;
        return setLayerOpacity(layerId, action.opacity ?? action.value, {{ render: true }});
      }}
      if (type === 'setaoistyle' || type === 'set-aoi-style') {{
        STATE.aoiStyle = normalizeAoiStyle({{ ...STATE.aoiStyle, ...(action.style || action) }});
        if (typeof action.shown === 'boolean') STATE.aoiShown = action.shown;
        renderAoiLayer();
        renderLayers();
        syncSessionState('aoi-style');
        return true;
      }}
      if (type === 'updatelayerstyle' || type === 'update-layer-style') {{
        const layerId = String(action.layerId || action.id || activeLayerId || '');
        if (!layerId) return false;
        if (layerId === AOI_LAYER_ID) {{
          STATE.aoiStyle = normalizeAoiStyle({{ ...STATE.aoiStyle, ...(action.style || action) }});
          renderAoiLayer();
          renderLayers();
          syncSessionState('aoi-style');
          return true;
        }}
        if (action.preset || action.stylePreset) {{
          return applyLayerPreset(layerId, String(action.preset || action.stylePreset));
        }}
        return true;
      }}
      if (type === 'clearmeasurements' || type === 'clear-measurements') {{
        clearMeasurements();
        return true;
      }}
      if (type === 'addtask' || type === 'add-task') {{
        return addTask(action.task || action.export || action, {{ reason: 'task-action' }});
      }}
      if (type === 'extractndvi' || type === 'extract-ndvi') {{
        await extractNdviForCurrentAoi(action.options || action);
        return true;
      }}
      if (type === 'exportndvidrive' || type === 'export-ndvi-drive' || type === 'drivendviexport' || type === 'drive-ndvi-export') {{
        await exportNdviToDrive(action.options || action);
        return true;
      }}
      return false;
    }}
    async function pollSessionActions() {{
      if (sessionActionBusy) return false;
      sessionActionBusy = true;
      try {{
        const response = await fetch(`/api/session/actions?since=${{encodeURIComponent(lastSessionActionId)}}`);
        if (!response.ok) return false;
        const payload = await response.json();
        const actions = Array.isArray(payload.actions) ? payload.actions : [];
        for (const action of actions) {{
          const id = Number(action.id || 0);
          if (id > lastSessionActionId) lastSessionActionId = id;
          await executeSessionAction(action);
        }}
        const latest = Number(payload.latestActionId || 0);
        if (latest > lastSessionActionId) lastSessionActionId = latest;
        return true;
      }} catch {{
        return false;
      }} finally {{
        sessionActionBusy = false;
      }}
    }}

    $('dataset-search').addEventListener('input', event => {{
      renderDatasets(filteredCatalog());
    }});
    $('dataset-list').addEventListener('scroll', maybeLoadMoreDatasets);
    $('category-search').addEventListener('input', event => {{
      catalogCategoryQuery = event.target.value || '';
      renderCatalogFacets();
    }});
    $('home-btn').addEventListener('click', () => {{
      resetHomeView();
      updateScaleLine();
      logMsg('log.home');
    }});
    function setBasemap(nextBasemap) {{
      const nextMeta = BASEMAPS.find(item => item.id === nextBasemap);
      if (!nextMeta) return false;
      if (isTiandituBasemap(nextMeta) && !tiandituToken) return requestTiandituToken();
      const nextLayer = basemapLayers.get(nextBasemap);
      if (!nextLayer) return false;
      if (nextBasemap === currentBasemap) {{
        primaryBasemapShown = true;
        setRasterLayerOpacity(nextLayer, primaryBasemapOpacity);
        if (!map.hasLayer(nextLayer)) nextLayer.addTo(map);
        fitCogBasemapBounds(nextMeta);
        renderBasemapChoices();
        renderLayers();
        updateInspector();
        syncSessionState('basemap-visible');
        return true;
      }}
      beginBasemapPerformance(nextMeta, nextLayer);
      fitCogBasemapBounds(nextMeta);
      const currentLayer = basemapLayers.get(currentBasemap);
      if (currentLayer && map.hasLayer(currentLayer)) map.removeLayer(currentLayer);
      primaryBasemapShown = true;
      setRasterLayerOpacity(nextLayer, primaryBasemapOpacity);
      if (!map.hasLayer(nextLayer)) nextLayer.addTo(map);
      currentBasemap = nextBasemap;
      renderBasemapChoices();
      renderLayers();
      updateInspector();
      showModeKey('mode.basemap', {{ basemap: displayBasemapName() }});
      logMsg('log.basemap', {{ basemap: displayBasemapName() }});
      syncSessionState('basemap-changed');
      return true;
    }}
    function toggleBasemapPanel() {{
      const panel = document.querySelector('.basemap-panel');
      const shouldOpen = !panel.classList.contains('open');
      quotaFocus = false;
      document.querySelector('.data-panel').classList.remove('open');
      document.querySelector('.upload-panel').classList.remove('open');
      document.querySelector('.layers-panel').classList.remove('open');
      document.querySelector('.right').classList.remove('open');
      document.querySelector('.bottom').classList.remove('open');
      panel.classList.toggle('open', shouldOpen);
      renderBasemapChoices();
      syncToolState();
    }}
    $('basemap-btn').addEventListener('click', toggleBasemapPanel);
    $('basemap-close-btn').addEventListener('click', () => {{
      document.querySelector('.basemap-panel').classList.remove('open');
      syncToolState();
    }});
    $('basemap-add-btn').addEventListener('click', () => openBasemapEditor());
    $('tianditu-auth-toggle').addEventListener('click', () => {{
      const opening = !$('tianditu-auth').classList.contains('open');
      if (opening && tiandituToken) tiandituKeyEditing = false;
      renderTiandituAuth();
      setTiandituAuthOpen(opening);
    }});
    $('tianditu-token-change').addEventListener('click', editTiandituToken);
    $('tianditu-token-persistence').addEventListener('click', toggleTiandituPersistence);
    $('tianditu-token-apply').addEventListener('click', applyTiandituToken);
    $('tianditu-token').addEventListener('keydown', event => {{
      if (event.key !== 'Enter') return;
      event.preventDefault();
      applyTiandituToken();
    }});
    $('basemap-editor-close').addEventListener('click', closeBasemapEditor);
    $('basemap-form-type').addEventListener('change', updateBasemapTypeFields);
    $('basemap-editor').querySelectorAll('input, select').forEach(field => {{
      field.addEventListener('input', invalidateBasemapTest);
      field.addEventListener('change', invalidateBasemapTest);
    }});
    $('basemap-test-btn').addEventListener('click', () => testBasemapForm());
    $('basemap-editor').addEventListener('submit', event => {{
      event.preventDefault();
      saveBasemapForm();
    }});
    function toggleMeasureMode() {{
      measureMode = !measureMode;
      measurePoints = [];
      measureDraftLayer.clearLayers();
      if (measureMode) {{
        stopDrawAoiMode(false);
        document.querySelector('.data-panel').classList.remove('open');
        document.querySelector('.upload-panel').classList.remove('open');
        document.querySelector('.layers-panel').classList.remove('open');
        document.querySelector('.right').classList.remove('open');
        document.querySelector('.bottom').classList.remove('open');
        document.querySelector('.basemap-panel').classList.remove('open');
      }}
      syncToolState();
      showModeKey(measureMode ? 'mode.measureStart' : 'mode.measureOff', {{}}, measureMode);
      logMsg(measureMode ? 'log.measureOn' : 'log.measureOff');
    }}
    function handleMeasureClick(event) {{
      measurePoints.push(event.latlng);
      renderMeasureDraft();
      if (measurePoints.length === 1) {{
        showModeKey('mode.measureEndpoint', {{}}, true);
        syncToolState();
        return true;
      }}
      const [start, end] = measurePoints;
      const row = saveMeasurement(start, end);
      measureDraftLayer.clearLayers();
      logMsg('log.measured', {{ distance: row.lengthLabel }});
      measurePoints = [];
      syncToolState();
      return true;
    }}
    $('draw-aoi-btn').addEventListener('click', event => toggleDrawAoiMode(event.shiftKey));
    $('measure-btn').addEventListener('click', toggleMeasureMode);
    $('measure-undo-btn').addEventListener('click', undoLastMeasurement);
    async function copyProjectState() {{
      const text = JSON.stringify(buildProjectState(), null, 2);
      try {{
        await navigator.clipboard.writeText(text);
        logMsg('log.copied');
      }} catch {{
        logMsg('log.clipboardUnavailable');
      }}
    }}
    function downloadProjectState() {{
      const blob = new Blob([JSON.stringify(buildProjectState(), null, 2)], {{ type: 'application/json' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'easygee-project.json';
      a.click();
      URL.revokeObjectURL(url);
      logMsg('log.downloaded');
    }}
    $('copy-btn').addEventListener('click', copyProjectState);
    $('download-btn').addEventListener('click', downloadProjectState);
    function togglePanel(which) {{
      const data = document.querySelector('.data-panel');
      const upload = document.querySelector('.upload-panel');
      const layers = document.querySelector('.layers-panel');
      const right = document.querySelector('.right');
      const bottom = document.querySelector('.bottom');
      const basemap = document.querySelector('.basemap-panel');
      quotaFocus = false;
      basemap.classList.remove('open');
      if (which === 'data') {{
        data.classList.toggle('open');
        upload.classList.remove('open');
        layers.classList.remove('open');
        right.classList.remove('open');
        bottom.classList.remove('open');
      }} else if (which === 'upload') {{
        upload.classList.toggle('open');
        data.classList.remove('open');
        layers.classList.remove('open');
        right.classList.remove('open');
        bottom.classList.remove('open');
        renderUploads();
      }} else if (which === 'layers') {{
        const opening = !layers.classList.contains('open');
        layers.classList.toggle('open', opening);
        if (opening) measurementLayerNotice = false;
        data.classList.remove('open');
        upload.classList.remove('open');
        right.classList.remove('open');
        bottom.classList.remove('open');
      }} else if (which === 'right') {{
        right.classList.toggle('open');
        data.classList.remove('open');
        upload.classList.remove('open');
        layers.classList.remove('open');
        bottom.classList.remove('open');
      }}
      syncToolState();
    }}
    function showQuotaStatus() {{
      const bottom = document.querySelector('.bottom');
      if (quotaFocus && bottom.classList.contains('open')) {{
        quotaFocus = false;
        bottom.classList.remove('open');
        $('mode-chip').classList.remove('show');
        syncToolState();
        return;
      }}
      quotaFocus = true;
      document.querySelector('.data-panel').classList.remove('open');
      document.querySelector('.upload-panel').classList.remove('open');
      document.querySelector('.layers-panel').classList.remove('open');
      document.querySelector('.right').classList.remove('open');
      document.querySelector('.basemap-panel').classList.remove('open');
      bottom.classList.add('open');
      $('mode-chip').classList.remove('show');
      syncToolState();
      logMsg('log.quotaOpened');
    }}
    $('data-btn').addEventListener('click', () => togglePanel('data'));
    $('upload-btn').addEventListener('click', () => togglePanel('upload'));
    $('upload-close-btn').addEventListener('click', () => {{
      document.querySelector('.upload-panel').classList.remove('open');
      syncToolState();
    }});
    $('upload-file-input').addEventListener('change', () => {{
      $('upload-status').textContent = '';
      $('upload-status').classList.remove('error');
      renderUploads();
    }});
    $('upload-submit-btn').addEventListener('click', uploadSelectedFiles);
    $('layers-btn').addEventListener('click', () => togglePanel('layers'));
    $('inspector-btn').addEventListener('click', () => togglePanel('right'));
    $('quota-btn').addEventListener('click', showQuotaStatus);
    $('drive-btn').addEventListener('click', openDriveTarget);
    $('lang-btn').addEventListener('click', () => setLanguage(currentLang === 'zh' ? 'en' : 'zh'));
    $('active-layer-badge').addEventListener('click', () => {{
      setBasemapSourceOpen(!basemapSourceOpen, currentBasemap);
    }});
    $('basemap-source-close').addEventListener('click', () => setBasemapSourceOpen(false));
    document.addEventListener('pointerdown', event => {{
      if (!basemapSourceOpen) return;
      if ($('active-layer-badge').contains(event.target) || $('basemap-source-card').contains(event.target)) return;
      setBasemapSourceOpen(false);
    }});
    document.querySelectorAll('[data-close-panel]').forEach(button => {{
      button.addEventListener('click', () => {{
        document.querySelector(`.${{button.dataset.closePanel}}`).classList.remove('open');
        syncToolState();
      }});
    }});
    document.addEventListener('keydown', event => {{
      if (event.key === 'Enter' && drawPolygonMode) {{
        event.preventDefault();
        finishPolygonAoi();
        return;
      }}
      if (event.key !== 'Escape') return;
      if (basemapSourceOpen) {{
        setBasemapSourceOpen(false);
        return;
      }}
      if (drawAoiMode || drawPolygonMode) {{
        stopDrawAoiMode(true);
        return;
      }}
      quotaFocus = false;
      document.querySelector('.data-panel').classList.remove('open');
      document.querySelector('.upload-panel').classList.remove('open');
      document.querySelector('.layers-panel').classList.remove('open');
      document.querySelector('.right').classList.remove('open');
      document.querySelector('.bottom').classList.remove('open');
      document.querySelector('.basemap-panel').classList.remove('open');
      syncToolState();
    }});

    map.on('mousemove', event => {{
      handleDrawAoiMove(event);
      handleDrawPolygonMove(event);
    }});
    map.on('click', event => {{
      if (drawPolygonMode && handleDrawPolygonClick(event)) return;
      if (drawAoiMode && handleDrawAoiClick(event)) return;
      if (measureMode && handleMeasureClick(event)) return;
      $('lat-value').textContent = fmt(event.latlng.lat, 6);
      $('lon-value').textContent = fmt(event.latlng.lng, 6);
      $('zoom-value').textContent = map.getZoom();
      setClickState('state.clicked');
      logMsg('log.clicked', {{ lat: fmt(event.latlng.lat, 4), lon: fmt(event.latlng.lng, 4) }});
    }});
    map.on('dblclick', event => {{
      if (!drawPolygonMode) return;
      L.DomEvent.stop(event);
      finishPolygonAoi();
    }});
    map.on('zoomend moveend', () => {{
      $('zoom-value').textContent = map.getZoom();
      updateScaleLine();
      renderBasemapSourceDetails();
    }});
    window.EasyGEE = {{
      getProjectState: () => buildProjectState(),
      getAoi: () => hasAoi() ? cloneAoi(STATE.aoi) : null,
      setAoi: aoi => updateAoi(aoi),
      clearAoi: () => {{
        return clearAoi();
      }},
      startRectangleAoi: () => startRectangleAoiMode(),
      startPolygonAoi: () => startPolygonAoiMode(),
      getMeasurements: () => STATE.measurements.map(item => ({{ ...item }})),
      getMeasurementSummary: () => measurementSummary(),
      clearMeasurements: () => clearMeasurements(),
      getTasks: () => STATE.tasks.map(item => ({{ ...item }})),
      addTask: task => addTask(task),
      getUploads: () => (STATE.uploads || []).map(item => normalizeUploadRecord(item)).filter(Boolean),
      getUploadCapabilities: () => ({{ ...UPLOAD_CAPABILITIES }}),
      openUploadPanel: () => togglePanel('upload'),
      removeUpload: id => removeUpload(id),
      getDriveUrl: () => driveTargetUrl(),
      openDrive: () => openDriveTarget(),
      getSelectedDataset: () => selectedDatasetContext(),
      getBasemaps: () => BASEMAPS.map(meta => meta.custom
        ? serializableCustomBasemap(meta)
        : {{ id: meta.id, name: basemapDisplayName(meta), provider: meta.provider, service: meta.service || meta.serviceKey, minZoom: meta.options?.minZoom ?? 0, maxZoom: meta.options?.maxZoom, maxNativeZoom: meta.options?.maxNativeZoom ?? meta.options?.maxZoom, builtIn: true }}),
      getCurrentBasemap: () => currentBasemap,
      getDefaultBasemap: () => defaultBasemapId,
      getPerformanceEngine: () => currentPerformanceEngine(),
      setBasemap: id => setBasemap(String(id || '')),
      addBasemapOverlay: id => addBasemapOverlay(String(id || currentBasemap || '')),
      setDefaultBasemap: id => setDefaultBasemap(String(id || '')),
      addCustomBasemap: basemap => executeSessionAction({{ type: 'addCustomBasemap', basemap }}),
      updateCustomBasemap: basemap => executeSessionAction({{ type: 'updateCustomBasemap', basemap }}),
      removeCustomBasemap: id => removeCustomBasemap(String(id || ''), {{ confirm: false }}),
      openBasemapEditor: id => openBasemapEditor(id || null),
      extractNdvi: options => extractNdviForCurrentAoi(options || {{}}),
      exportNdviToDrive: options => exportNdviToDrive(options || {{}}),
      addGeneratedLayer: meta => addGeneratedLayer(meta),
      showLayer: id => setLayerVisibility(String(id || activeLayerId || ''), true),
      hideLayer: id => setLayerVisibility(String(id || activeLayerId || ''), false),
      setLayerVisibility: (id, shown) => setLayerVisibility(String(id || activeLayerId || ''), shown !== false),
      setLayerOpacity: (id, opacity) => setLayerOpacity(String(id || activeLayerId || ''), opacity),
      zoomToLayer: (id, options) => zoomToLayer(String(id || activeLayerId || ''), options || {{}}),
      refreshLayer: id => refreshLayer(String(id || activeLayerId || '')),
      selectLayer: id => selectLayer(String(id || activeLayerId || '')),
      syncState: reason => syncSessionState(reason || 'manual'),
      pollActions: () => pollSessionActions(),
    }};
    renderAoiLayer();
    renderMeasurements();
    renderTasks();
    applyI18n();
    renderDatasets(filteredCatalog());
    renderLayers();
    setActiveLayer(activeLayerId, {{ reveal: false }});
    installPanelResizers();
    syncToolState();
    map.whenReady(() => {{
      setTimeout(() => {{
        map.invalidateSize(true);
        if (!restoreProfileMapView()) resetHomeView();
        updateScaleLine();
      }}, 180);
    }});
    window.addEventListener('resize', () => {{
      map.invalidateSize(true);
      updateScaleLine();
    }});
    logMsg('log.loaded');
    function startSessionProtocol() {{
      syncSessionState('loaded');
      window.setInterval(() => syncSessionState('interval'), SESSION_SYNC_INTERVAL_MS);
      window.setInterval(pollSessionActions, SESSION_ACTION_POLL_MS);
      pollSessionActions();
    }}
    restoreProfileFromServer().finally(startSessionProtocol);
    refreshCatalogFromApi();
  </script>
</body>
</html>
"""


def write_console(
    output: Path,
    state: dict,
    leaflet_src: str,
    pmtiles_src: str = PMTILES_CDN,
    cog_engine_assets: dict[str, str] | None = None,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(state, leaflet_src, pmtiles_src, cog_engine_assets), encoding="utf-8")


def smoke() -> int:
    with tempfile.TemporaryDirectory(prefix="easygee-map-console-") as tmp:
        output = Path(tmp) / "index.html"
        state = sample_state("demo-project", "EasyGEE Smoke Console")
        write_console(output, state, LEAFLET_CDN, PMTILES_CDN)
        text = output.read_text(encoding="utf-8")
        required = [
            "EasyGEE Smoke Console",
            "Add layers",
            "Layers",
            "Inspector",
            "Tasks",
            "drive-btn",
            "Google Drive",
            "Quota items",
            "quota-stat-grid",
            "STATE =",
            ".leaflet-tile",
            "EsriClarity",
            "basemap-source-card",
            "basemapThumbSvg",
            "source.trigger",
            "basemap-editor",
            "addCustomBasemap",
            "customBasemaps",
            "PMTiles (raster)",
            "pmtiles.leafletRasterLayer",
            "HTTP Range",
            "maxNativeZoom: 13",
            "COG (MapLibre WebGL)",
            "COG_ENGINE_ASSETS",
            "MaplibreCOGProtocol.getCogMetadata",
            "L.maplibreGL",
            "maplibre-cog",
            "basemap-source-performance",
            "beginBasemapPerformance",
            "TiandituImagery",
            "TIANDITU_TOKEN_STORAGE_KEY",
            "TILEMATRIXSET=w",
            "collectBasemapNetworkPerformance",
            "const AGENT_PROTOCOL_VERSION = 5;",
        ]
        missing = [item for item in required if item not in text]
        if missing:
            print("FAIL missing markers: " + ", ".join(missing))
            return 1
        filtered = report_warnings_for_console(
            {
                "live_source": "Cloud Quotas REST API",
                "warnings": [
                    "Skipping gcloud quota command groups because local components are not installed: beta, alpha",
                    "Cloud Monitoring request failed: permission denied",
                ],
            }
        )
        if any("Skipping gcloud" in item for item in filtered) or not any("Monitoring" in item for item in filtered):
            print("FAIL quota fallback warning filtering")
            return 1
    print("create_map_console smoke passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="Earth Engine / Google Cloud project id")
    parser.add_argument("--output", type=Path, default=default_output(), help="HTML output path")
    parser.add_argument("--title", default="EasyGEE Map Console")
    parser.add_argument("--lat", type=float, default=DEFAULT_EMPTY_CENTER[0])
    parser.add_argument("--lon", type=float, default=DEFAULT_EMPTY_CENTER[1])
    parser.add_argument("--zoom", type=int, default=DEFAULT_EMPTY_ZOOM)
    parser.add_argument("--buffer-m", type=float, default=25000)
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="2024-12-31")
    parser.add_argument("--cloud-pct", type=float, default=35)
    parser.add_argument("--default-layer", default="", help="Layer id to show by default, for example ndvi, s2-rgb, dynamic-world, jrc-water, or srtm")
    parser.add_argument("--sample", action="store_true", help="Create the legacy sample console without Earth Engine calls")
    parser.add_argument("--live", action="store_true", help="Create a pre-populated Earth Engine demo with default layers")
    parser.add_argument("--no-live-quota", action="store_true", help="Skip Cloud Quotas / Monitoring quota lookup")
    parser.add_argument("--no-quota-usage", action="store_true", help="Skip recent Cloud Monitoring quota usage lookup")
    parser.add_argument(
        "--allow-default-quota-state",
        action="store_true",
        help="Allow --no-live-quota to write default-only quota state to a non-sample page. Use only for explicit no-network previews.",
    )
    parser.add_argument("--quota-minutes", type=int, default=60, help="Lookback window for quota usage metrics")
    parser.add_argument(
        "--catalog-mode",
        choices=("auto", "official", "community", "all", "giswqs", "curated"),
        default="auto",
        help="Dataset catalog source: auto merges official STAC and community CSV; also supports official, community, all, giswqs, or curated",
    )
    parser.add_argument("--refresh-catalog", action="store_true", help="Refresh the cached official STAC catalog")
    parser.add_argument("--catalog-cache-hours", type=int, default=CATALOG_CACHE_MAX_AGE_HOURS, help="Official STAC cache age")
    parser.add_argument("--catalog-fetch-seconds", type=int, default=CATALOG_FETCH_SECONDS, help="Official STAC refresh budget")
    parser.add_argument("--no-local-leaflet", action="store_true", help="Use the Leaflet CDN instead of downloading a local preview copy")
    parser.add_argument("--no-local-pmtiles", action="store_true", help="Use the PMTiles CDN instead of downloading a local preview copy")
    parser.add_argument("--no-local-cog-engine", action="store_true", help="Keep the lazy MapLibre COG engine on pinned CDNs instead of downloading local preview copies")
    parser.add_argument("--json", action="store_true", help="Print a credential-safe output summary as JSON")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        return smoke()
    if args.no_live_quota and not (args.sample or args.allow_default_quota_state):
        parser.error(
            "--no-live-quota would write default-only quota state to a user-facing page. "
            "Use live quota lookup, run refresh_map_console_quota.py for quota-only updates, "
            "or add --allow-default-quota-state only for an explicit no-network preview."
        )

    resolved_project = easygee_project.resolve_project(args.project, remember_discovered=True)
    args.project = resolved_project.project

    if args.sample:
        state = sample_state(args.project, args.title)
    elif args.live:
        state = live_state(args)
    else:
        state = empty_state(args)
    state["projectSource"] = resolved_project.source
    state["quota"] = build_quota_state(
        args.project,
        include_usage=not args.no_quota_usage,
        no_live=args.no_live_quota or args.sample,
        minutes=args.quota_minutes,
    )
    leaflet_src = LEAFLET_CDN if args.no_local_leaflet else ensure_leaflet_js(args.output.parent)
    pmtiles_src = PMTILES_CDN if args.no_local_pmtiles else ensure_pmtiles_js(args.output.parent)
    cog_assets = cog_engine_cdn_assets() if args.no_local_cog_engine else ensure_cog_engine_assets(args.output.parent)
    write_console(args.output, state, leaflet_src, pmtiles_src, cog_assets)
    plan = ConsolePlan(
        output=str(args.output),
        project=args.project,
        project_source=resolved_project.source,
        title=args.title,
        center=(args.lat, args.lon),
        layer_count=len(state["layers"]),
        uses_live_ee=bool(args.live),
        quota_source=state.get("quota", {}).get("source") or "not available",
        quota_usage_source=state.get("quota", {}).get("usageSource") or "not available",
    )
    if args.json:
        print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
    else:
        print(f"Wrote EasyGEE Map Console: {args.output}")
        print(f"Project: {args.project}")
        print(f"Project source: {resolved_project.source}")
        print(f"Layers: {len(state['layers'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
