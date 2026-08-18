import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "easygee" / "scripts"


def _load(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


interaction = _load("route_easygee_interaction")
resolver = _load("resolve_ambiguous_geo_request")
exporter = _load("plan_gee_export")


DALAT_PROMPT = (
    "从 GEE 获取达拉特光伏基地近期清晰影像，用多模态视觉提取所有可见光伏场区边界，"
    "并导出带 CRS 的 GeoPackage。中心约为 109.671°E、40.295°N。"
)


def test_dalat_short_prompt_routes_end_to_end() -> None:
    interaction_plan = interaction.route(DALAT_PROMPT)
    assert interaction_plan.mode == "mixed"
    assert "aoi_needed" not in interaction_plan.artifacts
    assert {"source_imagery", "visual_annotations", "vector_file", "qa_preview"}.issubset(interaction_plan.artifacts)

    resolved = resolver.build_plan(DALAT_PROMPT)
    assert resolved["intent"]["target"] == "photovoltaic"
    assert resolved["intent"]["mentions_location_seed"] is True
    assert resolved["recommended_route"] == "multimodal_geo_vector"
    assert resolved["clarifying_questions"] == []
    assert resolved["agent_next_action"] == "execute_hybrid_multimodal_vector_workflow"

    export = exporter.build_plan(DALAT_PROMPT)
    assert export.data_kind == "vector"
    assert export.destination == "local"
    assert export.format == "GeoPackage"
    assert export.route == "local_geopackage_vector_export"
    assert not any(question["id"] == "export_destination" for question in export.clarifying_questions)


def test_common_visible_targets_are_recognized() -> None:
    cases = {
        "用多模态视觉识别车辆并导出 GeoJSON": "vehicle",
        "用多模态视觉勾画所有树冠并导出带 CRS 的矢量": "tree_crown",
        "用多模态视觉提取田块边界并导出 GeoPackage": "field_parcel",
        "用多模态视觉识别船舶并导出 GeoJSON": "vessel",
    }
    for prompt, expected in cases.items():
        plan = resolver.build_plan(prompt, {"has_aoi": True, "has_active_image": True})
        assert plan["intent"]["target"] == expected
        assert plan["recommended_route"] == "multimodal_geo_vector"
