#!/usr/bin/env python3
"""Common optical remote-sensing cloud masks for Earth Engine.

The module keeps the masking functions reusable in notebooks and scripts, while
the CLI performs only a small metadata probe. It never starts an export task.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import ee

try:
    from easygee_project import resolve_project
except ImportError:  # pragma: no cover - useful when imported from another cwd
    from skills.easygee.scripts.easygee_project import resolve_project


S2_SR_ID = "COPERNICUS/S2_SR_HARMONIZED"
S2_CLOUD_PROBABILITY_ID = "COPERNICUS/S2_CLOUD_PROBABILITY"
S2_CLOUD_SCORE_PLUS_ID = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"
LANDSAT_8_ID = "LANDSAT/LC08/C02/T1_L2"
LANDSAT_9_ID = "LANDSAT/LC09/C02/T1_L2"


def mask_s2_qa60(image: ee.Image) -> ee.Image:
    """Mask Sentinel-2 opaque cloud and cirrus bits in QA60."""

    qa = image.select("QA60")
    opaque_cloud = qa.bitwiseAnd(1 << 10).eq(0)
    cirrus = qa.bitwiseAnd(1 << 11).eq(0)
    return image.updateMask(opaque_cloud.And(cirrus))


def mask_s2_scl(image: ee.Image, keep_snow: bool = False) -> ee.Image:
    """Mask Sentinel-2 scene-classification cloud, shadow, and invalid classes."""

    scl = image.select("SCL")
    good = (
        scl.neq(0)  # no data
        .And(scl.neq(1))  # saturated or defective
        .And(scl.neq(3))  # cloud shadow
        .And(scl.neq(8))  # medium-probability cloud
        .And(scl.neq(9))  # high-probability cloud
        .And(scl.neq(10))  # cirrus
    )
    if not keep_snow:
        good = good.And(scl.neq(11))  # snow or ice
    return image.updateMask(good)


def add_s2_cloud_probability(collection: ee.ImageCollection) -> ee.ImageCollection:
    """Join the S2 cloud-probability image to each SR image by system:index."""

    probability = ee.ImageCollection(S2_CLOUD_PROBABILITY_ID)
    condition = ee.Filter.equals(leftField="system:index", rightField="system:index")
    joined = ee.Join.saveFirst("cloud_probability").apply(
        primary=collection,
        secondary=probability,
        condition=condition,
    )
    return ee.ImageCollection(joined).filter(ee.Filter.notNull(["cloud_probability"]))


def mask_s2_cloud_probability(image: ee.Image, threshold: float = 40.0) -> ee.Image:
    """Mask pixels whose s2cloudless probability is at or above threshold."""

    probability = ee.Image(image.get("cloud_probability")).select("probability")
    return image.addBands(probability.rename("cloud_probability")).updateMask(
        probability.lt(threshold)
    )


def mask_s2_cloud_probability_shadow(
    image: ee.Image,
    threshold: float = 40.0,
    nir_dark_threshold: float = 0.15,
    shadow_distance_km: float = 1.0,
    buffer_m: float = 50.0,
) -> ee.Image:
    """Mask s2cloudless clouds plus projected shadows, following the public EE tutorial."""

    probability = ee.Image(image.get("cloud_probability")).select("probability")
    clouds = probability.gt(threshold).rename("clouds")

    # S2 SR reflectance is scaled by 10,000; exclude SCL water from dark-pixel candidates.
    not_water = image.select("SCL").neq(6)
    dark_pixels = (
        image.select("B8")
        .lt(nir_dark_threshold * 1e4)
        .And(not_water)
        .rename("dark_pixels")
    )

    shadow_azimuth = ee.Number(90).subtract(
        ee.Number(image.get("MEAN_SOLAR_AZIMUTH_ANGLE"))
    )
    cloud_projection = (
        clouds.directionalDistanceTransform(shadow_azimuth, shadow_distance_km * 10)
        .reproject(crs=image.select(0).projection(), scale=100)
        .select("distance")
        .mask()
        .rename("cloud_transform")
    )
    shadows = cloud_projection.multiply(dark_pixels).rename("shadows")
    cloud_shadow = clouds.add(shadows).gt(0)
    cloud_shadow = (
        cloud_shadow.focalMin(2)
        .focalMax(buffer_m * 2 / 20)
        .reproject(crs=image.select(0).projection(), scale=20)
        .rename("cloudmask")
    )
    return image.addBands(
        ee.Image([probability.rename("cloud_probability"), cloud_shadow])
    ).updateMask(cloud_shadow.Not())


def mask_s2_cloud_score_plus(
    collection: ee.ImageCollection, threshold: float = 0.60
) -> ee.ImageCollection:
    """Mask Sentinel-2 with the official Cloud Score+ cs_cdf band."""

    cloud_score = ee.ImageCollection(S2_CLOUD_SCORE_PLUS_ID)
    return (
        collection.linkCollection(cloud_score, ["cs_cdf"])
        .map(lambda image: image.updateMask(image.select("cs_cdf").gte(threshold)))
    )


def mask_landsat_c2_qa_pixel(image: ee.Image) -> ee.Image:
    """Mask Landsat C2 L2 fill/cloud/shadow/snow and saturated pixels."""

    qa = image.select("QA_PIXEL")
    fill = qa.bitwiseAnd(1 << 0).eq(0)
    dilated_cloud = qa.bitwiseAnd(1 << 1).eq(0)
    cirrus = qa.bitwiseAnd(1 << 2).eq(0)
    cloud = qa.bitwiseAnd(1 << 3).eq(0)
    shadow = qa.bitwiseAnd(1 << 4).eq(0)
    snow = qa.bitwiseAnd(1 << 5).eq(0)
    clear = fill.And(dilated_cloud).And(cirrus).And(cloud).And(shadow).And(snow)
    not_saturated = image.select("QA_RADSAT").eq(0)
    return image.updateMask(clear).updateMask(not_saturated)


def scale_landsat_c2_l2(image: ee.Image) -> ee.Image:
    """Apply Collection 2 Level 2 optical and thermal scale factors."""

    optical = image.select("SR_B.").multiply(0.0000275).add(-0.2)
    thermal = image.select("ST_B.*").multiply(0.00341802).add(149.0)
    return image.addBands(optical, None, True).addBands(thermal, None, True)


def _filter_scenes(
    collection: ee.ImageCollection,
    roi: ee.Geometry,
    start: str,
    end: str,
    max_scene_cloud: float | None,
    scene_cloud_property: str,
) -> ee.ImageCollection:
    result = collection.filterBounds(roi).filterDate(start, end)
    if max_scene_cloud is not None:
        result = result.filter(ee.Filter.lt(scene_cloud_property, max_scene_cloud))
    return result


def build_sentinel2_collection(
    roi: ee.Geometry,
    start: str,
    end: str,
    method: str = "cloud_score_plus",
    threshold: float | None = None,
    max_scene_cloud: float | None = 80.0,
) -> ee.ImageCollection:
    """Build a masked Sentinel-2 SR collection using a named method."""

    collection = _filter_scenes(
        ee.ImageCollection(S2_SR_ID),
        roi,
        start,
        end,
        max_scene_cloud,
        "CLOUDY_PIXEL_PERCENTAGE",
    )
    if method == "qa60":
        return collection.map(mask_s2_qa60)
    if method == "scl":
        return collection.map(mask_s2_scl)
    if method == "cloud_probability":
        joined = add_s2_cloud_probability(collection)
        return joined.map(
            lambda image: mask_s2_cloud_probability(
                image, threshold if threshold is not None else 40.0
            )
        )
    if method == "cloud_score_plus":
        return mask_s2_cloud_score_plus(
            collection, threshold if threshold is not None else 0.60
        )
    raise ValueError(
        "Unsupported Sentinel-2 method. Choose qa60, scl, "
        "cloud_probability, or cloud_score_plus."
    )


def build_landsat_collection(
    roi: ee.Geometry,
    start: str,
    end: str,
    max_scene_cloud: float | None = 80.0,
    apply_scale: bool = True,
) -> ee.ImageCollection:
    """Build a masked Landsat 8/9 Collection 2 Level 2 collection."""

    collection = ee.ImageCollection(LANDSAT_8_ID).merge(
        ee.ImageCollection(LANDSAT_9_ID)
    )
    collection = _filter_scenes(
        collection,
        roi,
        start,
        end,
        max_scene_cloud,
        "CLOUD_COVER",
    ).map(mask_landsat_c2_qa_pixel)
    return collection.map(scale_landsat_c2_l2) if apply_scale else collection


def _parse_aoi(value: str) -> ee.Geometry:
    try:
        coordinates = [float(item.strip()) for item in value.split(",")]
    except ValueError as exc:
        raise ValueError("AOI must be xmin,ymin,xmax,ymax") from exc
    if len(coordinates) != 4:
        raise ValueError("AOI must be xmin,ymin,xmax,ymax")
    xmin, ymin, xmax, ymax = coordinates
    if not (-180 <= xmin < xmax <= 180 and -90 <= ymin < ymax <= 90):
        raise ValueError("AOI coordinates are outside valid longitude/latitude bounds")
    return ee.Geometry.Rectangle([xmin, ymin, xmax, ymax])


def _probe(collection: ee.ImageCollection) -> dict[str, Any]:
    """Fetch only small diagnostics needed to verify the server-side graph."""

    count = int(collection.size().getInfo())
    result: dict[str, Any] = {"collection_size": count}
    if count:
        first = collection.first()
        result["first_system_index"] = first.get("system:index").getInfo()
        result["band_names"] = first.bandNames().getInfo()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensor", choices=["s2", "landsat"], required=True)
    parser.add_argument(
        "--method",
        choices=["qa60", "scl", "cloud_probability", "cloud_score_plus", "qa_pixel"],
        required=True,
    )
    parser.add_argument("--aoi", help="AOI rectangle: xmin,ymin,xmax,ymax")
    parser.add_argument("--start", help="Start date, inclusive, e.g. 2024-06-01")
    parser.add_argument("--end", help="End date, exclusive, e.g. 2024-07-01")
    parser.add_argument("--project", help="Earth Engine / Google Cloud project id")
    parser.add_argument("--threshold", type=float, help="Cloud probability or cs_cdf threshold")
    parser.add_argument("--max-scene-cloud", type=float, default=80.0)
    parser.add_argument("--no-scale", action="store_true", help="Do not scale Landsat C2 L2 bands")
    args = parser.parse_args()

    if args.sensor == "s2" and args.method == "qa_pixel":
        parser.error("qa_pixel is only valid for --sensor landsat")
    if args.sensor == "landsat" and args.method != "qa_pixel":
        parser.error("Landsat currently supports --method qa_pixel")
    if not args.aoi or not args.start or not args.end:
        parser.error("--aoi, --start, and --end are required for a live probe")

    resolved = resolve_project(args.project)
    if not resolved.project or resolved.project == "YOUR_EE_PROJECT":
        parser.error("No Earth Engine project was found; pass --project PROJECT_ID")
    ee.Initialize(project=resolved.project)
    roi = _parse_aoi(args.aoi)

    if args.sensor == "s2":
        collection = build_sentinel2_collection(
            roi,
            args.start,
            args.end,
            method=args.method,
            threshold=args.threshold,
            max_scene_cloud=args.max_scene_cloud,
        )
        dataset = S2_SR_ID
    else:
        collection = build_landsat_collection(
            roi,
            args.start,
            args.end,
            max_scene_cloud=args.max_scene_cloud,
            apply_scale=not args.no_scale,
        )
        dataset = f"{LANDSAT_8_ID} + {LANDSAT_9_ID}"

    effective_threshold = args.threshold
    if args.sensor == "s2" and args.method == "cloud_probability":
        effective_threshold = args.threshold if args.threshold is not None else 40.0
    elif args.sensor == "s2" and args.method == "cloud_score_plus":
        effective_threshold = args.threshold if args.threshold is not None else 0.60

    payload = {
        "sensor": args.sensor,
        "method": args.method,
        "dataset": dataset,
        "project_source": resolved.source,
        "date_range": [args.start, args.end],
        "aoi": args.aoi,
        "threshold": effective_threshold,
        "max_scene_cloud": args.max_scene_cloud,
        "landsat_scale_applied": args.sensor == "landsat" and not args.no_scale,
    }
    payload.update(_probe(collection))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
