#!/usr/bin/env python
"""Static review helper for Earth Engine/geemap Python or notebook code."""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


@dataclass
class Finding:
    severity: str
    code: str
    line: int
    message: str
    evidence: str = ""


def read_code(path: Path) -> str:
    if path.suffix.lower() == ".ipynb":
        notebook = json.loads(path.read_text(encoding="utf-8"))
        chunks = []
        for cell in notebook.get("cells", []):
            if cell.get("cell_type") == "code":
                source = cell.get("source", [])
                chunks.append("".join(source))
                chunks.append("\n")
        return "\n".join(chunks)
    return path.read_text(encoding="utf-8")


def sanitize_for_ast(source: str) -> str:
    lines = []
    for line in source.splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if stripped.startswith(("%", "!")):
            lines.append(f"{indent}# {stripped}")
        else:
            lines.append(line)
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    return ""


def source_snippet(source: str, node: ast.AST) -> str:
    try:
        text = ast.get_source_segment(source, node) or ""
    except Exception:
        text = ""
    text = " ".join(text.split())
    return text[:180]


def has_keyword(node: ast.Call, name: str) -> bool:
    return any(keyword.arg == name for keyword in node.keywords)


def text_line(source: str, needle: str) -> int:
    index = source.find(needle)
    if index < 0:
        return 1
    return source.count("\n", 0, index) + 1


class EEVisitor(ast.NodeVisitor):
    def __init__(self, source: str) -> None:
        self.source = source
        self.findings: list[Finding] = []
        self.mapped_functions: set[str] = set()
        self.stack: list[str] = []
        self.loop_depth = 0

    def add(self, severity: str, code: str, node: ast.AST, message: str) -> None:
        self.findings.append(
            Finding(
                severity=severity,
                code=code,
                line=getattr(node, "lineno", 1),
                message=message,
                evidence=source_snippet(self.source, node),
            )
        )

    def collect_mapped_functions(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if dotted_name(node.func).endswith(".map") and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Name):
                    self.mapped_functions.add(arg.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_For(self, node: ast.For) -> None:
        self.loop_depth += 1
        self.generic_visit(node)
        self.loop_depth -= 1

    def visit_While(self, node: ast.While) -> None:
        self.loop_depth += 1
        self.generic_visit(node)
        self.loop_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        name = dotted_name(node.func)
        in_mapped_function = bool(self.stack and self.stack[-1] in self.mapped_functions)

        if name.endswith(".getInfo"):
            if in_mapped_function:
                self.add("ERROR", "mapped-getinfo", node, "Do not call getInfo() inside a function passed to collection.map().")
            elif self.loop_depth:
                self.add("ERROR", "loop-getinfo", node, "Avoid getInfo() inside Python loops; use server-side reducers/exports.")
            else:
                self.add("WARN", "getinfo", node, "Keep getInfo() calls tiny and diagnostic; export large results instead.")

        if in_mapped_function and name == "print":
            self.add("WARN", "mapped-print", node, "Avoid print() inside mapped Earth Engine functions.")

        if name.endswith(".toList"):
            self.add("WARN", "tolist", node, "Prefer filter(), limit(), aggregate_*(), or reducers over collection.toList().")

        if name.endswith("ee.Algorithms.If") or name.endswith(".Algorithms.If"):
            self.add("WARN", "algorithms-if", node, "Use filters, masks, or separate collection paths before defaulting to ee.Algorithms.If().")

        if name.endswith(".reproject"):
            self.add("WARN", "reproject", node, "Use reproject() sparingly; prefer scale/crs on reducers or exports unless a fixed projection is required.")

        if name.endswith(".reduceRegion"):
            for keyword in ("geometry", "scale"):
                if not has_keyword(node, keyword):
                    self.add("WARN", f"reduceRegion-missing-{keyword}", node, f"reduceRegion() should explicitly set {keyword}.")
            if not has_keyword(node, "maxPixels") and not has_keyword(node, "bestEffort"):
                self.add("WARN", "reduceRegion-missing-pixel-limit", node, "Set maxPixels or justify bestEffort for reduceRegion().")

        if name.endswith(".reduceRegions"):
            for keyword in ("collection", "scale"):
                if not has_keyword(node, keyword):
                    self.add("WARN", f"reduceRegions-missing-{keyword}", node, f"reduceRegions() should explicitly set {keyword}.")

        if ".Export.image." in name:
            for keyword in ("region", "scale"):
                if not has_keyword(node, keyword):
                    self.add("WARN", f"export-image-missing-{keyword}", node, f"Image export should explicitly set {keyword}.")
            if not has_keyword(node, "maxPixels"):
                self.add("WARN", "export-image-missing-maxPixels", node, "Image export should set maxPixels intentionally.")

        if ".Export.table." in name and not has_keyword(node, "collection"):
            self.add("WARN", "export-table-missing-collection", node, "Table export should explicitly set collection.")

        if name.endswith("ee.Initialize") or name == "ee.Initialize":
            if not has_keyword(node, "project"):
                self.add("WARN", "initialize-missing-project", node, "Prefer ee.Initialize(project='...') for local Python workflows.")

        self.generic_visit(node)


def text_findings(source: str) -> Iterable[Finding]:
    def find_line(pattern: str) -> int:
        match = re.search(pattern, source)
        if not match:
            return 1
        return source.count("\n", 0, match.start()) + 1

    uses_ee = "ee." in source or "import ee" in source
    if uses_ee and "ee.Initialize" not in source:
        yield Finding("WARN", "missing-initialize", 1, "Earth Engine code should initialize explicitly or explain deferred initialization.")

    if "ee.Authenticate(" in source:
        yield Finding("INFO", "authenticate-present", text_line(source, "ee.Authenticate("), "Do not run authentication automatically unless the user requested setup.")

    if "Export." in source and ".start(" not in source:
        yield Finding("INFO", "export-not-started", text_line(source, "Export."), "Export task is defined but not started; this is fine only when intentionally handing off review/start to the user.")

    if "COPERNICUS/S2_SR_HARMONIZED" in source:
        has_pixel_mask = any(
            token in source
            for token in (
                "updateMask",
                "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED",
                "COPERNICUS/S2_CLOUD_PROBABILITY",
                "SCL",
                "QA60",
            )
        )
        if not has_pixel_mask:
            yield Finding("WARN", "s2-no-pixel-mask", text_line(source, "COPERNICUS/S2_SR_HARMONIZED"), "Sentinel-2 scene cloud filtering is not pixel masking; add Cloud Score+, SCL, s2cloudless, or a justified mask.")
        if "QA60" in source:
            yield Finding("WARN", "s2-qa60-caveat", text_line(source, "QA60"), "QA60 has a 2022-01-25 to 2024-02-28 gap/caveat; prefer Cloud Score+, SCL, or cloud probability for multi-year workflows.")

    if re.search(r"LANDSAT/L[CTE]0[45789]/C02/T1_L2", source):
        if "0.0000275" not in source:
            yield Finding("WARN", "landsat-c2-missing-scale", find_line(r"LANDSAT/L[CTE]0[45789]/C02/T1_L2"), "Apply Landsat Collection 2 Level 2 optical scale factor 0.0000275 and offset -0.2 before analysis/export.")
        if "QA_PIXEL" not in source:
            yield Finding("WARN", "landsat-c2-missing-qa", find_line(r"LANDSAT/L[CTE]0[45789]/C02/T1_L2"), "Use QA_PIXEL bits for cloud, shadow, cirrus, snow, and dilated cloud masking.")

    if "MODIS/061/MOD13Q1" in source:
        if "0.0001" not in source:
            yield Finding("WARN", "modis-vi-missing-scale", text_line(source, "MODIS/061/MOD13Q1"), "MOD13Q1 NDVI/EVI are scaled by 0.0001.")
        if "DetailedQA" not in source and "SummaryQA" not in source:
            yield Finding("INFO", "modis-vi-no-qa", text_line(source, "MODIS/061/MOD13Q1"), "Consider DetailedQA or SummaryQA filtering before MODIS VI time-series analysis.")

    if "GOOGLE/DYNAMICWORLD/V1" in source and re.search(r"select\(\s*['\"]label['\"]", source):
        yield Finding("WARN", "dynamicworld-label-only", text_line(source, "GOOGLE/DYNAMICWORLD/V1"), "Dynamic World label is the top class; inspect probability bands or confidence thresholds before treating it as truth.")

    if "ESA/WorldCover" in source and re.search(r"\.mean\s*\(", source):
        yield Finding("WARN", "categorical-mean", text_line(source, "ESA/WorldCover"), "WorldCover is categorical; use mode, grouped reducers, or area counts instead of mean class labels.")


def review(source: str) -> list[Finding]:
    findings = list(text_findings(source))
    ast_source = sanitize_for_ast(source)
    try:
        tree = ast.parse(ast_source)
    except SyntaxError as exc:
        findings.append(Finding("ERROR", "python-syntax", exc.lineno or 1, f"Python syntax error: {exc.msg}"))
        return findings

    visitor = EEVisitor(source)
    visitor.collect_mapped_functions(tree)
    visitor.visit(tree)
    findings.extend(visitor.findings)
    findings.sort(key=lambda item: (item.line, item.severity, item.code))
    return findings


def print_text(path: Path, findings: list[Finding]) -> None:
    print(f"Earth Engine review: {path}")
    if not findings:
        print("No findings.")
        return
    for item in findings:
        location = f"line {item.line}" if item.line else "line ?"
        print(f"[{item.severity}] {item.code} ({location}): {item.message}")
        if item.evidence:
            print(f"  {item.evidence}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Python script or .ipynb notebook")
    parser.add_argument("--json", action="store_true", help="Emit JSON findings")
    parser.add_argument("--strict", action="store_true", help="Exit 1 when WARN/ERROR findings exist")
    args = parser.parse_args()

    source = read_code(args.path)
    findings = review(source)
    if args.json:
        print(json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2))
    else:
        print_text(args.path, findings)

    if any(item.severity == "ERROR" for item in findings):
        return 2
    if args.strict and any(item.severity == "WARN" for item in findings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
