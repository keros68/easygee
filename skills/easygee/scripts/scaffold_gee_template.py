#!/usr/bin/env python
"""Generate opinionated GEE/geemap starter templates for common tasks."""

from __future__ import annotations

import argparse
import json
import textwrap
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BBOX = [119.8, 30.0, 120.5, 30.5]


@dataclass(frozen=True)
class Profile:
    id: str
    title: str
    description: str
    datasets: tuple[str, ...]
    review_focus: tuple[str, ...]


PROFILES = {
    "s2-ndvi-cloud-score": Profile(
        id="s2-ndvi-cloud-score",
        title="Sentinel-2 NDVI with Cloud Score+",
        description="Clear-pixel Sentinel-2 SR NDVI map with RGB, NDVI, small reducer probe, and prepared Drive export.",
        datasets=("COPERNICUS/S2_SR_HARMONIZED", "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"),
        review_focus=("Cloud Score+ linked and thresholded", "Export has scale and region", "AOI is explicit"),
    ),
    "s1-flood-area": Profile(
        id="s1-flood-area",
        title="Sentinel-1 Flood Candidate Area",
        description="Pre/post Sentinel-1 VV/VH flood-candidate mask with pixel-area summary and table export.",
        datasets=("COPERNICUS/S1_GRD",),
        review_focus=("Threshold is a candidate, not universal truth", "Speckle/terrain/urban caveats included", "Area uses pixelArea"),
    ),
    "landsat-lst": Profile(
        id="landsat-lst",
        title="Landsat 8/9 Land Surface Temperature",
        description="Landsat Collection 2 LST composite with QA_PIXEL mask, scale conversion, map layers, and export.",
        datasets=("LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2"),
        review_focus=("ST_B10 scale/offset converted", "QA_PIXEL mask applied", "Thermal units are documented"),
    ),
    "modis-vi-timeseries": Profile(
        id="modis-vi-timeseries",
        title="MODIS Vegetation Index Time Series",
        description="MOD13Q1 NDVI/EVI zonal time-series table with QA filtering and CSV export.",
        datasets=("MODIS/061/MOD13Q1",),
        review_focus=("NDVI/EVI scale factor applied", "SummaryQA mask applied", "Table is exported, not downloaded with getInfo"),
    ),
    "dynamic-world-area": Profile(
        id="dynamic-world-area",
        title="Dynamic World Class Area",
        description="Dynamic World class-mode map with grouped pixel-area summary and class legend hooks.",
        datasets=("GOOGLE/DYNAMICWORLD/V1",),
        review_focus=("Label is categorical", "Area uses grouped pixelArea", "Probability/confidence caveat included"),
    ),
    "jrc-water-change": Profile(
        id="jrc-water-change",
        title="JRC Global Surface Water Baseline",
        description="JRC occurrence/seasonality/transition layers with thresholded baseline water area summary.",
        datasets=("JRC/GSW1_4/GlobalSurfaceWater",),
        review_focus=("Historical baseline, not event flood truth", "Threshold documented", "Area uses pixelArea"),
    ),
}


def parse_bbox(values: list[str] | None) -> list[float]:
    if values is None:
        return DEFAULT_BBOX
    if len(values) != 4:
        raise argparse.ArgumentTypeError("bbox needs four numbers: west south east north")
    try:
        west, south, east, north = [float(value) for value in values]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("bbox values must be numeric") from exc
    if not (-180 <= west < east <= 180):
        raise argparse.ArgumentTypeError("bbox longitude must satisfy -180 <= west < east <= 180")
    if not (-90 <= south < north <= 90):
        raise argparse.ArgumentTypeError("bbox latitude must satisfy -90 <= south < north <= 90")
    return [west, south, east, north]


def py(value: object) -> str:
    return repr(value)


def constants(args: argparse.Namespace, bbox: list[float]) -> str:
    return textwrap.dedent(
        f"""
        PROJECT = {py(args.project)}
        BBOX = {py(bbox)}
        START_DATE = {py(args.start)}
        END_DATE = {py(args.end)}
        BASELINE_START = {py(args.baseline_start)}
        BASELINE_END = {py(args.baseline_end)}
        SCALE = {args.scale}
        EXPORT_PREFIX = {py(args.export_prefix)}
        DRIVE_FOLDER = {py(args.drive_folder)}

        ee.Initialize(project=PROJECT)
        roi = ee.Geometry.Rectangle(BBOX, proj="EPSG:4326", geodesic=False)
        """
    ).strip()


def s2_ndvi_code() -> str:
    return r'''
S2 = "COPERNICUS/S2_SR_HARMONIZED"
CLOUD_SCORE = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"


def mask_s2_clear(image):
    return image.updateMask(image.select("cs_cdf").gte(0.60))


def build_collection():
    s2 = (
        ee.ImageCollection(S2)
        .filterBounds(roi)
        .filterDate(START_DATE, END_DATE)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 80))
    )
    return s2.linkCollection(ee.ImageCollection(CLOUD_SCORE), ["cs_cdf"]).map(mask_s2_clear)


collection = build_collection()
composite = collection.median().clip(roi)
ndvi = composite.normalizedDifference(["B8", "B4"]).rename("NDVI")

Map = geemap.Map()
Map.add_basemap("HYBRID")
Map.centerObject(roi, 10)
Map.addLayer(composite, {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}, "S2 SR RGB clear median")
Map.addLayer(ndvi, {"min": -0.2, "max": 0.8, "palette": ["8c510a", "f7f7f7", "1a9850"]}, "NDVI clear median")
Map.addLayer(roi, {}, "AOI")
Map

print("Small probes only:")
print("Collection size:", collection.size().getInfo())
print("Bands:", composite.bandNames().getInfo())
print("NDVI mean:", ndvi.reduceRegion(ee.Reducer.mean(), roi, scale=10, maxPixels=1e9, bestEffort=True).getInfo())

task = ee.batch.Export.image.toDrive(
    image=ndvi.clip(roi),
    description=EXPORT_PREFIX,
    folder=DRIVE_FOLDER,
    fileNamePrefix=EXPORT_PREFIX,
    region=roi,
    scale=10,
    maxPixels=1e13,
    fileFormat="GeoTIFF",
    formatOptions={"cloudOptimized": True},
)
print("Export prepared; inspect then call task.start() if desired:", task.id)
'''


def s1_flood_code() -> str:
    return r'''
S1 = "COPERNICUS/S1_GRD"
FLOOD_VV_THRESHOLD_DB = -16
VV_DROP_THRESHOLD_DB = -1.5


def s1_collection(start, end):
    return (
        ee.ImageCollection(S1)
        .filterBounds(roi)
        .filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .filter(ee.Filter.eq("resolution_meters", 10))
        .select(["VV", "VH"])
    )


before = s1_collection(BASELINE_START, BASELINE_END).median().clip(roi)
after = s1_collection(START_DATE, END_DATE).median().clip(roi)
vv_drop = after.select("VV").subtract(before.select("VV")).rename("VV_drop_db")
flood_candidate = (
    after.select("VV").lt(FLOOD_VV_THRESHOLD_DB)
    .And(vv_drop.lt(VV_DROP_THRESHOLD_DB))
    .selfMask()
    .rename("flood_candidate")
)
flood_area_m2 = flood_candidate.multiply(ee.Image.pixelArea()).rename("area_m2")

Map = geemap.Map()
Map.add_basemap("HYBRID")
Map.centerObject(roi, 10)
Map.addLayer(before.select("VV"), {"min": -25, "max": 0}, "S1 VV baseline")
Map.addLayer(after.select("VV"), {"min": -25, "max": 0}, "S1 VV event")
Map.addLayer(vv_drop, {"min": -6, "max": 3, "palette": ["08306b", "f7f7f7", "b30000"]}, "VV drop dB")
Map.addLayer(flood_candidate, {"palette": ["00bfff"]}, "Flood candidate mask")
Map.addLayer(roi, {}, "AOI")
Map

area = flood_area_m2.reduceRegion(
    reducer=ee.Reducer.sum(),
    geometry=roi,
    scale=10,
    maxPixels=1e10,
    bestEffort=True,
)
print("Candidate flood area m2:", area.getInfo())

summary = ee.FeatureCollection([
    ee.Feature(None, {
        "baseline_start": BASELINE_START,
        "baseline_end": BASELINE_END,
        "event_start": START_DATE,
        "event_end": END_DATE,
        "vv_threshold_db": FLOOD_VV_THRESHOLD_DB,
        "vv_drop_threshold_db": VV_DROP_THRESHOLD_DB,
        "area_m2": area.get("area_m2"),
    })
])
task = ee.batch.Export.table.toDrive(
    collection=summary,
    description=EXPORT_PREFIX,
    folder=DRIVE_FOLDER,
    fileNamePrefix=EXPORT_PREFIX,
    fileFormat="CSV",
)
print("Table export prepared; inspect thresholds and call task.start() if desired:", task.id)
'''


def landsat_lst_code() -> str:
    return r'''
LC08 = "LANDSAT/LC08/C02/T1_L2"
LC09 = "LANDSAT/LC09/C02/T1_L2"


def mask_landsat_c2(image):
    qa = image.select("QA_PIXEL")
    clear = (
        qa.bitwiseAnd(1 << 1).eq(0)
        .And(qa.bitwiseAnd(1 << 2).eq(0))
        .And(qa.bitwiseAnd(1 << 3).eq(0))
        .And(qa.bitwiseAnd(1 << 4).eq(0))
        .And(qa.bitwiseAnd(1 << 5).eq(0))
    )
    lst_c = image.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("LST_C")
    rgb = image.select(["SR_B4", "SR_B3", "SR_B2"]).multiply(0.0000275).add(-0.2)
    return image.addBands(rgb, None, True).addBands(lst_c).updateMask(clear)


collection = (
    ee.ImageCollection(LC08)
    .merge(ee.ImageCollection(LC09))
    .filterBounds(roi)
    .filterDate(START_DATE, END_DATE)
    .map(mask_landsat_c2)
)
composite = collection.median().clip(roi)
lst = composite.select("LST_C")

Map = geemap.Map()
Map.add_basemap("HYBRID")
Map.centerObject(roi, 10)
Map.addLayer(composite, {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 0.02, "max": 0.35}, "Landsat scaled RGB")
Map.addLayer(lst, {"min": 15, "max": 45, "palette": ["2c7bb6", "ffffbf", "d7191c"]}, "LST C")
Map.addLayer(roi, {}, "AOI")
Map

print("Collection size:", collection.size().getInfo())
print("LST C stats:", lst.reduceRegion(ee.Reducer.mean().combine(ee.Reducer.minMax(), "", True), roi, scale=30, maxPixels=1e9, bestEffort=True).getInfo())

task = ee.batch.Export.image.toDrive(
    image=lst.clip(roi),
    description=EXPORT_PREFIX,
    folder=DRIVE_FOLDER,
    fileNamePrefix=EXPORT_PREFIX,
    region=roi,
    scale=30,
    maxPixels=1e13,
    fileFormat="GeoTIFF",
)
print("LST export prepared; inspect then call task.start() if desired:", task.id)
'''


def modis_vi_timeseries_code() -> str:
    return r'''
MOD13Q1 = "MODIS/061/MOD13Q1"
zones = ee.FeatureCollection([ee.Feature(roi, {"zone_id": "aoi"})])


def mask_and_scale(image):
    good = image.select("SummaryQA").lte(1)
    ndvi = image.select("NDVI").multiply(0.0001).rename("NDVI")
    evi = image.select("EVI").multiply(0.0001).rename("EVI")
    return image.addBands([ndvi, evi], None, True).updateMask(good)


def image_to_zone_rows(image):
    date = ee.Date(image.get("system:time_start")).format("YYYY-MM-dd")
    rows = image.select(["NDVI", "EVI"]).reduceRegions(
        collection=zones,
        reducer=ee.Reducer.mean(),
        scale=250,
    )
    return rows.map(lambda feature: feature.set("date", date))


collection = (
    ee.ImageCollection(MOD13Q1)
    .filterBounds(roi)
    .filterDate(START_DATE, END_DATE)
    .map(mask_and_scale)
)
series = collection.map(image_to_zone_rows).flatten()

Map = geemap.Map()
Map.centerObject(roi, 8)
Map.addLayer(collection.select("NDVI").median().clip(roi), {"min": 0, "max": 0.8, "palette": ["f7f7f7", "1a9850"]}, "MODIS median NDVI")
Map.addLayer(zones, {}, "Zones")
Map

print("Image count:", collection.size().getInfo())
print("First few rows:", series.limit(5).getInfo())

task = ee.batch.Export.table.toDrive(
    collection=series,
    description=EXPORT_PREFIX,
    folder=DRIVE_FOLDER,
    fileNamePrefix=EXPORT_PREFIX,
    fileFormat="CSV",
)
print("Time-series CSV export prepared; call task.start() if desired:", task.id)
'''


def dynamic_world_area_code() -> str:
    return r'''
DW = "GOOGLE/DYNAMICWORLD/V1"
CLASS_NAMES = {
    0: "water",
    1: "trees",
    2: "grass",
    3: "flooded_vegetation",
    4: "crops",
    5: "shrub_and_scrub",
    6: "built",
    7: "bare",
    8: "snow_and_ice",
}


collection = ee.ImageCollection(DW).filterBounds(roi).filterDate(START_DATE, END_DATE)
label = collection.select("label").mode().clip(roi).rename("label")
confidence = collection.select(list(CLASS_NAMES.values())).max().reduce(ee.Reducer.max()).clip(roi).rename("max_probability")
area_stack = ee.Image.pixelArea().rename("area_m2").addBands(label)

grouped = area_stack.reduceRegion(
    reducer=ee.Reducer.sum().group(groupField=1, groupName="class"),
    geometry=roi,
    scale=10,
    maxPixels=1e10,
    bestEffort=True,
)

Map = geemap.Map()
Map.add_basemap("HYBRID")
Map.centerObject(roi, 10)
Map.addLayer(label, {"min": 0, "max": 8, "palette": ["419bdf", "397d49", "88b053", "7a87c6", "e49635", "dfc35a", "c4281b", "a59b8f", "b39fe1"]}, "Dynamic World mode label")
Map.addLayer(confidence, {"min": 0, "max": 1, "palette": ["ffffff", "08306b"]}, "Max class probability")
Map.addLayer(roi, {}, "AOI")
Map

print("Image count:", collection.size().getInfo())
print("Grouped area by class:", grouped.getInfo())

rows = ee.FeatureCollection(
    ee.List(grouped.get("groups")).map(
        lambda item: ee.Feature(None, {
            "class": ee.Dictionary(item).get("class"),
            "class_name": ee.Dictionary(CLASS_NAMES).get(ee.Dictionary(item).get("class")),
            "area_m2": ee.Dictionary(item).get("sum"),
        })
    )
)
task = ee.batch.Export.table.toDrive(
    collection=rows,
    description=EXPORT_PREFIX,
    folder=DRIVE_FOLDER,
    fileNamePrefix=EXPORT_PREFIX,
    fileFormat="CSV",
)
print("Class-area table export prepared; call task.start() if desired:", task.id)
'''


def jrc_water_change_code() -> str:
    return r'''
JRC_GSW = "JRC/GSW1_4/GlobalSurfaceWater"
OCCURRENCE_THRESHOLD = 50


gsw = ee.Image(JRC_GSW).clip(roi)
occurrence = gsw.select("occurrence")
seasonality = gsw.select("seasonality")
transition = gsw.select("transition")
baseline_water = occurrence.gte(OCCURRENCE_THRESHOLD).selfMask().rename("baseline_water")
area_m2 = baseline_water.multiply(ee.Image.pixelArea()).rename("area_m2")

Map = geemap.Map()
Map.add_basemap("HYBRID")
Map.centerObject(roi, 9)
Map.addLayer(occurrence, {"min": 0, "max": 100, "palette": ["ffffff", "0066ff"]}, "JRC water occurrence")
Map.addLayer(seasonality, {"min": 0, "max": 12, "palette": ["f7fbff", "08306b"]}, "JRC seasonality months")
Map.addLayer(transition, {"min": 0, "max": 10, "palette": ["ffffff", "ffeda0", "feb24c", "f03b20"]}, "JRC transition")
Map.addLayer(baseline_water, {"palette": ["00bfff"]}, "Baseline water occurrence >= threshold")
Map.addLayer(roi, {}, "AOI")
Map

summary = area_m2.reduceRegion(
    reducer=ee.Reducer.sum(),
    geometry=roi,
    scale=30,
    maxPixels=1e10,
    bestEffort=True,
)
print("Baseline water area m2:", summary.getInfo())

task = ee.batch.Export.image.toDrive(
    image=baseline_water,
    description=EXPORT_PREFIX,
    folder=DRIVE_FOLDER,
    fileNamePrefix=EXPORT_PREFIX,
    region=roi,
    scale=30,
    maxPixels=1e13,
    fileFormat="GeoTIFF",
)
print("Baseline water raster export prepared; call task.start() if desired:", task.id)
'''


PROFILE_CODE = {
    "s2-ndvi-cloud-score": s2_ndvi_code,
    "s1-flood-area": s1_flood_code,
    "landsat-lst": landsat_lst_code,
    "modis-vi-timeseries": modis_vi_timeseries_code,
    "dynamic-world-area": dynamic_world_area_code,
    "jrc-water-change": jrc_water_change_code,
}


def markdown_cell(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def code_cell(source: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": source.splitlines(keepends=True)}


def build_source(args: argparse.Namespace, bbox: list[float]) -> str:
    profile = PROFILES[args.profile]
    body = PROFILE_CODE[args.profile]().strip()
    header = (
        "#!/usr/bin/env python\n"
        f'"""{profile.title}.\n\n'
        "Generated by EasyGEE scaffold_gee_template.py.\n"
        "Verify dataset catalog pages, AOI, dates, QA, scale, and export params\n"
        "before using outputs for decisions.\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        "import ee\n"
        "import geemap\n\n"
        + constants(args, bbox)
    )
    return header + "\n\n\n" + body + "\n"


def build_notebook(args: argparse.Namespace, bbox: list[float]) -> dict:
    profile = PROFILES[args.profile]
    intro = (
        f"# {profile.title}\n\n"
        f"{profile.description}\n\n"
        "Datasets: " + ", ".join(f"`{dataset}`" for dataset in profile.datasets) + "\n\n"
        "Review focus: " + "; ".join(profile.review_focus) + "\n"
    )
    cells = [
        markdown_cell(intro),
        code_cell("import ee\nimport geemap\n\n" + constants(args, bbox) + "\n"),
        code_cell(PROFILE_CODE[args.profile]().strip() + "\n"),
        markdown_cell(
            "## Limitations and next checks\n\n"
            "- Verify the official Earth Engine Data Catalog pages before final analysis.\n"
            "- Confirm AOI/date choices and task-specific thresholds with visual and numeric probes.\n"
            "- Export tasks are prepared, not started; call `task.start()` only after review.\n"
        ),
    ]
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def list_profiles() -> None:
    for profile in PROFILES.values():
        print(f"{profile.id}: {profile.title}")
        print(f"  datasets: {', '.join(profile.datasets)}")
        print(f"  {profile.description}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path, help="Output .ipynb or .py path")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="s2-ndvi-cloud-score")
    parser.add_argument("--mode", choices=("notebook", "script"), default="notebook")
    parser.add_argument("--project", default="YOUR_EE_PROJECT")
    parser.add_argument("--bbox", nargs=4, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--baseline-start", default="2023-01-01")
    parser.add_argument("--baseline-end", default="2023-12-31")
    parser.add_argument("--scale", type=float, default=10)
    parser.add_argument("--export-prefix", default="gee_template_export")
    parser.add_argument("--drive-folder", default="earthengine_exports")
    parser.add_argument("--list-profiles", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.list_profiles:
        list_profiles()
        return 0
    if args.output is None:
        parser.error("output is required unless --list-profiles is used")

    bbox = parse_bbox(args.bbox)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.mode == "notebook":
        args.output.write_text(json.dumps(build_notebook(args, bbox), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        args.output.write_text(build_source(args, bbox), encoding="utf-8")
    print(f"Wrote {args.mode} template {args.profile}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
