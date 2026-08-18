"""Generate a reproducible multimodal annotation prompt.

The prompt deliberately asks for structured pixel coordinates. A painted
overlay is useful for visual QA, but JSON geometry is the safer handoff for
CRS-aware vector export.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def build_prompt(
    image_path: Path,
    target: str,
    geometry: str = "polygon",
    constraints: str = "",
    classes: str = "",
) -> str:
    width, height = Image.open(image_path).size
    class_text = classes or target
    constraint_text = constraints or (
        "只标注清晰可分开的目标；被遮挡、截断或无法确认的目标降低置信度；不要把道路、建筑、阴影、纹理或背景误标为目标。"
    )
    schema = {
        "image_size": [width, height],
        "coordinate_space": "pixel",
        "objects": [
            {
                "id": "obj_001",
                "label": class_text.split(",")[0].strip(),
                "geometry_type": geometry,
                "confidence": 0.0,
                "vertices": [[0, 0], [1, 0], [1, 1]],
            }
        ],
    }
    return f"""请分析这张遥感影像，识别并勾画：{target}。

影像像素尺寸为 width={width}, height={height}。坐标原点在左上角，x 向右为列号，y 向下为行号。
目标类别：{class_text}。
期望几何类型：{geometry}。
判别要求：{constraint_text}

请只返回合法 JSON，不要 Markdown 代码块，不要解释文字，格式必须符合：
{json.dumps(schema, ensure_ascii=False, indent=2)}

规则：
1. polygon 的 vertices 必须按顺时针或逆时针闭合边界给出，首尾可以不重复。
2. point 使用一个 [x, y]；bbox 使用 [xmin, ymin, xmax, ymax]；line 使用折线顶点。
3. 坐标必须落在 0<=x<={width}, 0<=y<={height} 内。
4. confidence 为 0 到 1 之间的小数；不确定目标不要硬猜。
5. 不要输出无法从影像位置确定的经纬度；地理坐标由后处理程序根据 GeoTIFF CRS 计算。
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--target", required=True, help="目标，例如：车辆、树冠、田块边界")
    parser.add_argument("--geometry", choices=["polygon", "bbox", "point", "line"], default="polygon")
    parser.add_argument("--classes", default="")
    parser.add_argument("--constraints", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = build_prompt(args.image, args.target, args.geometry, args.constraints, args.classes)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
