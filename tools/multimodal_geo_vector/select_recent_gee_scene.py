#!/usr/bin/env python
"""Select a recent clear GEE scene using AOI-local quality and valid pixels.

The selector intentionally returns one image id for boundary-oriented visual
workflows.  It does not build a median composite, because a composite can blur
or invent edges that were never present in one acquisition.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import UTC, datetime, timedelta
from typing import Any


S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
S2_CLOUD_SCORE = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def choose_candidate(
    rows: list[dict[str, Any]],
    *,
    min_valid_fraction: float = 0.98,
    min_clear_fraction: float = 0.80,
    quality_tolerance: float = 0.03,
    allow_best_available: bool = False,
) -> tuple[dict[str, Any], str]:
    """Choose newest scene among candidates close to the best local quality."""
    if not rows:
        raise ValueError("没有候选影像。")
    normalized = []
    for row in rows:
        item = dict(row)
        item["valid_fraction"] = _number(item.get("valid_fraction"))
        item["quality_mean"] = _number(item.get("quality_mean"))
        item["clear_fraction"] = _number(item.get("clear_fraction"))
        item["time_start"] = int(_number(item.get("time_start")))
        normalized.append(item)

    valid = [item for item in normalized if item["valid_fraction"] >= min_valid_fraction]
    if not valid:
        if not allow_best_available:
            raise ValueError(
                "没有影像达到 AOI 有效像元阈值；请扩大时间窗、检查 AOI/波段，或显式使用 --allow-best-available。"
            )
        valid = normalized
        valid_note = "no scene met min_valid_fraction; used the best available coverage"
    else:
        valid_note = "required AOI-valid-pixel coverage"

    clear = [item for item in valid if item["clear_fraction"] >= min_clear_fraction]
    if clear:
        pool = clear
        clear_note = "required AOI-local clear-pixel fraction"
    else:
        if not allow_best_available:
            raise ValueError(
                "没有影像达到 AOI 局部清晰像元阈值；请扩大时间窗，或显式使用 --allow-best-available。"
            )
        pool = valid
        clear_note = "no scene met min_clear_fraction; used the clearest available scene"

    best_quality = max(item["quality_mean"] for item in pool)
    comparable = [item for item in pool if item["quality_mean"] >= best_quality - quality_tolerance]
    selected = max(comparable, key=lambda item: (item["time_start"], item["quality_mean"], item["valid_fraction"]))
    return selected, f"{valid_note}; {clear_note}; newest within {quality_tolerance:.3f} of best local quality"


def _parse_bbox(text: str) -> list[float]:
    values = [float(value.strip()) for value in text.split(",")]
    if len(values) != 4 or values[0] >= values[2] or values[1] >= values[3]:
        raise ValueError("--region 必须为 xmin,ymin,xmax,ymax。")
    return values


def _parse_center(text: str) -> tuple[float, float]:
    values = [float(value.strip()) for value in text.split(",")]
    if len(values) != 2 or not (-180 <= values[0] <= 180 and -90 <= values[1] <= 90):
        raise ValueError("--center 必须为 lon,lat。")
    return values[0], values[1]


def select_scene(args: argparse.Namespace) -> dict[str, Any]:
    import ee

    ee.Initialize(project=args.project)
    if args.region:
        bbox = _parse_bbox(args.region)
        aoi = ee.Geometry.Rectangle(bbox, geodesic=False)
        spatial_seed = {"type": "bbox", "wgs84": bbox}
    else:
        lon, lat = _parse_center(args.center)
        if args.radius_km is None or args.radius_km <= 0:
            raise ValueError("使用 --center 时必须显式提供正数 --radius-km，并在结果中记录该范围假设。")
        aoi = ee.Geometry.Point([lon, lat]).buffer(args.radius_km * 1000).bounds()
        spatial_seed = {"type": "center_radius", "center_wgs84": [lon, lat], "radius_km": args.radius_km}

    end = args.end or datetime.now(UTC).date().isoformat()
    start = args.start or (datetime.fromisoformat(end) - timedelta(days=args.days)).date().isoformat()
    collection = ee.ImageCollection(args.collection).filterBounds(aoi).filterDate(start, end)
    if args.cloud_field and args.cloud_max is not None:
        collection = collection.filter(ee.Filter.lte(args.cloud_field, args.cloud_max))

    uses_cloud_score = args.collection == S2_COLLECTION
    if uses_cloud_score:
        collection = collection.linkCollection(ee.ImageCollection(S2_CLOUD_SCORE), ["cs_cdf"])

    def add_metrics(image):
        image = ee.Image(image)
        valid = image.select(args.valid_band).mask().reduce(ee.Reducer.min()).unmask(0).rename("valid_fraction")
        if uses_cloud_score:
            quality = image.select("cs_cdf").unmask(0).rename("quality_mean")
            clear = quality.gte(args.quality_threshold).unmask(0).rename("clear_fraction")
        else:
            cloud = (
                ee.Number(
                    ee.Algorithms.If(
                        image.propertyNames().contains(args.cloud_field),
                        image.get(args.cloud_field),
                        100,
                    )
                )
                if args.cloud_field
                else ee.Number(100)
            )
            quality_value = ee.Number(1).subtract(cloud.divide(100)).max(0).min(1)
            quality = ee.Image.constant(quality_value).rename("quality_mean")
            clear = ee.Image.constant(quality_value.gte(args.quality_threshold)).rename("clear_fraction")
        metrics = valid.addBands(quality).addBands(clear).reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=aoi,
            scale=args.qa_scale,
            bestEffort=True,
            maxPixels=1_000_000,
            tileScale=4,
        )
        return image.set(
            {
                "valid_fraction": metrics.get("valid_fraction", 0),
                "quality_mean": metrics.get("quality_mean", 0),
                "clear_fraction": metrics.get("clear_fraction", 0),
            }
        )

    scored = collection.map(add_metrics).sort("system:time_start", False).limit(args.limit)
    raw_rows = scored.toList(args.limit).map(
        lambda image: ee.Image(image).toDictionary(
            [
                "system:index",
                "system:time_start",
                args.cloud_field,
                "valid_fraction",
                "quality_mean",
                "clear_fraction",
            ]
        )
    ).getInfo()
    rows: list[dict[str, Any]] = []
    for row in raw_rows:
        item = dict(row)
        index = item.get("system:index")
        item["image_id"] = f"{args.collection}/{index}" if index else None
        millis = int(_number(item.get("system:time_start")))
        item["date"] = datetime.fromtimestamp(millis / 1000, tz=UTC).date().isoformat() if millis else None
        rows.append(item)

    selected, rule = choose_candidate(
        rows,
        min_valid_fraction=args.min_valid_fraction,
        min_clear_fraction=args.min_clear_fraction,
        quality_tolerance=args.quality_tolerance,
        allow_best_available=args.allow_best_available,
    )
    return {
        "selected_image_id": selected.get("image_id"),
        "selected_date": selected.get("date"),
        "selected_metrics": selected,
        "selection_rule": rule,
        "collection": args.collection,
        "date_range": [start, end],
        "spatial_seed": spatial_seed,
        "quality_source": "Cloud Score+ cs_cdf" if uses_cloud_score else f"scene property {args.cloud_field}",
        "candidate_count": len(rows),
        "top_candidates": sorted(
            rows,
            key=lambda item: (_number(item.get("quality_mean")), _number(item.get("valid_fraction")), _number(item.get("time_start"))),
            reverse=True,
        )[: min(10, len(rows))],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("EE_PROJECT", ""))
    parser.add_argument("--collection", default=S2_COLLECTION)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--region", help="xmin,ymin,xmax,ymax in WGS84")
    location.add_argument("--center", help="lon,lat in WGS84")
    parser.add_argument("--radius-km", type=float, help="Required with --center; choose and record a target-scale initial extent.")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--valid-band", default="B4")
    parser.add_argument("--cloud-field", default="CLOUDY_PIXEL_PERCENTAGE")
    parser.add_argument("--cloud-max", type=float, default=50.0)
    parser.add_argument("--qa-scale", type=float, default=100.0)
    parser.add_argument("--quality-threshold", type=float, default=0.60)
    parser.add_argument("--min-valid-fraction", type=float, default=0.98)
    parser.add_argument("--min-clear-fraction", type=float, default=0.80)
    parser.add_argument("--quality-tolerance", type=float, default=0.03)
    parser.add_argument("--allow-best-available", action="store_true", help="Explicitly permit a labelled fallback when quality thresholds are unmet.")
    parser.add_argument("--limit", type=int, default=80)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.project:
        parser.error("需要 --project 或 EE_PROJECT。")
    result = select_scene(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
