#!/usr/bin/env python
"""Compact agent protocol client for the EasyGEE Map Console.

This script is intentionally small: agents should use it to read workbench
state and enqueue browser-visible actions instead of parsing generated HTML.
It does not read credentials or print Earth Engine tile URLs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import easygee_project
import resolve_ambiguous_geo_request as ambiguous_requests


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SKILL_DIR = Path(__file__).resolve().parents[1]
CONTRACT_PATH = SKILL_DIR / "references" / "map-console-agent-contract.json"


def load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def api_url(base_url: str, path: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path)


def http_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: float = 60) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            parsed = {"ok": False, "error": str(exc)}
        parsed.setdefault("ok", False)
        parsed.setdefault("status", exc.code)
        return parsed
    if not raw:
        return {"ok": True}
    parsed = json.loads(raw.decode("utf-8"))
    if isinstance(parsed, dict):
        return parsed
    return {"ok": True, "data": parsed}


def print_json(payload: dict[str, Any], pretty: bool) -> None:
    payload = sanitize_for_output(payload)
    if pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def sanitize_for_output(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in {"tileurl", "tile_url", "url_format"}:
                safe[key] = "<omitted>"
            else:
                safe[key] = sanitize_for_output(item)
        return safe
    if isinstance(value, list):
        return [sanitize_for_output(item) for item in value]
    return value


def compact_aoi(aoi: Any) -> dict[str, Any] | None:
    if not isinstance(aoi, dict):
        return None
    coordinates = aoi.get("coordinates")
    coordinate_count = len(coordinates) if isinstance(coordinates, list) else 0
    return {
        "type": aoi.get("type"),
        "bounds": aoi.get("bounds"),
        "coordinateCount": coordinate_count,
    }


def compact_recipe(recipe: Any) -> dict[str, Any] | None:
    if not isinstance(recipe, dict):
        return None
    keys = [
        "kind",
        "source",
        "datasetId",
        "band",
        "outputBand",
        "temporalReducer",
        "operation",
        "year",
        "months",
        "startDate",
        "endDate",
        "periodLabel",
        "scaleFactor",
        "offset",
    ]
    return {key: recipe.get(key) for key in keys if recipe.get(key) not in (None, "", [])}


def compact_layer(layer: Any) -> dict[str, Any] | None:
    if not isinstance(layer, dict):
        return None
    summary = layer.get("summary") if isinstance(layer.get("summary"), dict) else {}
    compact: dict[str, Any] = {
        "id": layer.get("id"),
        "name": layer.get("name"),
        "dataset": layer.get("dataset"),
        "type": layer.get("type"),
        "shown": layer.get("shown"),
        "opacity": layer.get("opacity"),
        "styleProfile": layer.get("styleProfile"),
        "stylePreset": layer.get("stylePreset"),
    }
    recipe = compact_recipe(layer.get("recipe"))
    if recipe:
        compact["recipe"] = recipe
    summary_keys = ["startDate", "endDate", "band", "temporalReducer", "periodLabel", "sceneCount", "mean", "count"]
    compact_summary = {key: summary.get(key) for key in summary_keys if summary.get(key) not in (None, "", [])}
    if compact_summary:
        compact["summary"] = compact_summary
    return {key: value for key, value in compact.items() if value is not None}


def compact_task(task: Any) -> dict[str, Any] | None:
    if not isinstance(task, dict):
        return None
    keys = [
        "id",
        "type",
        "analysis",
        "title",
        "name",
        "status",
        "destination",
        "folder",
        "fileNamePrefix",
        "taskId",
        "taskName",
        "createdAt",
        "updatedAt",
    ]
    compact = {key: task.get(key) for key in keys if task.get(key) not in (None, "", [])}
    params = task.get("params") if isinstance(task.get("params"), dict) else {}
    param_keys = ["dataset", "index", "startDate", "endDate", "scale", "fileFormat", "cloudOptimized", "maxPixels"]
    compact_params = {key: params.get(key) for key in param_keys if params.get(key) not in (None, "", [])}
    if compact_params:
        compact["params"] = compact_params
    return compact or None


def compact_selected_dataset(selected: Any) -> dict[str, Any] | None:
    if not isinstance(selected, dict):
        return None
    keys = ["id", "label", "type", "source", "provider", "scale", "dateRange", "hasExplicitAoi", "mapDateRange"]
    compact = {key: selected.get(key) for key in keys if selected.get(key) not in (None, "", [])}
    recipe = compact_recipe(selected.get("defaultRecipe"))
    if recipe:
        compact["defaultRecipe"] = recipe
    return compact


def compact_quota(quota: Any) -> dict[str, Any] | None:
    if not isinstance(quota, dict):
        return None
    keys = ["status", "indicator", "source", "usageSource", "refreshedAt"]
    compact = {key: quota.get(key) for key in keys if quota.get(key) not in (None, "", [])}
    rows = quota.get("rows") if isinstance(quota.get("rows"), list) else []
    warnings = quota.get("warnings") if isinstance(quota.get("warnings"), list) else []
    if rows:
        compact["rowCount"] = len(rows)
        known_usage = sum(1 for row in rows if isinstance(row, dict) and row.get("usageKnown"))
        compact["usageKnownCount"] = known_usage
        warn_count = sum(1 for row in rows if isinstance(row, dict) and row.get("status") == "warn")
        if warn_count:
            compact["warningRowCount"] = warn_count
    if warnings:
        compact["warnings"] = [str(item) for item in warnings[:3]]
    tier = quota.get("tier") if isinstance(quota.get("tier"), dict) else None
    if tier:
        compact["tier"] = {key: tier.get(key) for key in ("name", "kind", "source") if tier.get(key) not in (None, "", [])}
    return compact or None


def compact_state_response(payload: dict[str, Any]) -> dict[str, Any]:
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    layers = [item for item in (compact_layer(layer) for layer in state.get("layers", [])) if item]
    tasks = [item for item in (compact_task(task) for task in state.get("tasks", [])) if item]
    compact_state = {
        "agentProtocolVersion": state.get("agentProtocolVersion"),
        "title": state.get("title"),
        "projectConfigured": easygee_project.is_concrete_project(state.get("project")),
        "projectSource": state.get("projectSource"),
        "center": state.get("center"),
        "zoom": state.get("zoom"),
        "basemap": state.get("basemap"),
        "activeLayerId": state.get("activeLayerId"),
        "bounds": state.get("bounds"),
        "aoiBounds": state.get("aoiBounds"),
        "aoi": compact_aoi(state.get("aoi")),
        "hasExplicitAoi": state.get("hasExplicitAoi"),
        "processingBounds": state.get("processingBounds"),
        "measurementsShown": state.get("measurementsShown"),
        "measurementsOpacity": state.get("measurementsOpacity"),
        "measurementSummary": state.get("measurementSummary"),
        "selectedDataset": compact_selected_dataset(state.get("selectedDataset")),
        "layers": layers,
        "tasks": tasks,
        "quota": compact_quota(state.get("quota")),
        "favoriteDatasetCount": len(state.get("favoriteDatasets", [])) if isinstance(state.get("favoriteDatasets"), list) else 0,
        "visualPreferences": state.get("visualPreferences") if isinstance(state.get("visualPreferences"), dict) else None,
    }
    return {
        "ok": bool(payload.get("ok") and state),
        "syncedAt": payload.get("syncedAt"),
        "state": {key: value for key, value in compact_state.items() if value is not None},
    }


def current_region_from_state(state: dict[str, Any]) -> tuple[dict[str, Any] | None, Any]:
    explicit_aoi = state.get("aoi") if isinstance(state.get("aoi"), dict) else None
    processing_aoi = state.get("processingAoi") if isinstance(state.get("processingAoi"), dict) else None
    aoi = explicit_aoi or processing_aoi
    bounds = None
    if isinstance(explicit_aoi, dict):
        bounds = explicit_aoi.get("bounds")
    if not bounds and isinstance(processing_aoi, dict):
        bounds = processing_aoi.get("bounds")
    if not bounds:
        bounds = state.get("processingBounds") or state.get("bounds")
    return aoi if isinstance(aoi, dict) else None, bounds


def extract_year(text: str, fallback: int | None = None) -> int | None:
    match = re.search(r"(20\d{2}|19\d{2})", text)
    if match:
        return int(match.group(1))
    return fallback


def infer_months(text: str) -> list[int] | None:
    compact = text.replace(" ", "")
    month_range = re.search(r"(?<!\d)(1[0-2]|0?[1-9])(?:月)?[-~至到—]+(1[0-2]|0?[1-9])月?", compact)
    if month_range:
        start = int(month_range.group(1))
        end = int(month_range.group(2))
        if start <= end:
            return list(range(start, end + 1))
    month_values = [int(item) for item in re.findall(r"(?<!\d)(1[0-2]|0?[1-9])月", compact)]
    if len(month_values) > 1:
        return sorted({month for month in month_values if 1 <= month <= 12})
    lowered = text.lower()
    if any(token in lowered for token in ["summer", "growing season"]) or "夏季" in text or "夏天" in text:
        return [6, 7, 8, 9]
    if "春季" in text or "spring" in lowered:
        return [3, 4, 5]
    if "秋季" in text or "autumn" in lowered or "fall" in lowered:
        return [9, 10, 11]
    return None


def infer_reducer(text: str, default: str = "median") -> str:
    lowered = text.lower().replace(" ", "")
    if any(token in lowered for token in ["ndvimax", "max", "maximum", "峰值", "最大"]):
        return "max"
    if any(token in lowered for token in ["mean", "average", "平均"]):
        return "mean"
    if any(token in lowered for token in ["min", "minimum", "最小"]):
        return "min"
    if any(token in lowered for token in ["mode", "众数"]):
        return "mode"
    if any(token in lowered for token in ["median", "中位"]):
        return "median"
    return default


def month_window_dates(year: int, months: list[int]) -> tuple[str, str]:
    start_month = min(months)
    end_month = max(months)
    start_date = f"{year:04d}-{start_month:02d}-01"
    if end_month == 12:
        end_date = f"{year + 1:04d}-01-01"
    else:
        end_date = f"{year:04d}-{end_month + 1:02d}-01"
    return start_date, end_date


def infer_quick_layer(prompt: str, state: dict[str, Any], dataset_override: str | None = None) -> dict[str, Any] | None:
    text = prompt.strip()
    lowered = text.lower()
    selected = state.get("selectedDataset") if isinstance(state.get("selectedDataset"), dict) else {}
    selected_id = str(dataset_override or selected.get("id") or "").strip()
    asks_ndvi = "ndvi" in lowered or "植被指数" in text or "植被" in text
    if not asks_ndvi:
        return None
    year = extract_year(text)
    months = infer_months(text)
    reducer = infer_reducer(text, "median")
    selected_is_modis_vi = selected_id == "MODIS/061/MOD13Q1"
    wants_modis = "modis" in lowered or "mod13" in lowered or selected_is_modis_vi
    wants_10m = any(token in lowered for token in ["10m", "10 m", "sentinel", "sentinel-2", "s2"]) or "哨兵" in text or "10米" in text

    if wants_modis and not wants_10m:
        recipe: dict[str, Any] = {
            "kind": "imageCollection",
            "source": "easygee-quick-layer",
            "datasetId": "MODIS/061/MOD13Q1",
            "band": "NDVI",
            "outputBand": "NDVI",
            "temporalReducer": reducer,
            "scaleFactor": 0.0001,
        }
        if year:
            recipe["year"] = year
        if months:
            recipe["months"] = months
        if year and months:
            start_date, end_date = month_window_dates(year, months)
        else:
            start_date = state.get("startDate")
            end_date = state.get("endDate")
        period = f"{year} months {min(months)}-{max(months)}" if year and months else f"{start_date}..{end_date}"
        name = f"MODIS NDVI {reducer.upper()} {period}".strip()
        recipe["name"] = name
        return {
            "kind": "modis_ndvi",
            "reason": "Matched MODIS vegetation-index NDVI request.",
            "datasetId": "MODIS/061/MOD13Q1",
            "catalogItem": {"id": "MODIS/061/MOD13Q1", "label": "MODIS Vegetation Indices", "type": "image_collection"},
            "recipe": recipe,
            "startDate": start_date,
            "endDate": end_date,
            "name": name,
        }

    if year and months:
        start_date, end_date = month_window_dates(year, months)
    else:
        start_date = state.get("startDate")
        end_date = state.get("endDate")
    period = f"{year} months {min(months)}-{max(months)}" if year and months else f"{start_date}..{end_date}"
    name = f"Sentinel-2 10m NDVI {period}".strip()
    return {
        "kind": "sentinel2_ndvi",
        "reason": "Matched 10 m/Sentinel-2 NDVI request.",
        "datasetId": "EASYGEE/S2_NDVI",
        "catalogItem": {"id": "EASYGEE/S2_NDVI", "label": "Sentinel-2 NDVI", "type": "image_collection"},
        "startDate": start_date,
        "endDate": end_date,
        "name": name,
    }


def wait_for_state(base_url: str, wait_seconds: float, timeout: float) -> dict[str, Any]:
    deadline = time.time() + max(0.0, wait_seconds)
    state_url = api_url(base_url, "/api/session/state")
    last_payload: dict[str, Any] = {"ok": False, "error": "No state has been synced yet."}
    while True:
        payload = http_json("GET", state_url, timeout=timeout)
        last_payload = payload
        state = payload.get("state") if isinstance(payload, dict) else None
        if payload.get("ok") and isinstance(state, dict) and state:
            return payload
        if time.time() >= deadline:
            return last_payload
        time.sleep(0.5)


def state_payload(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    payload = wait_for_state(args.url, args.wait, args.timeout)
    return (0 if payload.get("ok") and payload.get("state") else 2), payload


def substate_payload(args: argparse.Namespace, key: str) -> tuple[int, dict[str, Any]]:
    code, payload = state_payload(args)
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    value = state.get(key)
    ok = code == 0
    return (0 if ok else code), {"ok": ok, key: value, "syncedAt": payload.get("syncedAt")}


def enqueue_action(base_url: str, action: dict[str, Any], timeout: float) -> dict[str, Any]:
    return http_json("POST", api_url(base_url, "/api/session/actions"), {"action": action}, timeout=timeout)


def command_capabilities(args: argparse.Namespace) -> int:
    if args.url:
        payload = http_json("GET", api_url(args.url, "/api/session/capabilities"), timeout=args.timeout)
        if payload.get("ok"):
            print_json(payload, args.pretty)
            return 0
    print_json({"ok": True, "contract": load_contract(), "source": str(CONTRACT_PATH)}, args.pretty)
    return 0


def command_state(args: argparse.Namespace) -> int:
    code, payload = state_payload(args)
    if getattr(args, "compact", False):
        payload = compact_state_response(payload)
    print_json(payload, args.pretty)
    return code


def command_profile(args: argparse.Namespace) -> int:
    payload = http_json("GET", api_url(args.url, "/api/session/profile"), timeout=args.timeout)
    print_json(payload, args.pretty)
    return 0 if payload.get("ok") else 1


def command_aoi(args: argparse.Namespace) -> int:
    code, payload = substate_payload(args, "aoi")
    print_json(payload, args.pretty)
    return code


def command_measurements(args: argparse.Namespace) -> int:
    code, payload = substate_payload(args, "measurements")
    print_json(payload, args.pretty)
    return code


def command_measurement_summary(args: argparse.Namespace) -> int:
    code, payload = substate_payload(args, "measurementSummary")
    print_json(payload, args.pretty)
    return code


def command_tasks(args: argparse.Namespace) -> int:
    code, payload = substate_payload(args, "tasks")
    print_json(payload, args.pretty)
    return code


def command_selected_dataset(args: argparse.Namespace) -> int:
    code, payload = substate_payload(args, "selectedDataset")
    print_json(payload, args.pretty)
    return code


def command_clear_aoi(args: argparse.Namespace) -> int:
    payload = enqueue_action(args.url, {"type": "clearAoi", "source": "map_console_agent"}, args.timeout)
    print_json(payload, args.pretty)
    return 0 if payload.get("ok") else 1


def command_clear_measurements(args: argparse.Namespace) -> int:
    payload = enqueue_action(args.url, {"type": "clearMeasurements", "source": "map_console_agent"}, args.timeout)
    print_json(payload, args.pretty)
    return 0 if payload.get("ok") else 1


def command_remove_layer(args: argparse.Namespace) -> int:
    payload = enqueue_action(
        args.url,
        {"type": "removeLayer", "layerId": args.layer_id, "source": "map_console_agent"},
        args.timeout,
    )
    print_json(payload, args.pretty)
    return 0 if payload.get("ok") else 1


def command_layer_visibility(args: argparse.Namespace) -> int:
    action_type = "showLayer" if args.shown else "hideLayer"
    payload = enqueue_action(
        args.url,
        {
            "type": action_type,
            "layerId": args.layer_id,
            "activate": args.activate,
            "source": "map_console_agent",
        },
        args.timeout,
    )
    print_json(payload, args.pretty)
    return 0 if payload.get("ok") else 1


def command_select_layer(args: argparse.Namespace) -> int:
    payload = enqueue_action(
        args.url,
        {"type": "selectLayer", "layerId": args.layer_id, "source": "map_console_agent"},
        args.timeout,
    )
    print_json(payload, args.pretty)
    return 0 if payload.get("ok") else 1


def command_set_opacity(args: argparse.Namespace) -> int:
    payload = enqueue_action(
        args.url,
        {
            "type": "setLayerOpacity",
            "layerId": args.layer_id,
            "opacity": args.opacity,
            "source": "map_console_agent",
        },
        args.timeout,
    )
    print_json(payload, args.pretty)
    return 0 if payload.get("ok") else 1


def command_style_layer(args: argparse.Namespace) -> int:
    action: dict[str, Any] = {
        "type": "updateLayerStyle",
        "layerId": args.layer_id,
        "source": "map_console_agent",
    }
    if args.preset:
        action["preset"] = args.preset
    if args.color:
        action["style"] = {"color": args.color, "fillColor": args.color}
        if args.layer_id == "__easygee_aoi__":
            action["type"] = "setAoiStyle"
    payload = enqueue_action(args.url, action, args.timeout)
    print_json(payload, args.pretty)
    return 0 if payload.get("ok") else 1


def parse_months_arg(value: str | None) -> list[int] | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if "-" in text and "," not in text:
        start, end = text.split("-", 1)
        try:
            start_i = int(start)
            end_i = int(end)
        except Exception:
            return None
        return [month for month in range(min(start_i, end_i), max(start_i, end_i) + 1) if 1 <= month <= 12]
    months: list[int] = []
    for part in text.replace(";", ",").split(","):
        try:
            month = int(part.strip())
        except Exception:
            continue
        if 1 <= month <= 12 and month not in months:
            months.append(month)
    return months or None


def load_recipe_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    if value == "-":
        payload = json.loads(sys.stdin.read().lstrip("\ufeff"))
    else:
        payload = json.loads(Path(value).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Recipe JSON must be an object.")
    return payload


def command_render_recipe(args: argparse.Namespace) -> int:
    code, state_response = state_payload(args)
    state = state_response.get("state") if isinstance(state_response.get("state"), dict) else {}
    if code != 0:
        print_json({"ok": False, "error": "No synced Map Console state is available.", "stateResponse": state_response}, args.pretty)
        return code
    selected = state.get("selectedDataset") if isinstance(state.get("selectedDataset"), dict) else {}
    dataset_id = args.dataset_id or selected.get("id")
    if not dataset_id:
        print_json({"ok": False, "error": "No dataset id was provided and no selectedDataset is available."}, args.pretty)
        return 2
    aoi, bounds = current_region_from_state(state)
    if not bounds:
        print_json({"ok": False, "error": "No AOI, processing AOI, or map bounds are available in the Map Console state."}, args.pretty)
        return 2
    try:
        recipe = load_recipe_json(args.recipe_json)
    except Exception as exc:
        print_json({"ok": False, "error": str(exc)}, args.pretty)
        return 2
    recipe.setdefault("kind", "imageCollection")
    recipe["datasetId"] = dataset_id
    if args.band:
        recipe["band"] = args.band
    if args.output_band:
        recipe["outputBand"] = args.output_band
    if args.reducer:
        recipe["temporalReducer"] = args.reducer
    if args.year is not None:
        recipe["year"] = args.year
    months = parse_months_arg(args.months)
    if months:
        recipe["months"] = months
    if args.start_date:
        recipe["startDate"] = args.start_date
    if args.end_date:
        recipe["endDate"] = args.end_date
    if args.scale_factor is not None:
        recipe["scaleFactor"] = args.scale_factor
    if args.offset is not None:
        recipe["offset"] = args.offset
    if args.name:
        recipe["name"] = args.name
    project = args.project or state.get("project")
    if not easygee_project.is_concrete_project(project):
        project = None
    request = {
        "project": project,
        "datasetId": dataset_id,
        "catalogItem": selected or {"id": dataset_id},
        "aoi": aoi if isinstance(aoi, dict) else None,
        "bounds": bounds,
        "startDate": args.start_date or state.get("startDate"),
        "endDate": args.end_date or state.get("endDate"),
        "cloudPct": state.get("cloudPct"),
        "recipe": recipe,
    }
    request = {key: value for key, value in request.items() if value is not None}
    layer_response = http_json("POST", api_url(args.url, "/api/layer"), request, timeout=args.timeout)
    result: dict[str, Any] = {"ok": bool(layer_response.get("ok")), "layerResponse": layer_response}
    if layer_response.get("ok") and args.sync and isinstance(layer_response.get("layer"), dict):
        result["action"] = enqueue_action(
            args.url,
            {"type": "addLayer", "layer": layer_response["layer"], "source": "map_console_agent", "recipe": recipe},
            args.timeout,
        )
    print_json(result, args.pretty)
    return 0 if result["ok"] else 1


def visible_layer_label(state: dict[str, Any]) -> str | None:
    layers = state.get("layers")
    if not isinstance(layers, list):
        return None
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        if layer.get("shown") is False:
            continue
        label = layer.get("name") or layer.get("label") or layer.get("id")
        if label:
            return str(label)
    return None


def command_quick_layer(args: argparse.Namespace) -> int:
    code, state_response = state_payload(args)
    state = state_response.get("state") if isinstance(state_response.get("state"), dict) else {}
    if code != 0:
        print_json({"ok": False, "error": "No synced Map Console state is available.", "stateResponse": state_response}, args.pretty)
        return code
    prompt = " ".join(args.task).strip()
    fast_path = infer_quick_layer(prompt, state, args.dataset_id)
    if not fast_path:
        print_json(
            {
                "ok": False,
                "error": "No quick-layer recipe matched this request.",
                "suggestion": "Use render-recipe with explicit dataset, band, reducer, dates, and months.",
            },
            args.pretty,
        )
        return 2
    aoi, bounds = current_region_from_state(state)
    if not bounds:
        print_json({"ok": False, "error": "No AOI, processing AOI, or map bounds are available in the Map Console state."}, args.pretty)
        return 2
    project = args.project or state.get("project")
    if not easygee_project.is_concrete_project(project):
        project = None
    request = {
        "project": project,
        "datasetId": fast_path["datasetId"],
        "catalogItem": fast_path.get("catalogItem"),
        "aoi": aoi,
        "bounds": bounds,
        "startDate": fast_path.get("startDate") or state.get("startDate"),
        "endDate": fast_path.get("endDate") or state.get("endDate"),
        "cloudPct": args.cloud_pct if args.cloud_pct is not None else state.get("cloudPct"),
        "recipe": fast_path.get("recipe"),
        "name": args.name or fast_path.get("name"),
    }
    request = {key: value for key, value in request.items() if value is not None}
    layer_response = http_json("POST", api_url(args.url, "/api/layer"), request, timeout=args.timeout)
    result: dict[str, Any] = {
        "ok": bool(layer_response.get("ok")),
        "fastPath": fast_path,
        "layerResponse": layer_response,
    }
    layer = layer_response.get("layer") if isinstance(layer_response.get("layer"), dict) else None
    if layer_response.get("ok") and args.sync and layer:
        result["action"] = enqueue_action(
            args.url,
            {"type": "addLayer", "layer": layer, "source": "map_console_agent", "fastPath": fast_path},
            args.timeout,
        )
        result["visibilityAction"] = enqueue_action(
            args.url,
            {"type": "showLayer", "layerId": layer.get("id"), "activate": True, "source": "map_console_agent"},
            args.timeout,
        )
        result["selectAction"] = enqueue_action(
            args.url,
            {"type": "selectLayer", "layerId": layer.get("id"), "source": "map_console_agent"},
            args.timeout,
        )
    print_json(result, args.pretty)
    return 0 if result["ok"] else 1


def command_plan(args: argparse.Namespace) -> int:
    context: dict[str, Any] = {
        "has_aoi": bool(args.has_aoi),
        "has_map_state": False,
        "has_active_image": bool(args.has_active_image),
        "active_layer": args.active_layer,
    }
    state_response: dict[str, Any] | None = None
    if args.url:
        code, state_response = state_payload(args)
        state = state_response.get("state") if isinstance(state_response.get("state"), dict) else {}
        context["has_map_state"] = code == 0
        context["has_aoi"] = bool(context["has_aoi"] or isinstance(state.get("aoi"), dict))
        layer_label = args.active_layer or visible_layer_label(state)
        if layer_label:
            context["active_layer"] = layer_label
            context["has_active_image"] = True
    prompt = " ".join(args.task).strip()
    plan = ambiguous_requests.build_plan(prompt, context)
    payload: dict[str, Any] = {"ok": True, "plan": plan}
    if state_response is not None:
        payload["stateSyncedAt"] = state_response.get("syncedAt")
        payload["stateContext"] = context
        state = state_response.get("state") if isinstance(state_response.get("state"), dict) else {}
        quick_layer = infer_quick_layer(prompt, state)
        if quick_layer:
            payload["quickLayer"] = quick_layer
            payload["agentNextAction"] = "quick-layer"
            payload["recommendedCommand"] = "map_console_agent.py quick-layer --url <map-console-url> " + json.dumps(prompt, ensure_ascii=False)
    print_json(payload, args.pretty)
    return 0


def command_extract_ndvi(args: argparse.Namespace) -> int:
    code, state_response = state_payload(args)
    state = state_response.get("state") if isinstance(state_response.get("state"), dict) else {}
    if code != 0:
        print_json({"ok": False, "error": "No synced Map Console state is available.", "stateResponse": state_response}, args.pretty)
        return code
    aoi = state.get("aoi")
    project = args.project or state.get("project")
    if not easygee_project.is_concrete_project(project):
        project = None
    if not isinstance(aoi, dict):
        print_json({"ok": False, "error": "No AOI is available in the Map Console state."}, args.pretty)
        return 2
    request = {
        "project": project,
        "aoi": aoi,
        "bounds": aoi.get("bounds"),
        "startDate": args.start_date or state.get("startDate"),
        "endDate": args.end_date or state.get("endDate"),
        "cloudPct": args.cloud_pct if args.cloud_pct is not None else state.get("cloudPct"),
        "scale": args.scale,
    }
    request = {key: value for key, value in request.items() if value is not None}
    analysis = http_json("POST", api_url(args.url, "/api/analysis/ndvi"), request, timeout=args.timeout)
    result: dict[str, Any] = {"ok": bool(analysis.get("ok")), "analysis": analysis}
    if analysis.get("ok") and args.sync and isinstance(analysis.get("layer"), dict):
        action = {"type": "addLayer", "layer": analysis["layer"], "source": "map_console_agent"}
        result["action"] = enqueue_action(args.url, action, args.timeout)
    print_json(result, args.pretty)
    return 0 if result["ok"] else 1


def command_export_drive(args: argparse.Namespace) -> int:
    if args.analysis != "ndvi":
        print_json({"ok": False, "error": "Only NDVI Drive export is supported by this command today."}, args.pretty)
        return 2
    code, state_response = state_payload(args)
    state = state_response.get("state") if isinstance(state_response.get("state"), dict) else {}
    if code != 0:
        print_json({"ok": False, "error": "No synced Map Console state is available.", "stateResponse": state_response}, args.pretty)
        return code
    aoi = state.get("aoi")
    project = args.project or state.get("project")
    if not easygee_project.is_concrete_project(project):
        project = None
    if not isinstance(aoi, dict):
        print_json({"ok": False, "error": "No explicit AOI is available in the Map Console state. Draw an AOI before Drive export."}, args.pretty)
        return 2
    request = {
        "project": project,
        "aoi": aoi,
        "bounds": aoi.get("bounds"),
        "startDate": args.start_date or state.get("startDate"),
        "endDate": args.end_date or state.get("endDate"),
        "cloudPct": args.cloud_pct if args.cloud_pct is not None else state.get("cloudPct"),
        "scale": args.scale,
        "folder": args.folder,
        "fileNamePrefix": args.file_name_prefix,
        "description": args.description,
        "fileFormat": args.file_format,
        "cloudOptimized": not args.no_cloud_optimized,
        "maxPixels": args.max_pixels,
        "start": not args.prepare_only,
    }
    request = {key: value for key, value in request.items() if value is not None}
    export = http_json("POST", api_url(args.url, "/api/export/ndvi-drive"), request, timeout=args.timeout)
    result: dict[str, Any] = {"ok": bool(export.get("ok")), "export": export}
    task = export.get("task") or export.get("export")
    if export.get("ok") and args.sync and isinstance(task, dict):
        action = {"type": "addTask", "task": task, "source": "map_console_agent"}
        result["action"] = enqueue_action(args.url, action, args.timeout)
    print_json(result, args.pretty)
    return 0 if result["ok"] else 1


def command_enqueue(args: argparse.Namespace) -> int:
    if args.action_json == "-":
        action = json.loads(sys.stdin.read().lstrip("\ufeff"))
    else:
        path = Path(args.action_json)
        action = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(action, dict):
        print_json({"ok": False, "error": "Action JSON must be an object."}, args.pretty)
        return 2
    payload = enqueue_action(args.url, action, args.timeout)
    print_json(payload, args.pretty)
    return 0 if payload.get("ok") else 1


def command_smoke(args: argparse.Namespace) -> int:
    contract = load_contract()
    vague_plan = ambiguous_requests.build_plan("提取这个AOI中的水体", {"has_aoi": True})
    modis_fast = infer_quick_layer("MODIS 2024 5-9月 NDVImax", {"selectedDataset": {}})
    s2_fast = infer_quick_layer("2024 年夏季 10m NDVI", {"selectedDataset": {}})
    supported_actions = set(contract.get("actions", {}).get("supported", []))
    checks = {
        "contractVersion": contract.get("version") == 2,
        "stateEndpoint": contract.get("stateEndpoint") == "/api/session/state",
        "profileEndpoint": contract.get("profileEndpoint") == "/api/session/profile",
        "actionsEndpoint": contract.get("actionsEndpoint") == "/api/session/actions",
        "layerEndpoint": contract.get("layerEndpoint") == "/api/layer",
        "ndviEndpoint": contract.get("analysisEndpoints", {}).get("ndvi") == "/api/analysis/ndvi",
        "ndviDriveExportEndpoint": contract.get("exportEndpoints", {}).get("ndviDrive") == "/api/export/ndvi-drive",
        "selectedDataset": "selectedDataset" in contract.get("stateFields", []),
        "tasksState": "tasks" in contract.get("stateFields", []),
        "recipeState": "recipe" in contract.get("layerFields", []),
        "styleActions": {"removeLayer", "updateLayerStyle", "setAoiStyle"}.issubset(supported_actions),
        "layerControlActions": {"showLayer", "hideLayer", "selectLayer", "setLayerVisibility", "setLayerOpacity"}.issubset(supported_actions),
        "recipeActions": {"selectDataset", "addLayer"}.issubset(supported_actions),
        "taskActions": {"addTask", "exportNdviDrive"}.issubset(supported_actions),
        "driveShortcut": contract.get("driveShortcut", {}).get("elementId") == "drive-btn",
        "modisFastPath": isinstance(modis_fast, dict)
        and modis_fast.get("datasetId") == "MODIS/061/MOD13Q1"
        and modis_fast.get("recipe", {}).get("temporalReducer") == "max",
        "s2FastPath": isinstance(s2_fast, dict)
        and s2_fast.get("datasetId") == "EASYGEE/S2_NDVI"
        and s2_fast.get("startDate") == "2024-06-01",
        "ambiguousPlanner": vague_plan.get("recommended_route") == "ask_user",
        "apiUrl": api_url("http://127.0.0.1:5000/map.html", "/api/session/state")
        == "http://127.0.0.1:5000/api/session/state",
    }
    ok = all(checks.values())
    print_json({"ok": ok, "checks": checks}, args.pretty)
    return 0 if ok else 1


def add_url_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", required=True, help="Map Console URL, for example http://127.0.0.1:50165/index.html")
    parser.add_argument("--wait", type=float, default=0.0, help="Seconds to wait for the browser to sync state.")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capabilities = subparsers.add_parser("capabilities", help="Print the compact agent contract.")
    capabilities.add_argument("--url", help="Optional Map Console URL; uses local contract if unavailable.")
    capabilities.add_argument("--timeout", type=float, default=10.0)
    capabilities.add_argument("--pretty", action="store_true")
    capabilities.set_defaults(func=command_capabilities)

    state = subparsers.add_parser("state", help="Read the latest synced Map Console state.")
    add_url_args(state)
    state.add_argument("--compact", action="store_true", help="Print a small agent-oriented state summary.")
    state.set_defaults(func=command_state)

    profile = subparsers.add_parser("profile", help="Read the persistent Map Console profile.")
    profile.add_argument("--url", required=True)
    profile.add_argument("--timeout", type=float, default=30.0)
    profile.add_argument("--pretty", action="store_true")
    profile.set_defaults(func=command_profile)

    aoi = subparsers.add_parser("aoi", help="Read the latest synced AOI.")
    add_url_args(aoi)
    aoi.set_defaults(func=command_aoi)

    measurements = subparsers.add_parser("measurements", help="Read saved distance measurements.")
    add_url_args(measurements)
    measurements.set_defaults(func=command_measurements)

    summary = subparsers.add_parser("measurement-summary", help="Read distance measurement summary.")
    add_url_args(summary)
    summary.set_defaults(func=command_measurement_summary)

    tasks = subparsers.add_parser("tasks", help="Read recent background tasks and Drive exports.")
    add_url_args(tasks)
    tasks.set_defaults(func=command_tasks)

    selected_dataset = subparsers.add_parser("selected-dataset", help="Read the selected dataset context.")
    add_url_args(selected_dataset)
    selected_dataset.set_defaults(func=command_selected_dataset)

    clear_aoi = subparsers.add_parser("clear-aoi", help="Clear the current AOI from the Map Console.")
    add_url_args(clear_aoi)
    clear_aoi.set_defaults(func=command_clear_aoi)

    clear_measurements = subparsers.add_parser("clear-measurements", help="Clear saved distance measurements from the Map Console.")
    add_url_args(clear_measurements)
    clear_measurements.set_defaults(func=command_clear_measurements)

    remove_layer = subparsers.add_parser("remove-layer", help="Remove a layer from the Map Console layer stack.")
    add_url_args(remove_layer)
    remove_layer.add_argument("--layer-id", required=True)
    remove_layer.set_defaults(func=command_remove_layer)

    show_layer = subparsers.add_parser("show-layer", help="Show a layer and optionally make it active.")
    add_url_args(show_layer)
    show_layer.add_argument("--layer-id", required=True)
    show_layer.add_argument("--no-activate", dest="activate", action="store_false", help="Do not make the layer active.")
    show_layer.set_defaults(func=command_layer_visibility, shown=True, activate=True)

    hide_layer = subparsers.add_parser("hide-layer", help="Hide a layer without removing it.")
    add_url_args(hide_layer)
    hide_layer.add_argument("--layer-id", required=True)
    hide_layer.add_argument("--no-activate", dest="activate", action="store_false", help="Do not change the active layer.")
    hide_layer.set_defaults(func=command_layer_visibility, shown=False, activate=True)

    select_layer = subparsers.add_parser("select-layer", help="Set the active layer in the Map Console inspector.")
    add_url_args(select_layer)
    select_layer.add_argument("--layer-id", required=True)
    select_layer.set_defaults(func=command_select_layer)

    set_opacity = subparsers.add_parser("set-opacity", help="Set layer opacity through the Map Console.")
    add_url_args(set_opacity)
    set_opacity.add_argument("--layer-id", required=True)
    set_opacity.add_argument("--opacity", type=float, required=True, help="Opacity from 0 to 1.")
    set_opacity.set_defaults(func=command_set_opacity)

    style_layer = subparsers.add_parser("style-layer", help="Apply a style preset or AOI color through the Map Console.")
    add_url_args(style_layer)
    style_layer.add_argument("--layer-id", required=True, help="Layer id, or __easygee_aoi__ for the AOI system layer.")
    style_layer.add_argument("--preset", help="Visualization preset id, such as deep-blue or natural-green.")
    style_layer.add_argument("--color", help="AOI hex color, such as #1d4ed8.")
    style_layer.set_defaults(func=command_style_layer)

    render_recipe = subparsers.add_parser("render-recipe", help="Render an ImageCollection recipe and optionally sync it to the browser.")
    add_url_args(render_recipe)
    render_recipe.add_argument("--project", help="Override the project from Map Console state.")
    render_recipe.add_argument("--dataset-id", help="Dataset id; defaults to selectedDataset.id.")
    render_recipe.add_argument("--recipe-json", help="Path to recipe JSON, or '-' for stdin.")
    render_recipe.add_argument("--band", help="Band/index to select, for example NDVI.")
    render_recipe.add_argument("--output-band", help="Output band name.")
    render_recipe.add_argument("--reducer", choices=["median", "mean", "max", "min", "mode", "mosaic"], help="Temporal reducer.")
    render_recipe.add_argument("--year", type=int, help="Calendar year for seasonal recipes.")
    render_recipe.add_argument("--months", help="Month list or range, for example 5-9 or 5,6,7,8,9.")
    render_recipe.add_argument("--start-date", help="Override recipe start date.")
    render_recipe.add_argument("--end-date", help="Override recipe end date.")
    render_recipe.add_argument("--scale-factor", type=float, help="Scale factor applied per image before reducing.")
    render_recipe.add_argument("--offset", type=float, help="Offset applied per image before reducing.")
    render_recipe.add_argument("--name", help="Layer name.")
    render_recipe.add_argument("--no-sync", dest="sync", action="store_false", help="Do not enqueue the returned layer for the browser.")
    render_recipe.set_defaults(func=command_render_recipe, sync=True)

    quick_layer = subparsers.add_parser("quick-layer", help="Render a common request such as Sentinel-2 NDVI or MODIS NDVImax using a fast path.")
    add_url_args(quick_layer)
    quick_layer.add_argument("task", nargs="+", help="User request text, for example '2024 summer 10m NDVI'.")
    quick_layer.add_argument("--project", help="Override the project from Map Console state.")
    quick_layer.add_argument("--dataset-id", help="Force a dataset id, for example MODIS/061/MOD13Q1.")
    quick_layer.add_argument("--name", help="Override the generated layer name.")
    quick_layer.add_argument("--cloud-pct", type=float, help="Override Sentinel-2 CLOUDY_PIXEL_PERCENTAGE threshold.")
    quick_layer.add_argument("--no-sync", dest="sync", action="store_false", help="Do not enqueue the returned layer for the browser.")
    quick_layer.set_defaults(func=command_quick_layer, sync=True)

    plan = subparsers.add_parser("plan", help="Resolve a vague extraction request against current Map Console context.")
    plan.add_argument("task", nargs="+", help="User request text, for example '提取这个AOI中的水体'.")
    plan.add_argument("--url", help="Optional Map Console URL used to read AOI/layer state.")
    plan.add_argument("--wait", type=float, default=0.0, help="Seconds to wait for browser state when --url is used.")
    plan.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds.")
    plan.add_argument("--has-aoi", action="store_true", help="Treat the current session as having a usable AOI.")
    plan.add_argument("--has-active-image", action="store_true", help="Treat the current browser image/layer as a valid visual input.")
    plan.add_argument("--active-layer", help="Human-readable active layer name.")
    plan.add_argument("--pretty", action="store_true")
    plan.set_defaults(func=command_plan)

    ndvi = subparsers.add_parser("extract-ndvi", help="Run NDVI analysis and optionally sync the layer to the browser.")
    add_url_args(ndvi)
    ndvi.add_argument("--project", help="Override the project from Map Console state.")
    ndvi.add_argument("--start-date", help="Override start date.")
    ndvi.add_argument("--end-date", help="Override end date.")
    ndvi.add_argument("--cloud-pct", type=float, help="Override Sentinel-2 CLOUDY_PIXEL_PERCENTAGE threshold.")
    ndvi.add_argument("--scale", type=float, default=10.0)
    ndvi.add_argument("--no-sync", dest="sync", action="store_false", help="Do not enqueue the returned layer for the browser.")
    ndvi.set_defaults(func=command_extract_ndvi, sync=True)

    export_drive = subparsers.add_parser("export-drive", help="Start a background Earth Engine export to Google Drive and sync a task card.")
    add_url_args(export_drive)
    export_drive.add_argument("--analysis", choices=["ndvi"], default="ndvi", help="Analysis/export type.")
    export_drive.add_argument("--project", help="Override the project from Map Console state.")
    export_drive.add_argument("--start-date", help="Override start date.")
    export_drive.add_argument("--end-date", help="Override end date.")
    export_drive.add_argument("--cloud-pct", type=float, help="Override Sentinel-2 CLOUDY_PIXEL_PERCENTAGE threshold.")
    export_drive.add_argument("--scale", type=float, default=10.0, help="Export scale in meters.")
    export_drive.add_argument("--folder", default="EasyGEE", help="Google Drive folder name.")
    export_drive.add_argument("--file-name-prefix", help="Google Drive fileNamePrefix.")
    export_drive.add_argument("--description", help="Earth Engine task description.")
    export_drive.add_argument("--file-format", default="GeoTIFF", help="Earth Engine export file format.")
    export_drive.add_argument("--max-pixels", type=int, default=1_000_000_000)
    export_drive.add_argument("--no-cloud-optimized", action="store_true", help="Do not request cloud-optimized GeoTIFF output.")
    export_drive.add_argument("--prepare-only", action="store_true", help="Create the export task without starting it.")
    export_drive.add_argument("--no-sync", dest="sync", action="store_false", help="Do not enqueue the task card for the browser.")
    export_drive.set_defaults(func=command_export_drive, sync=True)

    enqueue = subparsers.add_parser("enqueue", help="Post a browser action JSON object.")
    enqueue.add_argument("--url", required=True)
    enqueue.add_argument("--action-json", required=True, help="Path to action JSON, or '-' for stdin.")
    enqueue.add_argument("--timeout", type=float, default=30.0)
    enqueue.add_argument("--pretty", action="store_true")
    enqueue.set_defaults(func=command_enqueue)

    smoke = subparsers.add_parser("smoke", help="Run offline self-checks.")
    smoke.add_argument("--pretty", action="store_true")
    smoke.set_defaults(func=command_smoke)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
