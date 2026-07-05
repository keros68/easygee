#!/usr/bin/env python
"""Run deterministic checks for the EasyGEE evaluation prompts."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class EvalCase:
    id: str
    prompt: str
    plan_ids: tuple[str, ...] = ()
    choose_ids: tuple[str, ...] = ()
    dataset_ids: tuple[str, ...] = ()


@dataclass
class EvalResult:
    id: str
    status: str
    checks: dict[str, bool]
    details: dict[str, list[str]]


CASES = [
    EvalCase(
        id="s2-ndvi-notebook",
        prompt="Build a geemap notebook to map 2024 Sentinel-2 NDVI for an AOI I will draw, show RGB and NDVI layers, and prepare a GeoTIFF export.",
        plan_ids=("vegetation-index",),
        choose_ids=("draw-aoi", "export-image"),
        dataset_ids=("COPERNICUS/S2_SR_HARMONIZED", "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"),
    ),
    EvalCase(
        id="flood-area-by-watershed",
        prompt="Estimate flood water area by watershed after a storm, preferably in a notebook where I can inspect the mask and export a CSV.",
        plan_ids=("water-flood", "zonal-statistics"),
        choose_ids=("zonal-stats", "export-vector"),
        dataset_ids=("COPERNICUS/S1_GRD",),
    ),
    EvalCase(
        id="land-cover-classification",
        prompt="Create a land-cover classification workflow with Sentinel or Landsat imagery and training polygons, then report accuracy.",
        plan_ids=("classification",),
        dataset_ids=("GOOGLE/DYNAMICWORLD/V1", "ESA/WorldCover/v200"),
    ),
    EvalCase(
        id="modis-vegetation-time-series",
        prompt="Extract a monthly or 16-day vegetation time series for multiple polygons and export the result for plotting.",
        plan_ids=("vegetation-index", "time-series", "zonal-statistics"),
        choose_ids=("export-vector", "zonal-stats"),
        dataset_ids=("MODIS/061/MOD13Q1",),
    ),
    EvalCase(
        id="js-to-python-migration",
        prompt="Convert this Earth Engine JavaScript project into a Python geemap notebook and make sure it can run outside the Code Editor.",
        choose_ids=("conversion",),
    ),
    EvalCase(
        id="communication-map",
        prompt="Make a polished interactive map showing before and after urban expansion and share it as HTML or PNG.",
        plan_ids=("change-detection",),
        choose_ids=("interactive-map", "map-export"),
    ),
    EvalCase(
        id="local-boundary-file",
        prompt="Use my local shapefile of field boundaries to summarize mean NDVI and export a table.",
        plan_ids=("vegetation-index", "zonal-statistics"),
        choose_ids=("local-vector", "zonal-stats", "export-vector"),
        dataset_ids=("COPERNICUS/S2_SR_HARMONIZED",),
    ),
    EvalCase(
        id="dataset-discovery-exposure",
        prompt="I need the best GEE dataset for mapping population exposure to flood-prone areas and want a short notebook starter.",
        plan_ids=("water-flood", "population-exposure"),
        choose_ids=("catalog-search",),
        dataset_ids=("COPERNICUS/S1_GRD", "WorldPop/GP/100m/pop"),
    ),
]


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts" / name), *args],
        cwd=str(ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def ids_from_json_process(process: subprocess.CompletedProcess[str], key: str | None = None) -> list[str]:
    if process.returncode != 0:
        return []
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        return []
    items = payload.get(key, []) if key else payload
    if not isinstance(items, list):
        return []
    ids: list[str] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.append(item["id"])
    return ids


def run_case(case: EvalCase) -> EvalResult:
    details: dict[str, list[str]] = {}
    checks: dict[str, bool] = {}

    if case.plan_ids:
        process = run_script("plan_gee_task.py", case.prompt, "--json", "--limit", "5")
        found = ids_from_json_process(process)
        details["plan_ids"] = found
        checks["plan"] = all(expected in found for expected in case.plan_ids)

    if case.choose_ids:
        process = run_script("choose_geemap_tool.py", case.prompt, "--json", "--limit", "5")
        found = ids_from_json_process(process)
        details["choose_ids"] = found
        checks["choose"] = all(expected in found for expected in case.choose_ids)

    if case.dataset_ids:
        process = run_script("search_gee_dataset.py", case.prompt, "--json", "--limit", "7")
        found = ids_from_json_process(process, key="candidates")
        details["dataset_ids"] = found
        checks["datasets"] = all(expected in found for expected in case.dataset_ids)

    status = "ok" if checks and all(checks.values()) else "fail"
    return EvalResult(id=case.id, status=status, checks=checks, details=details)


def print_text(results: list[EvalResult]) -> None:
    detail_keys = {"plan": "plan_ids", "choose": "choose_ids", "datasets": "dataset_ids"}
    for result in results:
        prefix = "OK" if result.status == "ok" else "FAIL"
        print(f"[{prefix}] {result.id}")
        for name, ok in result.checks.items():
            values = result.details.get(detail_keys.get(name, name), [])
            print(f"  {name}: {'ok' if ok else 'fail'} ({', '.join(values)})")
    ok_count = sum(1 for result in results if result.status == "ok")
    print(f"Summary: {ok_count}/{len(results)} evaluation prompts passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results = [run_case(case) for case in CASES]
    if args.json:
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    else:
        print_text(results)
    return 1 if any(result.status != "ok" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
