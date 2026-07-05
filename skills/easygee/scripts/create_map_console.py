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
import os
import re
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PROJECT = "YOUR_EE_PROJECT"
DEFAULT_EMPTY_CENTER = [20.0, 0.0]
DEFAULT_EMPTY_ZOOM = 2
UNLIMITED_QUOTA_THRESHOLD = 9_000_000_000_000_000_000
LEAFLET_CDN = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
LEAFLET_LOCAL = "leaflet-1.9.4.js"
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


def known_catalog_image(
    ee: Any,
    dataset_id: str,
    roi: Any,
    start_date: str,
    end_date: str,
    cloud_pct: float,
    warnings: list[str],
) -> tuple[Any, dict[str, Any], str, str, list[list[str]], str] | None:
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

    project = str(payload.get("project") or DEFAULT_PROJECT).strip()
    dataset_id = str(payload.get("datasetId") or payload.get("dataset") or "").strip()
    if not dataset_id:
        raise ValueError("datasetId is required")
    if not project or project == DEFAULT_PROJECT:
        raise ValueError("A concrete Earth Engine project id is required")
    west, south, east, north = normalize_bounds(payload.get("bounds"))
    start_date = str(payload.get("startDate") or "2024-01-01")
    end_date = str(payload.get("endDate") or datetime.now(timezone.utc).date().isoformat())
    try:
        cloud_pct = float(payload.get("cloudPct") or 80)
    except Exception:
        cloud_pct = 80.0
    catalog_item = payload.get("catalogItem") if isinstance(payload.get("catalogItem"), dict) else {}

    ee.Initialize(project=project)
    roi = ee.Geometry.Rectangle([west, south, east, north], None, False)
    warnings: list[str] = []

    def tile_url(image: Any, vis: dict[str, Any]) -> str:
        return image.getMapId(vis)["tile_fetcher"].url_format

    asset: dict[str, Any] = {}
    try:
        asset = ee.data.getAsset(dataset_id) or {}
    except Exception:
        asset = {}
    asset_type = str(asset.get("type") or catalog_item.get("type") or "").upper()
    known = known_catalog_image(ee, dataset_id, roi, start_date, end_date, cloud_pct, warnings)
    image: Any
    vis: dict[str, Any]
    name: str
    layer_type: str
    legend: list[list[str]]
    method: str
    if known:
        image, vis, name, layer_type, legend, method = known
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
                except Exception as vector_exc:
                    attempts.append(f"FeatureCollection failed: {vector_exc}")
                    raise ValueError("; ".join(attempts)) from vector_exc

    layer = {
        "id": layer_id_for_dataset(f"{dataset_id}:{start_date}:{end_date}:{west:.5f}:{south:.5f}:{east:.5f}:{north:.5f}"),
        "name": name,
        "dataset": dataset_id,
        "type": layer_type,
        "shown": True,
        "opacity": 0.78 if layer_type == "ee-vector" else 0.82,
        "tileUrl": tile_url(image, vis),
        "legend": legend,
        "method": method,
        "warnings": warnings,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    return {"ok": True, "layer": layer, "warnings": warnings}


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
        "warnings": report_json.get("warnings") or [],
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
    button, input { font: inherit; letter-spacing: 0; }
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
    .icon-btn > svg { display: block; }
    .icon-btn:hover { border-color: var(--line-strong); background: var(--panel-2); }
    .icon-btn.active { border-color: rgba(22, 115, 77, 0.55); background: var(--accent-soft); color: var(--accent); box-shadow: 0 0 0 2px rgba(22, 115, 77, 0.14), 0 3px 12px rgba(16, 24, 40, 0.10); }
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
      width: min(300px, calc(100vw - 66px));
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
    .basemap-body { padding: 10px; display: grid; gap: 8px; min-height: 0; overflow-y: auto; }
    .basemap-choice {
      border: 1px solid #e0e8e4;
      border-radius: 8px;
      background: rgba(255,255,255,0.9);
      padding: 8px;
      display: grid;
      grid-template-columns: 44px minmax(0, 1fr);
      gap: 9px;
      align-items: center;
      cursor: pointer;
      color: var(--text);
      text-align: left;
    }
    .basemap-choice:hover, .basemap-choice.active { border-color: rgba(22, 115, 77, 0.5); background: var(--accent-soft); }
    .basemap-thumb {
      width: 44px;
      height: 34px;
      border-radius: 6px;
      border: 1px solid rgba(16,24,40,0.12);
      overflow: hidden;
      background: #e9f0ec;
      position: relative;
    }
    .basemap-thumb.osm {
      background:
        linear-gradient(35deg, transparent 45%, rgba(215,92,86,0.75) 46%, rgba(215,92,86,0.75) 52%, transparent 53%),
        linear-gradient(120deg, transparent 55%, rgba(229,164,77,0.65) 56%, rgba(229,164,77,0.65) 62%, transparent 63%),
        linear-gradient(0deg, #a7d8ad 0 42%, #f5f3e8 43% 100%);
    }
    .basemap-thumb.light {
      background:
        linear-gradient(36deg, transparent 47%, rgba(143,166,151,0.55) 48%, rgba(143,166,151,0.55) 52%, transparent 53%),
        linear-gradient(116deg, transparent 55%, rgba(194,203,197,0.7) 56%, rgba(194,203,197,0.7) 61%, transparent 62%),
        linear-gradient(0deg, #f8faf7, #edf3ef);
    }
    .basemap-thumb.dark {
      background:
        linear-gradient(35deg, transparent 46%, rgba(89,219,180,0.65) 47%, rgba(89,219,180,0.65) 51%, transparent 52%),
        linear-gradient(112deg, transparent 55%, rgba(138,155,255,0.5) 56%, rgba(138,155,255,0.5) 60%, transparent 61%),
        linear-gradient(0deg, #121a1d, #27333a);
    }
    .basemap-thumb.voyager {
      background:
        linear-gradient(35deg, transparent 45%, rgba(237,126,74,0.68) 46%, rgba(237,126,74,0.68) 51%, transparent 52%),
        linear-gradient(118deg, transparent 55%, rgba(90,155,196,0.62) 56%, rgba(90,155,196,0.62) 61%, transparent 62%),
        linear-gradient(0deg, #b6d7b8 0 38%, #f4ead2 39% 100%);
    }
    .basemap-thumb.topo {
      background:
        radial-gradient(ellipse at 14px 18px, transparent 0 8px, rgba(122,94,58,0.5) 9px 10px, transparent 11px),
        radial-gradient(ellipse at 31px 13px, transparent 0 9px, rgba(122,94,58,0.42) 10px 11px, transparent 12px),
        linear-gradient(135deg, #d8e6ba, #f1e7c5 52%, #c9d7af);
    }
    .basemap-thumb.imagery {
      background:
        radial-gradient(circle at 24px 14px, rgba(35,99,64,0.92) 0 12px, transparent 13px),
        radial-gradient(circle at 8px 24px, rgba(68,118,68,0.85) 0 13px, transparent 14px),
        linear-gradient(135deg, #284d39, #6f8f6a 48%, #9b835e);
    }
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
    .layer-list, .dataset-list, .kv, .log-list { display: grid; gap: 8px; }
    .layer-item, .dataset-item, .stat-row, .task-row {
      border: 1px solid var(--line); background: #fff; border-radius: 6px;
    }
    .layer-item { padding: 9px; min-width: 0; }
    .layer-top { display: flex; align-items: flex-start; gap: 8px; }
    .layer-top input { margin-top: 3px; }
    .layer-copy { min-width: 0; }
    .layer-title-row { display: flex; align-items: center; gap: 6px; min-width: 0; }
    .layer-name { font-size: 13px; font-weight: 700; line-height: 1.25; }
    .type-dot { width: 18px; height: 18px; border-radius: 4px; display: grid; place-items: center; color: #fff; font-size: 10px; font-weight: 800; flex: 0 0 auto; }
    .type-dot.raster { background: #2f7d55; }
    .type-dot.derived { background: #7a58a8; }
    .type-dot.categorical { background: #2f6fa3; }
    .layer-dataset { margin-top: 2px; color: var(--muted); font-size: 11px; line-height: 1.25; overflow-wrap: anywhere; }
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
    #map.draw-aoi { cursor: crosshair; }
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
      .basemap-panel { left: 48px; top: 64px; width: min(292px, calc(100vw - 58px)); max-height: calc(100vh - 76px); }
      .bottom { top: 46px; left: 48px; right: 6px; bottom: 8px; width: auto; max-height: none; overflow: hidden; transform: translateX(calc(100% + 12px)); }
      .mode-chip { left: 48px; max-width: calc(100% - 56px); }
      .simple-scale { left: 48px; }
    }
    """


def sample_state(project: str, title: str) -> dict:
    layers = [
        {
            "id": "sample-dem",
            "name": "SRTM elevation",
            "dataset": "USGS/SRTMGL1_003",
            "type": "ee-raster",
            "shown": True,
            "opacity": 0.58,
            "tileUrl": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            "legend": [
                ["#0f3b2e", "Lower elevation"],
                ["#c9b96d", "Mid elevation"],
                ["#f4f1e8", "Higher elevation"],
            ],
        }
    ]
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


def svg_icon(name: str) -> str:
    icons = {
        "data": '<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5"/><path d="M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>',
        "layers": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 3 8l9 5 9-5-9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 16 9 5 9-5"/></svg>',
        "add": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
        "favorite": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3 6.4 20.2 7.5 14 3 9.6l6.2-.9L12 3Z"/></svg>',
        "external": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 7H5v12h12v-3"/><path d="M11 5h8v8"/><path d="m10 14 9-9"/></svg>',
        "inspect": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>',
        "draw-aoi": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="12" height="10" rx="1.5"/><path d="M14 19h3l4-4-3-3-4 4v3Z"/><path d="m17 13 3 3"/></svg>',
        "measure": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 17 13-13 3 3L7 20l-3-3Z"/><path d="m14 6 2 2M11 9l2 2M8 12l2 2"/></svg>',
        "basemap": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="1.8"/><path d="M7 19c2.4-3.4 3.4-6.2 3.1-12"/><path d="M18 7c-3.9 1.1-6.7 3.2-9.2 6.2"/><path d="M13.4 19c.3-3 1.7-5.5 4.1-7.3"/><path d="M7 13h10"/></svg>',
        "quota": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 14a8 8 0 0 1 16 0"/><path d="M12 14l4-5"/><path d="M5 18h14"/><path d="M8 18v2M16 18v2"/></svg>',
        "tasks": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6h12M9 12h12M9 18h12"/><path d="m3 6 1 1 2-2M3 12l1 1 2-2M3 18l1 1 2-2"/></svg>',
        "home": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/></svg>',
        "zoom-in": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6"/><path d="M10 7v6M7 10h6M15 15l5 5"/></svg>',
        "zoom-out": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6"/><path d="M7 10h6M15 15l5 5"/></svg>',
        "language": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h9M8.5 5v2M11.5 5c-.8 4.7-3.5 7.3-7 8.8"/><path d="M5.5 9.5c1.2 2 3.1 3.5 5.5 4.4"/><path d="M14 20l4-9 4 9M15.2 17h5.6"/></svg>',
        "close": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    }
    return icons[name]


def render_html(state: dict, leaflet_src: str) -> str:
    safe_title = html.escape(state["title"])
    safe_leaflet_src = html.escape(leaflet_src, quote=True)
    logo_data_uri = html.escape(easygee_logo_data_uri(), quote=True)
    state_json = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
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
  <style>
{leaflet_css()}
{shell_css()}
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar" aria-label="{safe_title} EE">
      <h1>{safe_title}</h1>
      <button class="logo-layer collapsed" id="active-layer-badge" type="button" title="Active layer" aria-label="Active layer">
        <span class="mark" aria-hidden="true">{logo_mark}</span>
        <span class="logo-layer-copy"><strong id="active-name"></strong><span id="active-dataset"></span></span>
      </button>
    </header>

    <nav class="tool-rail" aria-label="Map tools">
      <button class="icon-btn" id="data-btn" title="Add layers" aria-label="Add layers" data-i18n-title="tool.data">{svg_icon("data")}</button>
      <button class="icon-btn" id="layers-btn" title="Layers" aria-label="Layers" data-i18n-title="tool.layers">{svg_icon("layers")}</button>
      <button class="icon-btn" id="inspector-btn" title="Inspector" aria-label="Inspector" data-i18n-title="tool.inspector">{svg_icon("inspect")}</button>
      <button class="icon-btn" id="draw-aoi-btn" title="Draw AOI" aria-label="Draw AOI" data-i18n-title="tool.drawAoi">{svg_icon("draw-aoi")}</button>
      <button class="icon-btn" id="measure-btn" title="Measure distance" aria-label="Measure distance" data-i18n-title="tool.measure">{svg_icon("measure")}</button>
      <div class="rail-break" aria-hidden="true"></div>
      <button class="icon-btn" id="basemap-btn" title="Basemap" aria-label="Basemap" data-i18n-title="tool.basemap">{svg_icon("basemap")}</button>
      <button class="icon-btn quota-ready" id="quota-btn" title="Quota status" aria-label="Quota status" data-i18n-title="tool.quota">{svg_icon("quota")}<span class="quota-indicator"></span></button>
      <div class="rail-break" aria-hidden="true"></div>
      <button class="icon-btn" id="home-btn" title="Zoom to AOI" aria-label="Zoom to AOI" data-i18n-title="tool.home">{svg_icon("home")}</button>
      <button class="icon-btn" id="lang-btn" title="Switch language" aria-label="Switch language" data-i18n-title="tool.lang">{svg_icon("language")}<span class="lang-code" id="lang-code">中</span></button>
      <button class="icon-btn wide-only" id="copy-btn" title="Copy project state" aria-label="Copy project state" data-i18n-title="action.copyTitle">C</button>
      <button class="icon-btn wide-only" id="download-btn" title="Download project JSON" aria-label="Download project JSON" data-i18n-title="action.jsonTitle">D</button>
    </nav>

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
      <div class="basemap-body" id="basemap-list"></div>
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
            <div class="kv-row"><div class="kv-key" data-i18n="key.opacity">Opacity</div><div class="kv-value" id="detail-opacity">-</div></div>
          </div>
        </section>
        <section class="right-card">
          <h2 data-i18n="card.legend">Legend</h2>
          <div class="legend" id="legend"></div>
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
  <script>
    const STATE = {state_json};
    STATE.layers = Array.isArray(STATE.layers) ? STATE.layers : [];
    STATE.catalog = Array.isArray(STATE.catalog) ? STATE.catalog : [];
    const logLines = [];
    const layerRegistry = new Map();
    const I18N = {{
      zh: {{
        "tool.data": "添加图层",
        "tool.layers": "图层",
        "tool.inspector": "查看器",
        "tool.drawAoi": "绘制 AOI",
        "tool.measure": "测距",
        "tool.basemap": "底图",
        "tool.quota": "配额状态",
        "tool.home": "回到初始视图",
        "tool.zoomIn": "放大",
        "tool.zoomOut": "缩小",
        "tool.lang": "切换语言",
        "tool.close": "关闭",
        "panel.data": "添加图层",
        "panel.dataSubtitle": "搜索与添加 Earth Engine 数据集",
        "panel.basemap": "底图",
        "panel.layers": "图层",
        "panel.inspector": "查看器",
        "section.layerStack": "图层栈",
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
        "key.latitude": "纬度",
        "key.longitude": "经度",
        "key.zoom": "缩放",
        "key.name": "名称",
        "key.dataset": "数据集",
        "key.type": "类型",
        "key.opacity": "透明度",
        "label.opacity": "透明度",
        "layers.empty": "还没有图层。点“添加图层”搜索 GEE 数据集。",
        "layer.none": "未选择图层",
        "badge.noLayer": "EasyGEE 地图",
        "bottom.project": "配额",
        "link.quota": "控制台",
        "action.copy": "复制",
        "action.json": "JSON",
        "action.copyTitle": "复制项目状态",
        "action.jsonTitle": "下载项目 JSON",
        "pill.project": "项目：:project",
        "pill.aoi": "AOI：:lat, :lon",
        "pill.layers": ":count 个图层",
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
        "mode.measureStart": "测距：点击两个点",
        "mode.measureOff": "测距已关闭",
        "mode.measureEndpoint": "测距：选择终点",
        "mode.distance": "距离：:distance",
        "basemap.osm": "OpenStreetMap",
        "basemap.osmNote": "道路与标注",
        "basemap.light": "浅色",
        "basemap.lightNote": "突出分析图层",
        "basemap.dark": "深色",
        "basemap.darkNote": "夜间对比",
        "basemap.voyager": "彩色",
        "basemap.voyagerNote": "清爽道路与地物",
        "basemap.topo": "地形",
        "basemap.topoNote": "等高线与地貌",
        "basemap.imagery": "影像",
        "basemap.imageryNote": "卫星底图",
        "log.loaded": "EasyGEE 地图控制台已加载",
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
        "log.home": "已回到研究区",
        "log.basemap": "底图已切换为 :basemap",
        "log.aoiOn": "AOI 绘制模式已开启",
        "log.aoiOff": "AOI 绘制模式已关闭",
        "log.aoiDrawn": "AOI 已更新：:bounds",
        "log.measureOn": "测距模式已开启",
        "log.measureOff": "测距模式已关闭",
        "log.measured": "测得距离：:distance",
        "log.copied": "项目状态已复制",
        "log.clipboardUnavailable": "剪贴板不可用",
        "log.downloaded": "项目 JSON 已下载",
        "log.clicked": "点击坐标 :lat, :lon",
        "log.quotaOpened": "已打开配额详情",
        "log.language": "界面语言已切换为中文"
      }},
      en: {{
        "tool.data": "Add layers",
        "tool.layers": "Layers",
        "tool.inspector": "Inspector",
        "tool.drawAoi": "Draw AOI",
        "tool.measure": "Measure distance",
        "tool.basemap": "Basemap",
        "tool.quota": "Quota status",
        "tool.home": "Home view",
        "tool.zoomIn": "Zoom in",
        "tool.zoomOut": "Zoom out",
        "tool.lang": "Switch language",
        "tool.close": "Close",
        "panel.data": "Add Layers",
        "panel.dataSubtitle": "Search and add Earth Engine datasets",
        "panel.basemap": "Basemap",
        "panel.layers": "Layers",
        "panel.inspector": "Inspector",
        "section.layerStack": "Layer Stack",
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
        "key.latitude": "Latitude",
        "key.longitude": "Longitude",
        "key.zoom": "Zoom",
        "key.name": "Name",
        "key.dataset": "Dataset",
        "key.type": "Type",
        "key.opacity": "Opacity",
        "label.opacity": "Opacity",
        "layers.empty": "No layers yet. Use Add layers to search the GEE catalog.",
        "layer.none": "No layer selected",
        "badge.noLayer": "EasyGEE map",
        "bottom.project": "Quotas",
        "link.quota": "Console",
        "action.copy": "Copy",
        "action.json": "JSON",
        "action.copyTitle": "Copy project state",
        "action.jsonTitle": "Download project JSON",
        "pill.project": "Project: :project",
        "pill.aoi": "AOI: :lat, :lon",
        "pill.layers": ":count layers",
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
        "mode.measureStart": "Measure: click two points",
        "mode.measureOff": "Measure off",
        "mode.measureEndpoint": "Measure: choose endpoint",
        "mode.distance": "Distance: :distance",
        "basemap.osm": "OpenStreetMap",
        "basemap.osmNote": "Roads and labels",
        "basemap.light": "Light",
        "basemap.lightNote": "Clean overlay base",
        "basemap.dark": "Dark",
        "basemap.darkNote": "High contrast",
        "basemap.voyager": "Voyager",
        "basemap.voyagerNote": "Balanced roads and places",
        "basemap.topo": "Topo",
        "basemap.topoNote": "Terrain and contours",
        "basemap.imagery": "Imagery",
        "basemap.imageryNote": "Satellite view",
        "log.loaded": "EasyGEE Map Console loaded",
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
        "log.home": "Zoomed to AOI",
        "log.basemap": "Basemap switched to :basemap",
        "log.aoiOn": "AOI draw mode on",
        "log.aoiOff": "AOI draw mode off",
        "log.aoiDrawn": "AOI updated: :bounds",
        "log.measureOn": "Measure mode on",
        "log.measureOff": "Measure mode off",
        "log.measured": "Measured distance: :distance",
        "log.copied": "Project state copied",
        "log.clipboardUnavailable": "Clipboard write unavailable",
        "log.downloaded": "Project JSON downloaded",
        "log.clicked": "Clicked :lat, :lon",
        "log.quotaOpened": "Quota details opened",
        "log.language": "Interface language switched to English"
      }}
    }};
    let activeLayerId = STATE.layers.find(layer => layer.shown)?.id || STATE.layers[0]?.id || null;
    let activeDatasetId = null;
    let activeBadgeTimer = null;
    let currentLang = localStorage.getItem('easygee-lang') || 'zh';
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
    function loadFavoriteDatasetIds() {{
      try {{
        const parsed = JSON.parse(localStorage.getItem(FAVORITES_STORAGE_KEY) || '[]');
        return new Set(Array.isArray(parsed) ? parsed.filter(Boolean).map(String) : []);
      }} catch {{
        return new Set();
      }}
    }}
    let favoriteDatasetIds = loadFavoriteDatasetIds();
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
    }}
    function hasAoiBounds() {{
      return Array.isArray(STATE.bounds)
        && STATE.bounds.length === 2
        && Array.isArray(STATE.bounds[0])
        && Array.isArray(STATE.bounds[1]);
    }}
    function resetHomeView() {{
      if (hasAoiBounds()) {{
        map.fitBounds(STATE.bounds, {{ padding: [24, 24] }});
      }} else {{
        map.setView(STATE.center || [{DEFAULT_EMPTY_CENTER[0]}, {DEFAULT_EMPTY_CENTER[1]}], STATE.zoom || {DEFAULT_EMPTY_ZOOM});
      }}
    }}
    function currentProcessingBounds() {{
      if (hasAoiBounds()) return STATE.bounds;
      const bounds = map.getBounds();
      return [[bounds.getSouth(), bounds.getWest()], [bounds.getNorth(), bounds.getEast()]];
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
      setToolActive('layers-btn', document.querySelector('.layers-panel').classList.contains('open'));
      setToolActive('inspector-btn', document.querySelector('.right').classList.contains('open'));
      setToolActive('draw-aoi-btn', drawAoiMode);
      setToolActive('measure-btn', measureMode);
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
      $('layer-count').textContent = t('pill.layers', {{ count: STATE.layers.length }});
      $('click-state').textContent = t(clickStateKey);
      renderCatalogFacets();
      renderQuota();
      renderBasemapChoices();
      if (currentModeKey && $('mode-chip').classList.contains('show')) {{
        $('mode-chip').textContent = t(currentModeKey.key, currentModeKey.vars);
      }}
    }}
    function layerKind(layer) {{
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
      const meta = BASEMAPS.find(item => item.id === currentBasemap) || BASEMAPS[0];
      return t(meta.nameKey);
    }}
    function renderBasemapChoices() {{
      const current = $('basemap-current');
      if (current) current.textContent = displayBasemapName();
      const list = $('basemap-list');
      if (list) {{
        list.innerHTML = BASEMAPS.map(meta => `
          <button class="basemap-choice ${{meta.id === currentBasemap ? 'active' : ''}}" data-basemap="${{escapeHtml(meta.id)}}" type="button">
            <span class="basemap-thumb ${{escapeHtml(meta.thumb)}}" aria-hidden="true"></span>
            <span class="basemap-copy">
              <span class="basemap-name">${{escapeHtml(t(meta.nameKey))}}</span>
              <span class="basemap-note">${{escapeHtml(t(meta.noteKey))}}</span>
            </span>
          </button>
        `).join('');
        list.querySelectorAll('.basemap-choice').forEach(button => {{
          button.addEventListener('click', () => {{
            setBasemap(button.dataset.basemap);
            document.querySelector('.basemap-panel').classList.remove('open');
            syncToolState();
          }});
        }});
      }}
      document.querySelectorAll('.basemap-choice').forEach(button => {{
        button.classList.toggle('active', button.dataset.basemap === currentBasemap);
      }});
      const title = `${{t('tool.basemap')}} - ${{displayBasemapName()}}`;
      $('basemap-btn').title = title;
      $('basemap-btn').setAttribute('aria-label', title);
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
          <div class="dataset-detail-actions">
            <button class="dataset-detail-command primary" id="dataset-detail-add" type="button">${{escapeHtml(t('data.addFromDetail'))}}</button>
            <button class="dataset-detail-command" id="dataset-detail-copy" type="button">${{escapeHtml(t('data.copyId'))}}</button>
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
          setMode(t('data.detailCopied'));
        }} catch (error) {{
          setMode(t('log.clipboardUnavailable'));
        }}
      }});
    }}
    function setActiveDataset(datasetId) {{
      activeDatasetId = datasetId;
      document.querySelectorAll('.dataset-item').forEach(item => item.classList.toggle('active', item.dataset.dataset === datasetId));
      renderDatasetDetail(datasetId);
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
      setActiveLayer(activeLayerId, {{ reveal: false }});
      updateScaleLine();
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

    const map = L.map('map', {{ zoomControl: false, attributionControl: false }}).setView(STATE.center, STATE.zoom);
    const BASEMAPS = [
      {{
        id: 'OSM',
        nameKey: 'basemap.osm',
        noteKey: 'basemap.osmNote',
        thumb: 'osm',
        url: 'https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
        options: {{ maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }}
      }},
      {{
        id: 'CartoLight',
        nameKey: 'basemap.light',
        noteKey: 'basemap.lightNote',
        thumb: 'light',
        url: 'https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}.png',
        options: {{ maxZoom: 20, attribution: '&copy; OpenStreetMap contributors &copy; CARTO' }}
      }},
      {{
        id: 'CartoDark',
        nameKey: 'basemap.dark',
        noteKey: 'basemap.darkNote',
        thumb: 'dark',
        url: 'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}.png',
        options: {{ maxZoom: 20, attribution: '&copy; OpenStreetMap contributors &copy; CARTO' }}
      }},
      {{
        id: 'CartoVoyager',
        nameKey: 'basemap.voyager',
        noteKey: 'basemap.voyagerNote',
        thumb: 'voyager',
        url: 'https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}.png',
        options: {{ maxZoom: 20, attribution: '&copy; OpenStreetMap contributors &copy; CARTO' }}
      }},
      {{
        id: 'EsriTopo',
        nameKey: 'basemap.topo',
        noteKey: 'basemap.topoNote',
        thumb: 'topo',
        url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{{z}}/{{y}}/{{x}}',
        options: {{ maxZoom: 19, attribution: 'Tiles &copy; Esri' }}
      }},
      {{
        id: 'Imagery',
        nameKey: 'basemap.imagery',
        noteKey: 'basemap.imageryNote',
        thumb: 'imagery',
        url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
        options: {{ maxZoom: 19, attribution: 'Tiles &copy; Esri' }}
      }}
    ];
    const basemapLayers = new Map(BASEMAPS.map(meta => [meta.id, L.tileLayer(meta.url, meta.options)]));
    let currentBasemap = 'OSM';
    basemapLayers.get(currentBasemap).addTo(map);
    let aoiLayer = hasAoiBounds() ? L.rectangle(STATE.bounds, {{ color: '#d23b3b', weight: 2, fill: false }}).addTo(map) : null;

    function registerLayer(meta) {{
      const tile = L.tileLayer(meta.tileUrl, {{ opacity: meta.opacity, attribution: 'Google Earth Engine' }});
      layerRegistry.set(meta.id, {{ meta, tile }});
      if (meta.shown) tile.addTo(map);
      return tile;
    }}
    STATE.layers.forEach(meta => registerLayer(meta));

    function addGeneratedLayer(meta) {{
      const existingIndex = STATE.layers.findIndex(layer => layer.id === meta.id);
      if (existingIndex >= 0) {{
        const existing = layerRegistry.get(meta.id);
        if (existing && map.hasLayer(existing.tile)) map.removeLayer(existing.tile);
        STATE.layers.splice(existingIndex, 1);
      }}
      meta.shown = true;
      STATE.layers.unshift(meta);
      const tile = registerLayer(meta);
      if (!map.hasLayer(tile)) tile.addTo(map);
      $('layer-count').textContent = t('pill.layers', {{ count: STATE.layers.length }});
      renderLayers();
      renderDatasets(filteredCatalog());
      setActiveLayer(meta.id);
    }}

    const measureLayer = L.layerGroup().addTo(map);
    const drawAoiLayer = L.layerGroup().addTo(map);
    let drawAoiMode = false;
    let drawAoiStart = null;
    let drawAoiPreview = null;
    let measureMode = false;
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
      if (activeDatasetId && !items.some(item => item.id === activeDatasetId)) {{
        activeDatasetId = null;
        closeDatasetDetail();
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

    function renderLayers() {{
      if (!STATE.layers.length) {{
        $('layer-list').innerHTML = `<div class="empty-list">${{escapeHtml(t('layers.empty'))}}</div>`;
        updateInspector();
        return;
      }}
      $('layer-list').innerHTML = STATE.layers.map(layer => {{
        const kind = layerKind(layer);
        return `
        <div class="layer-item" data-layer="${{escapeHtml(layer.id)}}">
          <div class="layer-top">
            <input type="checkbox" data-action="toggle" ${{layer.shown ? 'checked' : ''}} aria-label="${{escapeHtml(layer.name)}}">
            <div class="layer-copy">
              <div class="layer-title-row"><span class="type-dot ${{kind.className}}">${{kind.label}}</span><div class="layer-name">${{escapeHtml(layer.name)}}</div></div>
              <div class="layer-dataset">${{escapeHtml(layer.dataset)}}</div>
            </div>
          </div>
          <div class="opacity-row">
            <span>${{escapeHtml(t('label.opacity'))}}</span>
            <input type="range" min="0" max="1" step="0.01" value="${{layer.opacity}}" data-action="opacity">
            <span data-opacity-label>${{Math.round(layer.opacity * 100)}}%</span>
          </div>
        </div>
      `}}).join('');
      document.querySelectorAll('.layer-item').forEach(item => {{
        const id = item.dataset.layer;
        const record = layerRegistry.get(id);
        if (!record) return;
        item.addEventListener('click', event => {{
          if (event.target?.dataset?.action) return;
          setActiveLayer(id);
        }});
        item.querySelector('[data-action="toggle"]').addEventListener('change', event => {{
          record.meta.shown = event.target.checked;
          if (record.meta.shown) {{
            record.tile.addTo(map);
            setActiveLayer(id);
            logMsg('log.layerOn', {{ layer: record.meta.name }});
          }} else {{
            map.removeLayer(record.tile);
            logMsg('log.layerOff', {{ layer: record.meta.name }});
          }}
        }});
        item.querySelector('[data-action="opacity"]').addEventListener('input', event => {{
          const value = Number(event.target.value);
          record.meta.opacity = value;
          record.tile.setOpacity(value);
          item.querySelector('[data-opacity-label]').textContent = `${{Math.round(value * 100)}}%`;
          if (activeLayerId === id) updateInspector();
        }});
      }});
    }}

    function setActiveLayer(id, options = {{}}) {{
      activeLayerId = id || null;
      document.querySelectorAll('.layer-item').forEach(item => {{
        item.style.borderColor = item.dataset.layer === id ? 'var(--accent)' : 'var(--line)';
        item.style.background = item.dataset.layer === id ? 'var(--accent-soft)' : '#fff';
      }});
      updateInspector();
      if (activeLayerId && options.reveal !== false) revealActiveBadge();
    }}

    function updateInspector() {{
      const record = layerRegistry.get(activeLayerId);
      if (!record) {{
        const noLayer = t('layer.none');
        $('active-name').textContent = 'EasyGEE';
        $('active-dataset').textContent = noLayer;
        $('active-layer-badge').title = t('badge.noLayer');
        $('active-layer-badge').setAttribute('aria-label', t('badge.noLayer'));
        $('detail-name').textContent = noLayer;
        $('detail-dataset').textContent = '-';
        $('detail-type').textContent = '-';
        $('detail-opacity').textContent = '-';
        $('legend').innerHTML = `<div class="empty-list">${{escapeHtml(noLayer)}}</div>`;
        return;
      }}
      const layer = record.meta;
      $('active-name').textContent = layer.name;
      $('active-dataset').textContent = layer.dataset;
      const badgeLabel = `${{layer.name}} - ${{layer.dataset}}`;
      $('active-layer-badge').title = badgeLabel;
      $('active-layer-badge').setAttribute('aria-label', badgeLabel);
      $('detail-name').textContent = layer.name;
      $('detail-dataset').textContent = layer.dataset;
      $('detail-type').textContent = layer.type;
      $('detail-opacity').textContent = `${{Math.round(layer.opacity * 100)}}%`;
      $('legend').innerHTML = (layer.legend || []).map(([color, label]) => `
        <div class="legend-row"><span class="swatch" style="background:${{escapeHtml(color)}}"></span><span>${{escapeHtml(label)}}</span></div>
      `).join('');
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
      document.querySelector('.layers-panel').classList.remove('open');
      document.querySelector('.right').classList.remove('open');
      document.querySelector('.bottom').classList.remove('open');
      document.querySelector('.basemap-panel').classList.remove('open');
    }}
    function clearAoiPreview() {{
      drawAoiLayer.clearLayers();
      drawAoiPreview = null;
    }}
    function stopDrawAoiMode(announce = true) {{
      const wasActive = drawAoiMode || drawAoiStart;
      drawAoiMode = false;
      drawAoiStart = null;
      clearAoiPreview();
      map.getContainer().classList.remove('draw-aoi');
      syncToolState();
      if (announce && wasActive) {{
        showModeKey('mode.aoiOff', {{}}, false);
        logMsg('log.aoiOff');
      }}
    }}
    function toggleDrawAoiMode() {{
      if (drawAoiMode) {{
        stopDrawAoiMode(true);
        return;
      }}
      measureMode = false;
      measurePoints = [];
      measureLayer.clearLayers();
      closeFloatingPanels();
      drawAoiMode = true;
      drawAoiStart = null;
      clearAoiPreview();
      map.getContainer().classList.add('draw-aoi');
      syncToolState();
      showModeKey('mode.aoiStart', {{}}, true);
      logMsg('log.aoiOn');
    }}
    function updateAoiBounds(bounds) {{
      STATE.bounds = bounds;
      if (!aoiLayer) {{
        aoiLayer = L.rectangle(bounds, {{ color: '#d23b3b', weight: 2, fill: false }}).addTo(map);
      }} else {{
        aoiLayer.setBounds(bounds);
      }}
      aoiLayer.bringToFront();
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

    function buildProjectState() {{
      return {{
        title: STATE.title,
        project: STATE.project,
        center: [map.getCenter().lat, map.getCenter().lng],
        zoom: map.getZoom(),
        basemap: currentBasemap,
        bounds: hasAoiBounds() ? STATE.bounds : null,
        language: currentLang,
        favoriteDatasets: [...favoriteDatasetIds].sort(),
        quota: STATE.quota,
        layers: STATE.layers.map(layer => ({{
          id: layer.id,
          name: layer.name,
          dataset: layer.dataset,
          shown: layerRegistry.has(layer.id) ? map.hasLayer(layerRegistry.get(layer.id).tile) : Boolean(layer.shown),
          opacity: layer.opacity
        }}))
      }};
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
      const nextLayer = basemapLayers.get(nextBasemap);
      if (!nextLayer) return;
      if (nextBasemap === currentBasemap) {{
        renderBasemapChoices();
        return;
      }}
      const currentLayer = basemapLayers.get(currentBasemap);
      if (currentLayer && map.hasLayer(currentLayer)) map.removeLayer(currentLayer);
      if (!map.hasLayer(nextLayer)) nextLayer.addTo(map);
      currentBasemap = nextBasemap;
      renderBasemapChoices();
      showModeKey('mode.basemap', {{ basemap: displayBasemapName() }});
      logMsg('log.basemap', {{ basemap: displayBasemapName() }});
    }}
    function toggleBasemapPanel() {{
      const panel = document.querySelector('.basemap-panel');
      const shouldOpen = !panel.classList.contains('open');
      quotaFocus = false;
      document.querySelector('.data-panel').classList.remove('open');
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
    function toggleMeasureMode() {{
      measureMode = !measureMode;
      measurePoints = [];
      measureLayer.clearLayers();
      if (measureMode) {{
        stopDrawAoiMode(false);
        document.querySelector('.data-panel').classList.remove('open');
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
      L.circleMarker(event.latlng, {{
        radius: 4,
        color: '#16734d',
        fillColor: '#16734d',
        fillOpacity: 1,
        weight: 2,
      }}).addTo(measureLayer);
      if (measurePoints.length === 1) {{
        showModeKey('mode.measureEndpoint', {{}}, true);
        return true;
      }}
      const [start, end] = measurePoints;
      const meters = distanceMeters(start, end);
      L.polyline(measurePoints, {{ color: '#16734d', weight: 3, dashArray: '6 5' }}).addTo(measureLayer);
      const label = formatDistance(meters);
      showModeKey('mode.distance', {{ distance: label }}, true);
      logMsg('log.measured', {{ distance: label }});
      measurePoints = [];
      return true;
    }}
    $('draw-aoi-btn').addEventListener('click', toggleDrawAoiMode);
    $('measure-btn').addEventListener('click', toggleMeasureMode);
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
      const layers = document.querySelector('.layers-panel');
      const right = document.querySelector('.right');
      const bottom = document.querySelector('.bottom');
      const basemap = document.querySelector('.basemap-panel');
      quotaFocus = false;
      basemap.classList.remove('open');
      if (which === 'data') {{
        data.classList.toggle('open');
        layers.classList.remove('open');
        right.classList.remove('open');
        bottom.classList.remove('open');
      }} else if (which === 'layers') {{
        layers.classList.toggle('open');
        data.classList.remove('open');
        right.classList.remove('open');
        bottom.classList.remove('open');
      }} else if (which === 'right') {{
        right.classList.toggle('open');
        data.classList.remove('open');
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
      document.querySelector('.layers-panel').classList.remove('open');
      document.querySelector('.right').classList.remove('open');
      document.querySelector('.basemap-panel').classList.remove('open');
      bottom.classList.add('open');
      $('mode-chip').classList.remove('show');
      syncToolState();
      logMsg('log.quotaOpened');
    }}
    $('data-btn').addEventListener('click', () => togglePanel('data'));
    $('layers-btn').addEventListener('click', () => togglePanel('layers'));
    $('inspector-btn').addEventListener('click', () => togglePanel('right'));
    $('quota-btn').addEventListener('click', showQuotaStatus);
    $('lang-btn').addEventListener('click', () => setLanguage(currentLang === 'zh' ? 'en' : 'zh'));
    $('active-layer-badge').addEventListener('click', () => {{
      if ($('active-layer-badge').classList.contains('collapsed')) revealActiveBadge(0);
      else collapseActiveBadge();
    }});
    document.querySelectorAll('[data-close-panel]').forEach(button => {{
      button.addEventListener('click', () => {{
        document.querySelector(`.${{button.dataset.closePanel}}`).classList.remove('open');
        syncToolState();
      }});
    }});
    document.addEventListener('keydown', event => {{
      if (event.key !== 'Escape') return;
      if (drawAoiMode) {{
        stopDrawAoiMode(true);
        return;
      }}
      quotaFocus = false;
      document.querySelector('.data-panel').classList.remove('open');
      document.querySelector('.layers-panel').classList.remove('open');
      document.querySelector('.right').classList.remove('open');
      document.querySelector('.bottom').classList.remove('open');
      document.querySelector('.basemap-panel').classList.remove('open');
      syncToolState();
    }});

    map.on('mousemove', event => {{
      handleDrawAoiMove(event);
    }});
    map.on('click', event => {{
      if (drawAoiMode && handleDrawAoiClick(event)) return;
      if (measureMode && handleMeasureClick(event)) return;
      $('lat-value').textContent = fmt(event.latlng.lat, 6);
      $('lon-value').textContent = fmt(event.latlng.lng, 6);
      $('zoom-value').textContent = map.getZoom();
      setClickState('state.clicked');
      logMsg('log.clicked', {{ lat: fmt(event.latlng.lat, 4), lon: fmt(event.latlng.lng, 4) }});
    }});
    map.on('zoomend moveend', () => {{
      $('zoom-value').textContent = map.getZoom();
      updateScaleLine();
    }});
    applyI18n();
    renderDatasets(filteredCatalog());
    renderLayers();
    setActiveLayer(activeLayerId, {{ reveal: false }});
    installPanelResizers();
    syncToolState();
    map.whenReady(() => {{
      setTimeout(() => {{
        map.invalidateSize(true);
        resetHomeView();
        updateScaleLine();
      }}, 180);
    }});
    window.addEventListener('resize', () => {{
      map.invalidateSize(true);
      updateScaleLine();
    }});
    logMsg('log.loaded');
    refreshCatalogFromApi();
  </script>
</body>
</html>
"""


def write_console(output: Path, state: dict, leaflet_src: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(state, leaflet_src), encoding="utf-8")


def smoke() -> int:
    with tempfile.TemporaryDirectory(prefix="easygee-map-console-") as tmp:
        output = Path(tmp) / "index.html"
        state = sample_state("demo-project", "EasyGEE Smoke Console")
        write_console(output, state, LEAFLET_CDN)
        text = output.read_text(encoding="utf-8")
        required = [
            "EasyGEE Smoke Console",
            "Add layers",
            "Layers",
            "Inspector",
            "Quota items",
            "quota-stat-grid",
            "STATE =",
            ".leaflet-tile",
        ]
        missing = [item for item in required if item not in text]
        if missing:
            print("FAIL missing markers: " + ", ".join(missing))
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
    parser.add_argument("--quota-minutes", type=int, default=60, help="Lookback window for quota usage metrics")
    parser.add_argument(
        "--catalog-mode",
        choices=("auto", "official", "giswqs", "curated"),
        default="auto",
        help="Dataset catalog source: auto merges official STAC and community CSV; also supports official, community, all, giswqs, or curated",
    )
    parser.add_argument("--refresh-catalog", action="store_true", help="Refresh the cached official STAC catalog")
    parser.add_argument("--catalog-cache-hours", type=int, default=CATALOG_CACHE_MAX_AGE_HOURS, help="Official STAC cache age")
    parser.add_argument("--catalog-fetch-seconds", type=int, default=CATALOG_FETCH_SECONDS, help="Official STAC refresh budget")
    parser.add_argument("--no-local-leaflet", action="store_true", help="Use the Leaflet CDN instead of downloading a local preview copy")
    parser.add_argument("--json", action="store_true", help="Print a credential-safe output summary as JSON")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        return smoke()

    if args.sample:
        state = sample_state(args.project, args.title)
    elif args.live:
        state = live_state(args)
    else:
        state = empty_state(args)
    state["quota"] = build_quota_state(
        args.project,
        include_usage=not args.no_quota_usage,
        no_live=args.no_live_quota or args.sample,
        minutes=args.quota_minutes,
    )
    leaflet_src = LEAFLET_CDN if args.no_local_leaflet else ensure_leaflet_js(args.output.parent)
    write_console(args.output, state, leaflet_src)
    plan = ConsolePlan(
        output=str(args.output),
        project=args.project,
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
        print(f"Layers: {len(state['layers'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
