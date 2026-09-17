from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MCP_CONFIG = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["easygee"]
POWERSHELL = shutil.which(MCP_CONFIG["command"])
TIMEOUT = 30.0


def launcher_cwd() -> Path:
    configured = MCP_CONFIG.get("cwd")
    return (ROOT / str(configured)).resolve() if configured else Path(tempfile.gettempdir())


def run_launcher(payload: bytes, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    if not POWERSHELL:
        pytest.skip("PowerShell is required for the Windows MCP launcher test")
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        [POWERSHELL, *MCP_CONFIG["args"]],
        cwd=launcher_cwd(),
        env=process_env,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=TIMEOUT,
        check=False,
    )


INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "easygee-regression", "version": "0"},
    },
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


def frame(message: dict[str, object]) -> bytes:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body


def parse_framed_messages(data: bytes) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    offset = 0
    while offset < len(data):
        assert data.startswith(b"Content-Length: ", offset), data[:200]
        header_end = data.find(b"\r\n\r\n", offset)
        assert header_end >= 0, data[offset:]
        length = int(data[offset + len(b"Content-Length: ") : header_end].split(b"\r\n", 1)[0])
        body_start = header_end + 4
        body_end = body_start + length
        assert len(data) >= body_end, data[offset:]
        messages.append(json.loads(data[body_start:body_end].decode("utf-8")))
        offset = body_end
    return messages


def parse_line_messages(data: bytes) -> list[dict[str, object]]:
    assert data.startswith(b"{") or not data, data[:200]
    return [json.loads(line.decode("utf-8")) for line in data.splitlines() if line]


@pytest.mark.parametrize("mode", ["framed", "lines"])
def test_mcp_launcher_handles_json_rpc_from_unrelated_session(mode: str) -> None:
    if mode == "framed":
        payload = frame(INITIALIZE) + frame(INITIALIZED) + frame(TOOLS_LIST)
    else:
        payload = b"\n".join(json.dumps(message).encode("utf-8") for message in (INITIALIZE, INITIALIZED, TOOLS_LIST)) + b"\n"

    result = run_launcher(payload)

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    result.stderr.decode("utf-8")
    messages = parse_framed_messages(result.stdout) if mode == "framed" else parse_line_messages(result.stdout)
    assert messages[0]["result"]["serverInfo"]["name"] == "easygee"
    tool_names = {tool["name"] for tool in messages[1]["result"]["tools"]}
    assert "easygee_preview_plan" in tool_names


def test_mcp_launcher_failure_keeps_stdout_clean_and_stderr_utf8() -> None:
    missing_python = ROOT / "missing-python-路径.exe"
    result = run_launcher(b"", env={"EASYGEE_PYTHON": str(missing_python)})

    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr
    result.stderr.decode("utf-8")
