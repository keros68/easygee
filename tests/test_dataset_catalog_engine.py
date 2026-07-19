from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "skills" / "easygee" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from dataset_catalog_engine import compare_datasets, recommend_datasets, search_catalog  # noqa: E402


def record(
    dataset_id: str,
    label: str,
    *,
    tags: str = "",
    category: str = "",
    source: str = "official",
    deprecated: bool = False,
    kind: str = "image_collection",
) -> dict[str, object]:
    return {
        "id": dataset_id,
        "label": label,
        "tags": tags,
        "description": f"{label} {tags}",
        "provider": "fixture provider",
        "type": kind,
        "category": category,
        "source": source,
        "deprecated": deprecated,
        "url": f"https://example.test/{dataset_id}",
    }


CATALOG = [
    record("COPERNICUS/DEM/GLO30_2024_1", "Copernicus DEM GLO-30 Global 30m Digital Elevation Model", tags="elevation terrain dem", category="elevation-topography"),
    record("COPERNICUS/DEM/GLO30", "Copernicus DEM GLO-30", tags="elevation terrain dem", category="elevation-topography", deprecated=True),
    record("users/example/community_dem", "Community DEM 12m", tags="elevation terrain dem", category="elevation-topography", source="community"),
    record("NASA/SMAP/SPL4SMGP/008", "SMAP L4 Global 3-hourly Soil Moisture", tags="soil moisture root zone", category="climate"),
    record("COPERNICUS/S1_GRD", "Sentinel-1 SAR GRD", tags="radar flood water", category="satellite-imagery"),
    record("JRC/GSW1_4/GlobalSurfaceWater", "JRC Global Surface Water", tags="water occurrence historical", category="surface-ground-water", kind="image"),
    record("NASA/GPM_L3/IMERG_V07", "GPM Global Precipitation", tags="rain rainfall precipitation", category="precipitation"),
    record("WorldPop/GP/100m/pop", "WorldPop Population 100m", tags="population exposure", category="population"),
    record("GOOGLE/Research/open-buildings/v3/polygons", "Open Buildings V3", tags="buildings exposure", category="population", kind="table"),
]


class DatasetCatalogEngineTests(unittest.TestCase):
    def test_dem_prefers_current_official_product(self) -> None:
        result = search_catalog(CATALOG, "DEM", limit=3)
        self.assertEqual(result["candidates"][0]["id"], "COPERNICUS/DEM/GLO30_2024_1")
        self.assertFalse(any(candidate["deprecated"] for candidate in result["candidates"]))

    def test_chinese_soil_moisture_query(self) -> None:
        result = search_catalog(CATALOG, "土壤湿度", limit=3)
        self.assertEqual(result["candidates"][0]["id"], "NASA/SMAP/SPL4SMGP/008")
        self.assertIn("soil-moisture", result["detected_concepts"])

    def test_flood_risk_returns_role_based_bundle(self) -> None:
        result = recommend_datasets(CATALOG, "山区洪水风险评估", limit_per_role=1)
        self.assertEqual(result["recipe"], "flood-risk")
        self.assertTrue({"event_hazard", "terrain", "forcing", "exposure"}.issubset(result["roles"]))
        self.assertTrue(all(result["roles"][role] for role in ("event_hazard", "terrain", "forcing", "exposure")))

    def test_irrelevant_query_has_no_generic_fallback(self) -> None:
        result = search_catalog(CATALOG, "xyzzqv unknown widget", limit=5)
        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["needs_clarification"])

    def test_source_filter_and_comparison(self) -> None:
        result = search_catalog(CATALOG, "DEM", filters={"source": "community"})
        self.assertTrue(result["candidates"])
        self.assertTrue(all(candidate["source"] == "community" for candidate in result["candidates"]))
        comparison = compare_datasets(CATALOG, ["COPERNICUS/DEM/GLO30_2024_1", "MISSING/ASSET"])
        self.assertEqual(len(comparison["datasets"]), 1)
        self.assertEqual(comparison["missing"], ["MISSING/ASSET"])


if __name__ == "__main__":
    unittest.main()
