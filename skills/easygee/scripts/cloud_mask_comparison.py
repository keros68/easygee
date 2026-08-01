#!/usr/bin/env python3
"""Build a visual and numeric comparison of common Sentinel-2 cloud masks.

The case uses one cloudy Sentinel-2 overpass from the public s2cloudless
tutorial area near Portland, Oregon. It creates a local HTML comparison page
with Earth Engine tiles and a small JSON summary. No export task is started.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

import ee

try:
    from cloud_mask_workflows import (
        S2_SR_ID,
        add_s2_cloud_probability,
        mask_s2_cloud_probability_shadow,
        mask_s2_cloud_score_plus,
        mask_s2_qa60,
        mask_s2_scl,
    )
    from easygee_project import resolve_project
except ImportError:  # pragma: no cover - useful when imported as a package
    from skills.easygee.scripts.cloud_mask_workflows import (
        S2_SR_ID,
        add_s2_cloud_probability,
        mask_s2_cloud_probability_shadow,
        mask_s2_cloud_score_plus,
        mask_s2_qa60,
        mask_s2_scl,
    )
    from skills.easygee.scripts.easygee_project import resolve_project


IMAGE_INDEX = "20200601T185919_20200601T190551_T10TER"
CENTER = [-122.269, 45.701]
START = "2020-06-01"
END = "2020-06-02"
RGB_VIS = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}
DEFAULT_OUTPUT = Path("D:/Scratch/easygee-cloud-mask-comparison/cloud-mask-comparison.html")


def _clear_band(masked_image: ee.Image) -> ee.Image:
    """Return a small 0/1 clear-pixel image from the B4 mask."""

    return masked_image.select("B4").mask().unmask(0).rename("clear")


def _append_band(image: ee.Image, band: ee.Image, name: str) -> ee.Image:
    if image is None:
        return band.rename(name)
    return image.addBands(band.rename(name))


def _tile_url(image: ee.Image, vis_params: dict[str, Any], roi: ee.Geometry) -> str:
    """Return a short-lived Earth Engine tile template for the local preview."""

    map_id = image.clip(roi).getMapId(vis_params)
    return map_id["tile_fetcher"].url_format


def _build_case() -> dict[str, Any]:
    roi = ee.Geometry.Point(CENTER).buffer(5_000)
    source = (
        ee.ImageCollection(S2_SR_ID)
        .filterBounds(roi)
        .filterDate(START, END)
        .filter(ee.Filter.eq("system:index", IMAGE_INDEX))
        .first()
    )

    source_collection = ee.ImageCollection.fromImages([source])
    probability_image = add_s2_cloud_probability(source_collection).first()

    masked_images = {
        "qa60": mask_s2_qa60(source),
        "scl": mask_s2_scl(source),
        "cloud_probability": mask_s2_cloud_probability_shadow(
            probability_image,
            threshold=40.0,
            nir_dark_threshold=0.15,
            shadow_distance_km=1.0,
            buffer_m=50.0,
        ),
        "cloud_score_plus": mask_s2_cloud_score_plus(
            source_collection, 0.60
        ).first(),
    }
    clear_bands: dict[str, ee.Image] = {
        name: _clear_band(image) for name, image in masked_images.items()
    }

    metric_image: ee.Image | None = None
    for name, band in clear_bands.items():
        metric_image = _append_band(metric_image, band, name)
    metrics = metric_image.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=roi,
        scale=10,
        maxPixels=1e8,
    ).getInfo()

    cloud_score_clear = clear_bands["cloud_score_plus"]
    agreement_image: ee.Image | None = None
    for name, band in clear_bands.items():
        if name == "cloud_score_plus":
            continue
        agreement_image = _append_band(
            agreement_image,
            band.eq(cloud_score_clear),
            f"{name}_vs_cloud_score_plus",
        )
    agreements = agreement_image.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=roi,
        scale=10,
        maxPixels=1e8,
    ).getInfo()

    disagreement = (
        clear_bands["qa60"].neq(cloud_score_clear)
        .Or(clear_bands["scl"].neq(cloud_score_clear))
        .Or(clear_bands["cloud_probability"].neq(cloud_score_clear))
        .selfMask()
        .rename("disagreement")
    )

    scene_metadata = source.toDictionary(
        ["system:index", "CLOUDY_PIXEL_PERCENTAGE", "MGRS_TILE"]
    ).getInfo()
    return {
        "roi": roi,
        "source": source,
        "masked_images": masked_images,
        "disagreement": disagreement,
        "metrics": metrics,
        "agreements": agreements,
        "scene_metadata": scene_metadata,
    }


def _summary_rows(case: dict[str, Any]) -> list[dict[str, Any]]:
    labels = {
        "qa60": ("QA60", "bits 10/11; no dedicated shadow mask"),
        "scl": ("SCL", "Sen2Cor scene classes; removes cloud shadow/cirrus"),
        "cloud_probability": ("s2cloudless", "probability < 40 + 云影投影"),
        "cloud_score_plus": ("Cloud Score+", "cs_cdf >= 0.60"),
    }
    rows = []
    for key, (label, note) in labels.items():
        clear = float(case["metrics"].get(key, 0.0))
        rows.append(
            {
                "key": key,
                "label": label,
                "note": note,
                "clear_fraction": clear,
                "masked_fraction": 1.0 - clear,
                "agreement_with_cloud_score_plus": (
                    1.0
                    if key == "cloud_score_plus"
                    else float(case["agreements"].get(f"{key}_vs_cloud_score_plus", 0.0))
                ),
            }
        )
    return rows


def _table_html(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(row['label'])}</td>"
            f"<td>{row['clear_fraction'] * 100:.1f}%</td>"
            f"<td>{row['masked_fraction'] * 100:.1f}%</td>"
            f"<td>{row['agreement_with_cloud_score_plus'] * 100:.1f}%</td>"
            f"<td>{html.escape(row['note'])}</td>"
            "</tr>"
        )
    return "".join(body)


def _make_html(case: dict[str, Any], output: Path) -> dict[str, Any]:
    roi = case["roi"]
    tiles = {
        "raw": _tile_url(case["source"], RGB_VIS, roi),
        "qa60": _tile_url(case["masked_images"]["qa60"], RGB_VIS, roi),
        "scl": _tile_url(case["masked_images"]["scl"], RGB_VIS, roi),
        "cloud_probability": _tile_url(
            case["masked_images"]["cloud_probability"], RGB_VIS, roi
        ),
        "cloud_score_plus": _tile_url(
            case["masked_images"]["cloud_score_plus"], RGB_VIS, roi
        ),
        "disagreement": _tile_url(
            case["disagreement"],
            {"min": 1, "max": 1, "palette": ["ffcc00"]},
            roi,
        ),
    }
    rows = _summary_rows(case)
    metadata = case["scene_metadata"]
    panels = [
        ("panel-raw", "原始真彩色", "同一景，未去云", "raw"),
        ("panel-qa60", "QA60", "位元云/卷云掩膜", "qa60"),
        ("panel-scl", "SCL", "Sen2Cor 场景分类", "scl"),
        ("panel-prob", "s2cloudless", "概率 < 40 + 云影投影", "cloud_probability"),
        ("panel-cs", "Cloud Score+", "cs_cdf ≥ 0.60", "cloud_score_plus"),
        ("panel-diff", "差异图", "黄色 = 与 Cloud Score+ 不一致", "disagreement"),
    ]
    panel_html = "".join(
        f'<section class="panel"><h2>{title}</h2><p>{subtitle}</p><div id="{panel_id}" class="map"></div></section>'
        for panel_id, title, subtitle, _ in panels
    )
    panel_data = [
        {"id": panel_id, "tile": tiles[tile_key], "title": title}
        for panel_id, title, _, tile_key in panels
    ]
    summary_json = {
        "case": "Sentinel-2 cloud-mask comparison",
        "dataset": S2_SR_ID,
        "image_index": IMAGE_INDEX,
        "date": START,
        "center": CENTER,
        "scene_metadata": metadata,
        "rows": rows,
    }
    payload = json.dumps(summary_json, ensure_ascii=False, indent=2)
    panels_json = json.dumps(panel_data, ensure_ascii=False)
    center_json = json.dumps([CENTER[1], CENTER[0]])
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EasyGEE Sentinel-2 去云算法对比案例</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    :root {{ color-scheme: light; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f3f6f8; color: #1f2933; }}
    header {{ padding: 22px 28px 12px; background: #0f766e; color: white; }}
    header h1 {{ margin: 0 0 6px; font-size: 24px; }}
    header p {{ margin: 0; opacity: .9; }}
    main {{ max-width: 1500px; margin: 0 auto; padding: 18px 22px 32px; }}
    .callout {{ background: white; border-left: 5px solid #0f766e; padding: 12px 16px; margin-bottom: 16px; box-shadow: 0 1px 3px #0001; }}
    .grid {{ display: grid; grid-template-columns: repeat(3, minmax(260px, 1fr)); gap: 14px; }}
    .panel {{ background: white; padding: 10px 10px 12px; box-shadow: 0 1px 3px #0001; }}
    .panel h2 {{ margin: 0; font-size: 17px; }}
    .panel p {{ margin: 3px 0 8px; color: #52606d; font-size: 13px; }}
    .map {{ height: 300px; border: 1px solid #d9e2ec; }}
    table {{ border-collapse: collapse; width: 100%; background: white; margin-top: 18px; box-shadow: 0 1px 3px #0001; }}
    th, td {{ border-bottom: 1px solid #e4e7eb; padding: 9px 10px; text-align: left; font-size: 13px; }}
    th {{ background: #e8f5f2; }}
    .foot {{ color: #52606d; font-size: 12px; margin-top: 14px; }}
    @media (max-width: 980px) {{ .grid {{ grid-template-columns: repeat(2, minmax(260px, 1fr)); }} }}
    @media (max-width: 650px) {{ .grid {{ grid-template-columns: 1fr; }} main {{ padding: 12px; }} }}
  </style>
</head>
<body>
  <header><h1>EasyGEE：Sentinel-2 常见去云算法对比</h1>
    <p>同一景影像、同一 AOI、同一真彩色参数；黄色差异图用于定位算法分歧。</p>
  </header>
  <main>
    <div class="callout">
      <strong>案例设置：</strong> {html.escape(str(metadata.get('system:index', IMAGE_INDEX)))}，日期 {START}，场景云量元数据 {float(metadata.get('CLOUDY_PIXEL_PERCENTAGE', 0)):.1f}%。
      云概率阈值为 40，Cloud Score+ 使用 <code>cs_cdf ≥ 0.60</code>。这里只比较“掩膜”，没有做云下影像重建。
    </div>
    <div class="grid">{panel_html}</div>
    <table>
      <thead><tr><th>算法</th><th>保留清晰像元</th><th>掩膜像元</th><th>与 Cloud Score+ 一致率</th><th>教学提示</th></tr></thead>
      <tbody>{_table_html(rows)}</tbody>
    </table>
    <p class="foot">数据：{S2_SR_ID}；Cloud Score+ 和 s2cloudless 与源影像按 system:index 对齐。地图瓦片为临时 Earth Engine 预览，不是导出结果。</p>
  </main>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const center = {center_json};
    const panels = {panels_json};
    panels.forEach((panel) => {{
      const map = L.map(panel.id, {{ zoomControl: false, scrollWheelZoom: false }}).setView(center, 12);
      L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
        maxZoom: 19, attribution: '&copy; OpenStreetMap contributors', opacity: 0.55
      }}).addTo(map);
      L.tileLayer(panel.tile, {{ opacity: 0.96, attribution: 'Google Earth Engine' }}).addTo(map);
      L.control.scale({{ imperial: false }}).addTo(map);
    }});
  </script>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")
    output.with_suffix(".json").write_text(payload, encoding="utf-8")
    return summary_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Earth Engine / Google Cloud project id")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    resolved = resolve_project(args.project)
    if not resolved.project or resolved.project == "YOUR_EE_PROJECT":
        parser.error("No Earth Engine project was found; pass --project PROJECT_ID")
    ee.Initialize(project=resolved.project)
    case = _build_case()
    summary = _make_html(case, args.output)
    print(json.dumps({
        "output": str(args.output),
        "summary": str(args.output.with_suffix('.json')),
        "project_source": resolved.source,
        "image_index": summary["image_index"],
        "rows": summary["rows"],
        "note": "No export task was created.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
