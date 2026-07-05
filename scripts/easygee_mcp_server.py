#!/usr/bin/env python3
"""Small stdio MCP wrapper around EasyGEE's existing scripts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PLUGIN_ROOT / "skills" / "easygee"
SCRIPT_ROOT = SKILL_ROOT / "scripts"
SCRATCH_ROOT = Path("D:/Scratch/easygee-plugin")
SERVER_NAME = "easygee"
SERVER_VERSION = "0.1.0"

FRAME_MODE: str | None = None


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


TOOLS: list[dict[str, Any]] = [
    {
        "name": "easygee_check_environment",
        "description": "Check local Earth Engine, geemap, and optional project initialization readiness without printing credentials.",
        "inputSchema": _schema(
            {
                "project": {"type": "string", "description": "Optional Google Cloud / Earth Engine project id."},
                "initialize": {"type": "boolean", "description": "Try ee.Initialize(project=...) without running OAuth."},
            }
        ),
    },
    {
        "name": "easygee_auth_plan",
        "description": "Return a credential-safe Earth Engine/geemap authorization plan. Does not run OAuth.",
        "inputSchema": _schema(
            {
                "project": {"type": "string", "description": "Google Cloud / Earth Engine project id."},
                "mode": {
                    "type": "string",
                    "enum": ["auto", "localhost", "notebook", "gcloud", "colab", "service-account"],
                    "description": "Earth Engine auth mode.",
                },
                "include_auth_snippet": {"type": "boolean", "description": "Include ee.Authenticate(...) setup snippet."},
            }
        ),
    },
    {
        "name": "easygee_search_catalog",
        "description": "Search likely Google Earth Engine datasets for a task or dataset query.",
        "inputSchema": _schema(
            {
                "query": {"type": "string", "description": "Dataset need, task prompt, or analysis goal."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Maximum candidate count."},
                "workflow": {"type": "boolean", "description": "Include concise workflow hints when supported."},
                "geemap_ai": {"type": "boolean", "description": "Also try geemap's AI dataset index when installed."},
            },
            ["query"],
        ),
    },
    {
        "name": "easygee_quota_summary",
        "description": "Show Earth Engine quota totals and optional recent usage for a Cloud project or quotas Console URL.",
        "inputSchema": _schema(
            {
                "project": {"type": "string", "description": "Google Cloud project id or number."},
                "console_url": {"type": "string", "description": "Optional Cloud Console quotas URL."},
                "include_usage": {"type": "boolean", "description": "Query recent Cloud Monitoring usage metrics."},
                "minutes": {"type": "integer", "minimum": 1, "maximum": 1440, "description": "Lookback window for usage metrics."},
                "no_live": {"type": "boolean", "description": "Skip live Google Cloud API calls and use fallback guidance."},
            }
        ),
    },
    {
        "name": "easygee_create_map_console",
        "description": "Generate the EasyGEE local browser map console HTML. This does not start a long-running server.",
        "inputSchema": _schema(
            {
                "project": {"type": "string", "description": "Optional Earth Engine / Google Cloud project id."},
                "title": {"type": "string", "description": "Map console title."},
                "lat": {"type": "number", "description": "Initial latitude."},
                "lon": {"type": "number", "description": "Initial longitude."},
                "zoom": {"type": "integer", "minimum": 1, "maximum": 20, "description": "Initial zoom."},
                "default_layer": {"type": "string", "description": "Default layer id such as ndvi, s2-rgb, dynamic-world, jrc-water, or srtm."},
                "live": {"type": "boolean", "description": "Pre-populate live Earth Engine demo layers."},
                "sample": {"type": "boolean", "description": "Generate offline sample console without Earth Engine calls."},
                "output": {"type": "string", "description": "Optional output HTML path under D:/Scratch or D:/Data/exports."},
            }
        ),
    },
    {
        "name": "easygee_preview_plan",
        "description": "Return a local preview server plan for an EasyGEE/geemap HTML artifact without starting the server.",
        "inputSchema": _schema(
            {
                "target": {"type": "string", "description": "Optional HTML file or directory to preview."},
                "title": {"type": "string", "description": "Placeholder title when no target is supplied."},
            }
        ),
    },
]


def _read_message() -> dict[str, Any] | None:
    global FRAME_MODE
    first = sys.stdin.buffer.readline()
    if not first:
        return None
    if first.startswith(b"Content-Length:"):
        FRAME_MODE = FRAME_MODE or "headers"
        length = int(first.decode("ascii").split(":", 1)[1].strip())
        while True:
            line = sys.stdin.buffer.readline()
            if line in (b"\r\n", b"\n", b""):
                break
        payload = sys.stdin.buffer.read(length)
        return json.loads(payload.decode("utf-8"))
    FRAME_MODE = FRAME_MODE or "lines"
    return json.loads(first.decode("utf-8"))


def _write_message(message: dict[str, Any]) -> None:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if FRAME_MODE == "headers":
        sys.stdout.buffer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
        sys.stdout.buffer.write(payload)
    else:
        sys.stdout.buffer.write(payload + b"\n")
    sys.stdout.buffer.flush()


def _response(request_id: Any, result: Any = None, error: dict[str, Any] | None = None) -> None:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        message["error"] = error
    else:
        message["result"] = result
    _write_message(message)


def _tool_text(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _safe_output_path(raw: str | None) -> Path:
    if not raw:
        return SCRATCH_ROOT / "map-console" / "index.html"
    candidate = Path(raw).expanduser().resolve()
    allowed_roots = [SCRATCH_ROOT.resolve(), Path("D:/Data/exports").resolve()]
    if not any(candidate == root or root in candidate.parents for root in allowed_roots):
        raise ValueError("output must be under D:/Scratch/easygee-plugin or D:/Data/exports")
    if candidate.suffix.lower() != ".html":
        raise ValueError("output must be an .html file")
    return candidate


def _run_script(script: str, args: list[str], timeout: int = 120) -> dict[str, Any]:
    script_path = (SCRIPT_ROOT / script).resolve()
    if SCRIPT_ROOT.resolve() not in script_path.parents or script_path.suffix != ".py":
        raise ValueError(f"script is not allowlisted: {script}")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=str(SKILL_ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def _format_run(label: str, run: dict[str, Any]) -> dict[str, Any]:
    text = run["stdout"] or ""
    if run["stderr"]:
        text = f"{text}\n\nstderr:\n{run['stderr']}".strip()
    if not text:
        text = f"{label} completed with exit code {run['returncode']}."
    return _tool_text(text, is_error=run["returncode"] != 0)


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "easygee_check_environment":
        args = ["--json"]
        if arguments.get("project"):
            args += ["--project", str(arguments["project"])]
        if arguments.get("initialize"):
            args.append("--initialize")
        return _format_run(name, _run_script("check_gee_geemap.py", args))

    if name == "easygee_auth_plan":
        args = ["--json"]
        if arguments.get("project"):
            args += ["--project", str(arguments["project"])]
        args += ["--mode", str(arguments.get("mode") or "auto")]
        if arguments.get("include_auth_snippet"):
            args.append("--include-auth-snippet")
        return _format_run(name, _run_script("ee_auth_workflow.py", args))

    if name == "easygee_search_catalog":
        args = [str(arguments["query"]), "--json", "--limit", str(int(arguments.get("limit") or 8))]
        if arguments.get("workflow"):
            args.append("--workflow")
        if arguments.get("geemap_ai"):
            args.append("--geemap-ai")
        return _format_run(name, _run_script("search_gee_dataset.py", args))

    if name == "easygee_quota_summary":
        args = ["--json"]
        if arguments.get("console_url"):
            args.append(str(arguments["console_url"]))
        if arguments.get("project"):
            args += ["--project", str(arguments["project"])]
        if arguments.get("include_usage"):
            args.append("--include-usage")
        if arguments.get("minutes"):
            args += ["--minutes", str(int(arguments["minutes"]))]
        if arguments.get("no_live"):
            args.append("--no-live")
        return _format_run(name, _run_script("show_ee_quotas.py", args, timeout=180))

    if name == "easygee_create_map_console":
        output = _safe_output_path(arguments.get("output"))
        output.parent.mkdir(parents=True, exist_ok=True)
        args = ["--output", str(output), "--json"]
        if arguments.get("project"):
            args += ["--project", str(arguments["project"])]
        if arguments.get("title"):
            args += ["--title", str(arguments["title"])]
        for key, flag in (("lat", "--lat"), ("lon", "--lon"), ("zoom", "--zoom")):
            if arguments.get(key) is not None:
                args += [flag, str(arguments[key])]
        if arguments.get("default_layer"):
            args += ["--default-layer", str(arguments["default_layer"])]
        if arguments.get("live"):
            args.append("--live")
        if arguments.get("sample"):
            args.append("--sample")
        return _format_run(name, _run_script("create_map_console.py", args, timeout=240))

    if name == "easygee_preview_plan":
        args = ["--json"]
        if arguments.get("target"):
            args.append(str(arguments["target"]))
        if arguments.get("title"):
            args += ["--title", str(arguments["title"])]
        return _format_run(name, _run_script("serve_map_preview.py", args))

    raise ValueError(f"unknown tool: {name}")


def main() -> int:
    while True:
        request = _read_message()
        if request is None:
            return 0
        method = request.get("method")
        request_id = request.get("id")
        try:
            if method == "initialize":
                params = request.get("params") or {}
                _response(
                    request_id,
                    {
                        "protocolVersion": params.get("protocolVersion") or "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    },
                )
            elif method == "notifications/initialized":
                continue
            elif method == "ping":
                _response(request_id, {})
            elif method == "tools/list":
                _response(request_id, {"tools": TOOLS})
            elif method == "tools/call":
                params = request.get("params") or {}
                _response(request_id, call_tool(str(params.get("name")), params.get("arguments") or {}))
            else:
                _response(request_id, error={"code": -32601, "message": f"Method not found: {method}"})
        except Exception as exc:
            _response(request_id, error={"code": -32000, "message": str(exc)})


if __name__ == "__main__":
    raise SystemExit(main())
