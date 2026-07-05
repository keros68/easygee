#!/usr/bin/env python
"""Create reproducible Earth Engine/geemap notebook or script scaffolds."""

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path


DEFAULT_BBOX = [119.8, 30.0, 120.5, 30.5]


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


def csv_list(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("comma-separated list cannot be empty")
    return items


def py(value: object) -> str:
    return repr(value)


def markdown_cell(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def code_cell(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def notebook_document(args: argparse.Namespace, bbox: list[float]) -> dict:
    title = f"# {args.title}\n"
    cells = [
        markdown_cell(
            title
            + "\n"
            + "Generated scaffold for a reproducible Earth Engine/geemap workflow. "
            + "Authenticate deliberately if credentials are missing; do not store tokens in this notebook.\n"
        ),
        code_cell(
            textwrap.dedent(
                f"""
                import ee
                import geemap

                PROJECT = {py(args.project)}
                ee.Initialize(project=PROJECT)
                """
            ).strip()
            + "\n"
        ),
        code_cell(
            textwrap.dedent(
                f"""
                DATASET = {py(args.dataset)}
                START_DATE = {py(args.start)}
                END_DATE = {py(args.end)}
                RGB_BANDS = {py(args.rgb_bands)}
                INDEX_NAME = {py(args.index)}
                INDEX_BANDS = {py(args.index_bands)}
                SCALE = {args.scale}
                CLOUD_FIELD = {py(args.cloud_field)}
                CLOUD_THRESHOLD = {args.cloud_threshold}
                USE_S2_CLOUD_SCORE = {py(args.use_s2_cloud_score)}
                S2_CLOUD_SCORE_COLLECTION = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"
                S2_CLOUD_SCORE_BAND = {py(args.s2_cloud_score_band)}
                S2_CLEAR_THRESHOLD = {args.s2_clear_threshold}
                EXPORT_PREFIX = {py(args.export_prefix)}
                DRIVE_FOLDER = {py(args.drive_folder)}

                roi = ee.Geometry.Rectangle({py(bbox)}, proj="EPSG:4326", geodesic=False)
                """
            ).strip()
            + "\n"
        ),
        code_cell(collection_code().strip() + "\n"),
        code_cell(map_code().strip() + "\n"),
        code_cell(probe_code().strip() + "\n"),
        code_cell(export_code(start_immediately=False).strip() + "\n"),
        markdown_cell(
            "## Provenance and limits\n\n"
            f"- Dataset id: `{args.dataset}`\n"
            f"- Date range: `{args.start}` to `{args.end}`\n"
            f"- AOI bbox: `{bbox}`\n"
            "- Validate QA/cloud masking, projection alignment, scale, nodata behavior, and quota before using outputs for decisions.\n"
        ),
    ]
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def collection_code() -> str:
    return textwrap.dedent(
        """
        def is_sentinel2_sr():
            return DATASET == "COPERNICUS/S2_SR_HARMONIZED"


        def mask_s2_clear(image):
            return image.updateMask(image.select(S2_CLOUD_SCORE_BAND).gte(S2_CLEAR_THRESHOLD))


        def apply_dataset_quality(collection):
            if is_sentinel2_sr() and USE_S2_CLOUD_SCORE:
                cloud_score = ee.ImageCollection(S2_CLOUD_SCORE_COLLECTION)
                return collection.linkCollection(cloud_score, [S2_CLOUD_SCORE_BAND]).map(mask_s2_clear)
            return collection


        def filtered_collection():
            collection = (
                ee.ImageCollection(DATASET)
                .filterBounds(roi)
                .filterDate(START_DATE, END_DATE)
            )
            if CLOUD_FIELD:
                collection = collection.filter(ee.Filter.lt(CLOUD_FIELD, CLOUD_THRESHOLD))
            return apply_dataset_quality(collection)


        def add_index(image):
            if INDEX_NAME.lower() == "none":
                return image
            return image.addBands(
                image.normalizedDifference(INDEX_BANDS).rename(INDEX_NAME)
            )


        collection = filtered_collection()
        composite = collection.median().clip(roi)
        composite = add_index(composite)
        target = composite.select(INDEX_NAME) if INDEX_NAME.lower() != "none" else composite
        """
    )


def map_code() -> str:
    return textwrap.dedent(
        """
        Map = geemap.Map()
        Map.add_basemap("HYBRID")
        Map.centerObject(roi, 10)

        Map.addLayer(
            composite,
            {"bands": RGB_BANDS, "min": 0, "max": 3000, "gamma": 1.1},
            f"{DATASET} RGB composite",
            shown=True,
            opacity=0.85,
        )

        if INDEX_NAME.lower() != "none":
            Map.addLayer(
                target,
                {
                    "min": -0.2,
                    "max": 0.8,
                    "palette": ["8c510a", "f7f7f7", "1a9850"],
                },
                f"{INDEX_NAME} composite",
            )

        Map
        """
    )


def probe_code() -> str:
    return textwrap.dedent(
        """
        print("Collection size:", collection.size().getInfo())
        print("Composite bands:", composite.bandNames().getInfo())
        print("Target projection:", target.projection().getInfo())

        stats = target.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=roi,
            scale=SCALE,
            maxPixels=1e9,
            bestEffort=True,
        )
        print("Mean over AOI:", stats.getInfo())
        """
    )


def export_code(start_immediately: bool) -> str:
    start_line = "task.start()" if start_immediately else "# task.start()"
    note = (
        "Export task started:"
        if start_immediately
        else "Export task prepared. Inspect parameters, then uncomment task.start() when ready:"
    )
    return textwrap.dedent(
        f"""
        task = ee.batch.Export.image.toDrive(
            image=target.clip(roi),
            description=EXPORT_PREFIX,
            folder=DRIVE_FOLDER,
            fileNamePrefix=EXPORT_PREFIX,
            region=roi,
            scale=SCALE,
            maxPixels=1e13,
            fileFormat="GeoTIFF",
            formatOptions={{"cloudOptimized": True}},
        )
        {start_line}
        print({py(note)}, task.id)
        """
    )


def script_document(args: argparse.Namespace, bbox: list[float]) -> str:
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env python
        \"\"\"Headless Earth Engine workflow scaffold generated for {args.title}.\"\"\"

        from __future__ import annotations

        import argparse
        import ee


        PROJECT = {py(args.project)}
        DATASET = {py(args.dataset)}
        START_DATE = {py(args.start)}
        END_DATE = {py(args.end)}
        RGB_BANDS = {py(args.rgb_bands)}
        INDEX_NAME = {py(args.index)}
        INDEX_BANDS = {py(args.index_bands)}
        SCALE = {py(args.scale)}
        CLOUD_FIELD = {py(args.cloud_field)}
        CLOUD_THRESHOLD = {py(args.cloud_threshold)}
        USE_S2_CLOUD_SCORE = {py(args.use_s2_cloud_score)}
        S2_CLOUD_SCORE_COLLECTION = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"
        S2_CLOUD_SCORE_BAND = {py(args.s2_cloud_score_band)}
        S2_CLEAR_THRESHOLD = {py(args.s2_clear_threshold)}
        EXPORT_PREFIX = {py(args.export_prefix)}
        DRIVE_FOLDER = {py(args.drive_folder)}
        BBOX = {py(bbox)}


        def is_sentinel2_sr():
            return DATASET == "COPERNICUS/S2_SR_HARMONIZED"


        def mask_s2_clear(image):
            return image.updateMask(image.select(S2_CLOUD_SCORE_BAND).gte(S2_CLEAR_THRESHOLD))


        def apply_dataset_quality(collection):
            if is_sentinel2_sr() and USE_S2_CLOUD_SCORE:
                cloud_score = ee.ImageCollection(S2_CLOUD_SCORE_COLLECTION)
                return collection.linkCollection(cloud_score, [S2_CLOUD_SCORE_BAND]).map(mask_s2_clear)
            return collection


        def filtered_collection(roi):
            collection = (
                ee.ImageCollection(DATASET)
                .filterBounds(roi)
                .filterDate(START_DATE, END_DATE)
            )
            if CLOUD_FIELD:
                collection = collection.filter(ee.Filter.lt(CLOUD_FIELD, CLOUD_THRESHOLD))
            return apply_dataset_quality(collection)


        def add_index(image):
            if INDEX_NAME.lower() == "none":
                return image
            return image.addBands(
                image.normalizedDifference(INDEX_BANDS).rename(INDEX_NAME)
            )


        def build_workflow(roi):
            collection = filtered_collection(roi)
            composite = collection.median().clip(roi)
            composite = add_index(composite)
            target = composite.select(INDEX_NAME) if INDEX_NAME.lower() != "none" else composite
            return collection, composite, target


        def print_small_probes(collection, composite, target, roi):
            print("Dataset:", DATASET)
            print("Date range:", START_DATE, END_DATE)
            print("AOI bbox:", BBOX)
            print("Collection size:", collection.size().getInfo())
            print("Composite bands:", composite.bandNames().getInfo())
            print("Target projection:", target.projection().getInfo())
            stats = target.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=roi,
                scale=SCALE,
                maxPixels=1e9,
                bestEffort=True,
            )
            print("Mean over AOI:", stats.getInfo())


        def build_export_task(target, roi):
            return ee.batch.Export.image.toDrive(
                image=target.clip(roi),
                description=EXPORT_PREFIX,
                folder=DRIVE_FOLDER,
                fileNamePrefix=EXPORT_PREFIX,
                region=roi,
                scale=SCALE,
                maxPixels=1e13,
                fileFormat="GeoTIFF",
                formatOptions={{"cloudOptimized": True}},
            )


        def main() -> int:
            parser = argparse.ArgumentParser(description=__doc__)
            parser.add_argument("--project", default=PROJECT, help="Earth Engine / Google Cloud project id")
            parser.add_argument("--start-export", action="store_true", help="Start the Drive export after reviewing it")
            args = parser.parse_args()

            ee.Initialize(project=args.project)
            roi = ee.Geometry.Rectangle(BBOX, proj="EPSG:4326", geodesic=False)
            collection, composite, target = build_workflow(roi)
            print_small_probes(collection, composite, target, roi)

            task = build_export_task(target, roi)
            if args.start_export:
                task.start()
                print("Export task started:", task.id)
            else:
                print("Export task prepared:", task.id)
                print("Run again with --start-export after reviewing destination, scale, region, and quota.")
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        """
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Output .ipynb or .py path")
    parser.add_argument("--mode", choices=["notebook", "script"], default="notebook")
    parser.add_argument("--title", default="GEE geemap workflow")
    parser.add_argument("--project", default="YOUR_EE_PROJECT")
    parser.add_argument("--dataset", default="COPERNICUS/S2_SR_HARMONIZED")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--bbox", nargs=4, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--rgb-bands", type=csv_list, default=csv_list("B4,B3,B2"))
    parser.add_argument("--index", default="NDVI")
    parser.add_argument("--index-bands", type=csv_list, default=csv_list("B8,B4"))
    parser.add_argument("--scale", type=float, default=10)
    parser.add_argument("--cloud-field", default="CLOUDY_PIXEL_PERCENTAGE")
    parser.add_argument("--cloud-threshold", type=float, default=20)
    parser.add_argument(
        "--no-s2-cloud-score",
        dest="use_s2_cloud_score",
        action="store_false",
        help="Disable default Cloud Score+ masking for COPERNICUS/S2_SR_HARMONIZED",
    )
    parser.set_defaults(use_s2_cloud_score=True)
    parser.add_argument("--s2-cloud-score-band", choices=["cs", "cs_cdf"], default="cs_cdf")
    parser.add_argument("--s2-clear-threshold", type=float, default=0.60)
    parser.add_argument("--export-prefix", default="gee_geemap_export")
    parser.add_argument("--drive-folder", default="earthengine_exports")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    bbox = parse_bbox(args.bbox)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.mode == "notebook":
        document = notebook_document(args, bbox)
        args.output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        args.output.write_text(script_document(args, bbox), encoding="utf-8")
    print(f"Wrote {args.mode} scaffold: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
