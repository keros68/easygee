#!/usr/bin/env python
"""Resolve vague geospatial extraction prompts into EasyGEE action plans.

The resolver is deliberately offline. It does not contact Earth Engine, inspect
credentials, or decide that an analytical result is correct. Its job is to help
an agent choose between existing GEE products, reproducible remote-sensing
processing, and current-image visual recognition before doing work.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ROUTE_LABELS = {
    "gee_product": "Use an existing GEE/catalog product",
    "gee_remote_sensing": "Derive the target from remote-sensing data",
    "current_image_vision": "Recognize objects from the currently visible image",
    "ask_user": "Ask a clarifying question first",
}

WATER_WORDS = (
    "water",
    "surface water",
    "flood",
    "inundation",
    "lake",
    "river",
    "wetland",
    "ndwi",
    "mndwi",
    "水体",
    "水域",
    "水面",
    "洪水",
    "淹没",
    "积水",
    "湖泊",
    "河流",
    "湿地",
)
FLOOD_WORDS = ("flood", "inundation", "storm", "洪水", "淹没", "积水", "内涝", "暴雨")
HISTORICAL_WATER_WORDS = (
    "permanent",
    "seasonal",
    "history",
    "historical",
    "occurrence",
    "baseline",
    "长期",
    "多年",
    "常年",
    "季节性",
    "历史",
    "水频率",
    "基准",
)
CURRENT_WORDS = (
    "current",
    "recent",
    "today",
    "now",
    "this image",
    "this scene",
    "当前",
    "近期",
    "现在",
    "最近",
    "今年",
    "这个影像",
    "这张影像",
    "这一景",
)
ROOF_WORDS = ("roof", "rooftop", "roofs", "屋顶", "房顶", "楼顶")
BUILDING_WORDS = (
    "building",
    "buildings",
    "footprint",
    "built-up",
    "house",
    "houses",
    "建筑",
    "建筑物",
    "房屋",
    "楼宇",
    "建成区",
)
CURRENT_IMAGE_WORDS = (
    "this image",
    "current image",
    "satellite image",
    "this scene",
    "screen",
    "visible",
    "影像",
    "这张图",
    "当前图",
    "当前影像",
    "这个影像",
    "屏幕",
    "可见",
)
AOI_WORDS = ("aoi", "roi", "area", "polygon", "区域", "范围", "这个区域", "多边形", "矩形")
EXTRACT_WORDS = ("extract", "detect", "segment", "mask", "classify", "提取", "识别", "分割", "检测", "圈出")


@dataclass(frozen=True)
class CandidateRoute:
    route: str
    label: str
    confidence: str
    when_to_use: str
    datasets: tuple[str, ...]
    outputs: tuple[str, ...]
    limitations: tuple[str, ...]
    next_steps: tuple[str, ...]


@dataclass(frozen=True)
class QuestionOption:
    id: str
    label: str
    description: str
    route: str


@dataclass(frozen=True)
class ClarifyingQuestion:
    id: str
    question: str
    options: tuple[QuestionOption, ...]


def norm(text: str) -> str:
    return text.casefold()


def has_any(text: str, words: tuple[str, ...]) -> bool:
    folded = norm(text)
    return any(word.casefold() in folded for word in words)


def load_context(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    if path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path).read_text(encoding="utf-8-sig")
    loaded = json.loads(raw)
    return loaded if isinstance(loaded, dict) else {}


def infer_intent(prompt: str) -> dict[str, Any]:
    target = "unknown"
    if has_any(prompt, WATER_WORDS):
        target = "water"
    if has_any(prompt, ROOF_WORDS):
        target = "rooftop"
    elif target == "unknown" and has_any(prompt, BUILDING_WORDS):
        target = "building"

    return {
        "target": target,
        "is_extraction": has_any(prompt, EXTRACT_WORDS) or target != "unknown",
        "mentions_aoi": has_any(prompt, AOI_WORDS),
        "mentions_current_image": has_any(prompt, CURRENT_IMAGE_WORDS),
        "mentions_flood": has_any(prompt, FLOOD_WORDS),
        "mentions_historical": has_any(prompt, HISTORICAL_WATER_WORDS),
        "mentions_current": has_any(prompt, CURRENT_WORDS),
    }


def water_routes(intent: dict[str, Any]) -> list[CandidateRoute]:
    product_confidence = "high" if intent["mentions_historical"] else "medium"
    optical_confidence = "high" if intent["mentions_current"] and not intent["mentions_flood"] else "medium"
    sar_confidence = "high" if intent["mentions_flood"] else "medium"
    return [
        CandidateRoute(
            route="gee_product",
            label="JRC/Dynamic World water product",
            confidence=product_confidence,
            when_to_use="Use this for permanent, seasonal, or baseline water, or as a quick explainable first pass.",
            datasets=("JRC/GSW1_4/GlobalSurfaceWater", "GOOGLE/DYNAMICWORLD/V1"),
            outputs=("water mask layer", "area summary table", "occurrence/probability layer"),
            limitations=(
                "JRC is historical context, not a live flood detector.",
                "Dynamic World is a land-cover probability product and still needs date filtering and QA.",
            ),
            next_steps=(
                "Read the AOI from Map Console state.",
                "Choose occurrence/probability threshold and date semantics.",
                "Sync the resulting water mask as a normal map layer.",
            ),
        ),
        CandidateRoute(
            route="gee_remote_sensing",
            label="Sentinel/Landsat water index or Sentinel-1 flood workflow",
            confidence="high" if intent["mentions_flood"] or intent["mentions_current"] else optical_confidence,
            when_to_use="Use this for current water, event water, or when the user gives a date/scene.",
            datasets=(
                "COPERNICUS/S2_SR_HARMONIZED + GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED",
                "LANDSAT/*/C02/T1_L2",
                "COPERNICUS/S1_GRD",
            ),
            outputs=("index/probability layer", "binary water mask", "area statistics", "optional raster/table export"),
            limitations=(
                "Optical water masks can confuse cloud shadow, terrain shadow, dark roofs, and turbid water.",
                "SAR flood masks need speckle handling and local threshold validation.",
            ),
            next_steps=(
                "Ask or infer date range and cloud tolerance.",
                "Add a visual QA layer before the final mask.",
                "Summarize area with pixelArea at an explicit scale.",
            ),
        ),
        CandidateRoute(
            route="current_image_vision",
            label="Visible-image water annotation",
            confidence="low",
            when_to_use="Use only when the user means the currently rendered image and accepts visual annotation rather than a reproducible GEE product.",
            datasets=("current browser screenshot or active layer render",),
            outputs=("screen-space annotation", "approximate vector mask if georeferencing is available"),
            limitations=(
                "The result follows what is visible on screen, not necessarily the source pixels.",
                "It needs visual QA and should not replace a reproducible GEE mask when analysis/export matters.",
            ),
            next_steps=(
                "Capture the current map image and georeference/viewport metadata.",
                "Ask whether approximate visible-object annotation is acceptable.",
            ),
        ),
    ]


def building_routes(intent: dict[str, Any]) -> list[CandidateRoute]:
    current_image_confidence = "high" if intent["mentions_current_image"] and intent["target"] == "rooftop" else "medium"
    return [
        CandidateRoute(
            route="current_image_vision",
            label="Current-image rooftop or object recognition",
            confidence=current_image_confidence,
            when_to_use="Use when the user says the target is in the current image or wants screen-visible rooftops/objects.",
            datasets=("current browser screenshot or active layer render", "optional high-resolution source layer metadata"),
            outputs=("annotated polygons", "count/area estimate", "QA overlay"),
            limitations=(
                "This is visual recognition over the rendered image unless tied back to source imagery.",
                "It is appropriate for inspection/annotation, not a catalog-scale reproducible extraction by itself.",
            ),
            next_steps=(
                "Read current viewport, active layer, and AOI if present.",
                "Ask whether the desired output is footprint, roof surface/material, or visible annotation.",
                "Sync accepted polygons back through the Map Console layer stack.",
            ),
        ),
        CandidateRoute(
            route="gee_product",
            label="Existing building or built-up products",
            confidence="medium",
            when_to_use="Use for building footprints or built-up exposure where product coverage and resolution fit the AOI.",
            datasets=(
                "GOOGLE/Research/open-buildings/v3/polygons",
                "GOOGLE/DYNAMICWORLD/V1 built probability",
                "ESA/WorldCover built-up class",
            ),
            outputs=("building footprint layer where covered", "built-up mask", "area/count summary"),
            limitations=(
                "Open Buildings coverage must be verified for the AOI; it is not a universal rooftop layer.",
                "10 m land-cover products can show built-up area but cannot reliably extract individual roofs.",
            ),
            next_steps=(
                "Verify catalog coverage for the AOI before presenting footprints.",
                "Use built-up products only when individual roof boundaries are not required.",
            ),
        ),
        CandidateRoute(
            route="gee_remote_sensing",
            label="Custom segmentation/classification from imagery",
            confidence="low",
            when_to_use="Use when the target is a custom roof/building class and training data or high-resolution imagery is available.",
            datasets=("user-provided imagery or labels", "Sentinel/Landsat only for coarse built-up context"),
            outputs=("classified raster", "vectorized candidates", "validation table"),
            limitations=(
                "Sentinel-2/Landsat are usually too coarse for individual rooftop extraction.",
                "A custom classifier needs labels and validation before analytical use.",
            ),
            next_steps=(
                "Clarify source imagery and target resolution.",
                "Collect labels or accept a visual annotation workflow.",
            ),
        ),
    ]


def generic_routes(intent: dict[str, Any]) -> list[CandidateRoute]:
    return [
        CandidateRoute(
            route="gee_product",
            label="Search for an existing class/product",
            confidence="medium",
            when_to_use="Use when the requested target has a known catalog class or curated product.",
            datasets=("search_gee_dataset.py candidates", "official Earth Engine catalog entries"),
            outputs=("product layer", "zonal summary", "export-ready mask/table"),
            limitations=("Catalog classes may not match the user's wording or local semantics.",),
            next_steps=("Run search_gee_dataset.py for candidate products.", "Verify catalog scale, date range, bands, and QA."),
        ),
        CandidateRoute(
            route="gee_remote_sensing",
            label="Derive the target from remote-sensing features",
            confidence="medium",
            when_to_use="Use when the target can be expressed through spectral/SAR/terrain features or supervised labels.",
            datasets=("sensor-matched ImageCollection", "training or reference data when classification is needed"),
            outputs=("mask/classification layer", "statistics", "exports"),
            limitations=("Needs method choices, thresholds, labels, and validation.",),
            next_steps=("Clarify target definition, dates, scale, and acceptable validation.",),
        ),
        CandidateRoute(
            route="current_image_vision",
            label="Recognize the target from the current image",
            confidence="medium" if intent["mentions_current_image"] else "low",
            when_to_use="Use when the task is about what is visually present in the active map image.",
            datasets=("current browser screenshot or active layer render",),
            outputs=("annotation overlay", "approximate object list or polygons"),
            limitations=("Screen-visible recognition is not automatically reproducible over other dates or AOIs.",),
            next_steps=("Read current map state and ask the user to accept visual recognition if analysis rigor matters.",),
        ),
    ]


def build_questions(intent: dict[str, Any], context: dict[str, Any]) -> list[ClarifyingQuestion]:
    questions: list[ClarifyingQuestion] = []
    target = intent["target"]
    has_aoi = bool(context.get("has_aoi"))

    if target == "unknown":
        questions.append(
            ClarifyingQuestion(
                id="target_definition",
                question="你想从 AOI 或当前影像中提取哪一类对象/现象？",
                options=(
                    QuestionOption("catalog_class", "现成类别/产品", "先找 GEE 目录里是否已有对应类别。", "gee_product"),
                    QuestionOption("custom_rs", "遥感算法/分类", "用指数、阈值、分类器或训练样本做可复现处理。", "gee_remote_sensing"),
                    QuestionOption("visible_object", "当前影像可见对象", "把当前屏幕/影像当作视觉识别输入做近似标注。", "current_image_vision"),
                ),
            )
        )
    elif target == "water" and not (intent["mentions_historical"] or intent["mentions_current"] or intent["mentions_flood"]):
        questions.append(
            ClarifyingQuestion(
                id="water_semantics",
                question="这里的“水体”更接近哪一种？",
                options=(
                    QuestionOption("baseline_water", "长期/常年水体", "优先用 JRC Global Surface Water 或 Dynamic World 做可解释基线。", "gee_product"),
                    QuestionOption("current_water", "近期/当前水体", "优先用 Sentinel-2/Landsat 水体指数并做云影 QA。", "gee_remote_sensing"),
                    QuestionOption("flood_water", "洪水/积水范围", "优先考虑 Sentinel-1 SAR 或事件前后对比。", "gee_remote_sensing"),
                ),
            )
        )
    elif target in {"rooftop", "building"}:
        questions.append(
            ClarifyingQuestion(
                id="building_output",
                question="你要的“屋顶/建筑”输出是哪一种？",
                options=(
                    QuestionOption("visible_roofs", "当前影像里的可见屋顶", "用当前影像视觉识别，产出近似标注或多边形。", "current_image_vision"),
                    QuestionOption("building_footprints", "建筑物轮廓", "优先查现成建筑矢量/建成区产品并验证 AOI 覆盖。", "gee_product"),
                    QuestionOption("roof_surface_or_material", "屋顶表面/材质", "需要明确影像来源、分辨率和训练/验证方式。", "gee_remote_sensing"),
                ),
            )
        )

    if intent["mentions_aoi"] and not has_aoi:
        questions.append(
            ClarifyingQuestion(
                id="aoi_missing",
                question="我还没有可用 AOI。你希望我怎么取得范围？",
                options=(
                    QuestionOption("use_drawn_aoi", "使用已绘制 AOI", "先读取 Map Console 的 AOI；没有就请你画一个。", "ask_user"),
                    QuestionOption("use_visible_extent", "使用当前视野", "把浏览器当前地图范围作为临时 AOI。", "ask_user"),
                    QuestionOption("provide_geometry", "提供几何/资产", "用你给的 GeoJSON、坐标或 EE 资产作为 AOI。", "ask_user"),
                ),
            )
        )

    return questions


def choose_route(intent: dict[str, Any], questions: list[ClarifyingQuestion]) -> str:
    if questions:
        return "ask_user"
    if intent["target"] == "water":
        if intent["mentions_historical"]:
            return "gee_product"
        return "gee_remote_sensing"
    if intent["target"] in {"rooftop", "building"}:
        if intent["mentions_current_image"]:
            return "current_image_vision"
        return "gee_product"
    if intent["mentions_current_image"]:
        return "current_image_vision"
    return "gee_product"


def candidate_routes(intent: dict[str, Any]) -> list[CandidateRoute]:
    if intent["target"] == "water":
        return water_routes(intent)
    if intent["target"] in {"rooftop", "building"}:
        return building_routes(intent)
    return generic_routes(intent)


def read_references(intent: dict[str, Any]) -> list[str]:
    refs = ["references/task-patterns.md", "references/dataset-qa-patterns.md", "references/browser-preview.md"]
    if intent["target"] in {"rooftop", "building"}:
        refs.append("references/gee-agent-playbook.md")
    return refs


def build_plan(prompt: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = dict(context or {})
    intent = infer_intent(prompt)
    questions = build_questions(intent, context)
    route = choose_route(intent, questions)
    mode = "clarify" if route == "ask_user" else "ready"
    if intent["mentions_current_image"] and not (context.get("has_active_image") or context.get("active_layer")):
        if route == "current_image_vision":
            mode = "needs_context"

    plan = {
        "ok": True,
        "prompt": prompt,
        "mode": mode,
        "intent": intent,
        "context": {
            "has_aoi": bool(context.get("has_aoi")),
            "has_map_state": bool(context.get("has_map_state")),
            "has_active_image": bool(context.get("has_active_image")),
            "active_layer": context.get("active_layer"),
        },
        "recommended_route": route,
        "recommended_label": ROUTE_LABELS[route],
        "candidate_routes": [asdict(item) for item in candidate_routes(intent)],
        "clarifying_questions": [asdict(question) for question in questions],
        "clarification_policy": "Ask one multiple-choice question at a time. Put the recommended option first and continue only after the user's choice changes the route.",
        "agent_next_action": "ask_user" if route == "ask_user" else "execute_background_workflow",
        "read": read_references(intent),
        "map_console": {
            "prefer_agent_protocol": True,
            "state_commands": ("map_console_agent.py state", "map_console_agent.py aoi", "map_console_agent.py profile"),
            "result_sync": "Sync result as ordinary layers, vectors, or task-log entries. Do not add task-specific toolbar buttons.",
        },
    }
    if mode == "needs_context":
        plan["agent_next_action"] = "read_current_map_or_image_state"
        plan["context_gap"] = "The prompt refers to the current image, but no active image/layer context was provided."
    return plan


def print_text(plan: dict[str, Any]) -> None:
    print(f"mode: {plan['mode']}")
    print(f"target: {plan['intent']['target']}")
    print(f"recommended_route: {plan['recommended_route']} - {plan['recommended_label']}")
    if plan.get("context_gap"):
        print(f"context_gap: {plan['context_gap']}")
    questions = plan.get("clarifying_questions", [])
    if questions:
        first = questions[0]
        print(f"ask: {first['question']}")
        for option in first["options"]:
            print(f"  - {option['id']}: {option['label']} ({option['route']})")
    print("candidates:")
    for item in plan["candidate_routes"]:
        print(f"  - {item['route']}: {item['label']} [{item['confidence']}]")
        print(f"    datasets: {', '.join(item['datasets'])}")


def run_smoke() -> int:
    cases = [
        ("提取这个AOI中的水体", {"has_aoi": True}, "water", "ask_user", "water_semantics"),
        ("提取这个AOI里的长期水体", {"has_aoi": True}, "water", "gee_product", None),
        ("提取这个影像里的屋顶", {"has_active_image": True, "active_layer": "visible satellite image"}, "rooftop", "ask_user", "building_output"),
        ("extract flood water in this AOI after the storm", {"has_aoi": True}, "water", "gee_remote_sensing", None),
    ]
    for prompt, context, target, route, question_id in cases:
        plan = build_plan(prompt, context)
        assert plan["ok"], prompt
        assert plan["intent"]["target"] == target, plan
        assert plan["recommended_route"] == route, plan
        question_ids = {item["id"] for item in plan["clarifying_questions"]}
        if question_id:
            assert question_id in question_ids, plan
    print(f"resolve_ambiguous_geo_request smoke passed: {len(cases)} cases")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", nargs="*", help="User request text")
    parser.add_argument("--context-json", help="JSON object with has_aoi, has_map_state, has_active_image, and active_layer.")
    parser.add_argument("--has-aoi", action="store_true", help="The Map Console has a usable AOI.")
    parser.add_argument("--has-map-state", action="store_true", help="A Map Console state snapshot is available.")
    parser.add_argument("--has-active-image", action="store_true", help="The browser has a current image/layer suitable for visual recognition.")
    parser.add_argument("--active-layer", help="Human-readable active layer name.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    parser.add_argument("--smoke", action="store_true", help="Run offline self-checks.")
    args = parser.parse_args()

    if args.smoke:
        return run_smoke()

    prompt = " ".join(args.task).strip()
    if not prompt:
        parser.error("provide task text")
    context = load_context(args.context_json)
    if args.has_aoi:
        context["has_aoi"] = True
    if args.has_map_state:
        context["has_map_state"] = True
    if args.has_active_image:
        context["has_active_image"] = True
    if args.active_layer:
        context["active_layer"] = args.active_layer

    plan = build_plan(prompt, context)
    if args.json or args.pretty:
        print(json.dumps(plan, ensure_ascii=False, indent=2 if args.pretty else None))
    else:
        print_text(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
