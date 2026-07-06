#!/usr/bin/env python
"""Refresh only the embedded quota state in an EasyGEE Map Console HTML file.

This helper is for UI/code maintenance on an existing Map Console page. It
updates `STATE.quota` without regenerating Earth Engine layers, tile URLs, AOI,
or measurements. By default it refuses to write default-only quota fallback
state, so a transient quota lookup failure does not silently downgrade a
user-facing workbench.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from create_map_console import build_quota_state


STATE_MARKER = "const STATE = "
LIVE_QUOTA_STATUSES = {"live-with-usage", "live-limit-only"}


def find_state_json_span(text: str) -> tuple[int, int]:
    marker_index = text.find(STATE_MARKER)
    if marker_index < 0:
        raise ValueError("Could not find `const STATE =` in the HTML file.")
    start = text.find("{", marker_index + len(STATE_MARKER))
    if start < 0:
        raise ValueError("Could not find the start of the STATE JSON object.")

    in_string = False
    escape = False
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start, index + 1
    raise ValueError("Could not find the end of the STATE JSON object.")


def load_state_from_html(text: str) -> tuple[dict[str, Any], tuple[int, int]]:
    start, end = find_state_json_span(text)
    state = json.loads(text[start:end])
    if not isinstance(state, dict):
        raise ValueError("STATE JSON is not an object.")
    return state, (start, end)


def quota_is_live(quota: dict[str, Any]) -> bool:
    return quota.get("status") in LIVE_QUOTA_STATUSES


def quota_summary(quota: dict[str, Any]) -> dict[str, Any]:
    return {
        "quotaSource": quota.get("source"),
        "usageSource": quota.get("usageSource"),
        "status": quota.get("status"),
        "indicator": quota.get("indicator"),
        "rows": len(quota.get("rows") or []),
        "warnings": quota.get("warnings") or [],
    }


def refresh_quota_in_html(
    html_path: Path,
    *,
    project: str | None,
    include_usage: bool,
    minutes: int,
    allow_fallback: bool,
    require_usage: bool,
) -> tuple[bool, dict[str, Any]]:
    text = html_path.read_text(encoding="utf-8")
    state, span = load_state_from_html(text)
    resolved_project = project or state.get("project")
    if not resolved_project:
        raise ValueError("No project was provided and STATE.project is missing.")

    quota = build_quota_state(str(resolved_project), include_usage=include_usage, no_live=False, minutes=minutes)
    summary = quota_summary(quota)
    summary["project"] = str(resolved_project)
    if not quota_is_live(quota) and not allow_fallback:
        summary["updated"] = False
        summary["error"] = "Live quota lookup was unavailable; existing HTML was left unchanged."
        return False, summary
    if require_usage and quota.get("status") != "live-with-usage":
        summary["updated"] = False
        summary["error"] = "Cloud Monitoring usage was unavailable; existing HTML was left unchanged."
        return False, summary

    state["quota"] = quota
    start, end = span
    next_state = json.dumps(state, ensure_ascii=False)
    html_path.write_text(text[:start] + next_state + text[end:], encoding="utf-8")
    summary["updated"] = True
    summary["path"] = str(html_path)
    return True, summary


def smoke() -> int:
    sample = (
        '<script>\n'
        'const STATE = {"project":"demo-project","layers":[{"id":"x","tileUrl":"local-preview"}],'
        '"quota":{"status":"default-only","source":"official Earth Engine default"}};\n'
        "</script>\n"
    )
    state, span = load_state_from_html(sample)
    quota = {"status": "live-with-usage", "source": "Cloud Quotas REST API", "usageSource": "Cloud Monitoring API", "rows": [1]}
    state["quota"] = quota
    start, end = span
    updated = sample[:start] + json.dumps(state, ensure_ascii=False) + sample[end:]
    next_state, _ = load_state_from_html(updated)
    if next_state.get("quota") != quota:
        print("FAIL quota replacement")
        return 1
    if next_state.get("layers", [{}])[0].get("tileUrl") != "local-preview":
        print("FAIL layer state was not preserved")
        return 1
    print("refresh_map_console_quota smoke passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", nargs="?", type=Path, help="Existing Map Console HTML file to update.")
    parser.add_argument("--project", help="Override STATE.project.")
    parser.add_argument("--minutes", type=int, default=60, help="Cloud Monitoring usage lookback window.")
    parser.add_argument("--no-usage", action="store_true", help="Skip Cloud Monitoring usage and update live quota limits only.")
    parser.add_argument("--allow-fallback", action="store_true", help="Allow writing default-only fallback quota state if live lookup fails.")
    parser.add_argument("--require-usage", action="store_true", help="Refuse to write unless Cloud Monitoring usage is available.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON summary.")
    parser.add_argument("--smoke", action="store_true", help="Run offline parser/rewrite checks.")
    args = parser.parse_args()

    if args.smoke:
        return smoke()
    if args.html is None:
        parser.error("html is required unless --smoke is used")
    if args.require_usage and args.no_usage:
        parser.error("--require-usage cannot be combined with --no-usage")

    ok, summary = refresh_quota_in_html(
        args.html,
        project=args.project,
        include_usage=not args.no_usage,
        minutes=args.minutes,
        allow_fallback=args.allow_fallback,
        require_usage=args.require_usage,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
