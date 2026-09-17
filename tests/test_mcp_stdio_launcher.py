"""Regression tests for the EasyGEE stdio MCP launcher on Windows.

Drives the real PowerShell launcher declared in .mcp.json and checks that both
Content-Length framed and newline-delimited JSON-RPC work, and that stdout
carries protocol bytes only.

Run: python tests/test_mcp_stdio_launcher.py   (or pytest)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCP_CONFIG = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["easygee"]
TIMEOUT = 30.0
# Codex spawns plugin MCP servers in the session cwd unless .mcp.json declares
# "cwd" (resolved against the plugin root), so an unrelated dir mirrors that.
LAUNCH_CWD = ROOT / MCP_CONFIG["cwd"] if "cwd" in MCP_CONFIG else Path(tempfile.gettempdir())


class LauncherProcess:
    def __init__(self, env: dict[str, str] | None = None) -> None:
        command = shutil.which(MCP_CONFIG["command"]) or MCP_CONFIG["command"]
        self.proc = subprocess.Popen(
            [command, *MCP_CONFIG["args"]],
            cwd=LAUNCH_CWD,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, **(env or {})},
        )
        self.stdout = bytearray()
        self.stderr = bytearray()
        self._lock = threading.Lock()
        threading.Thread(target=self._pump, args=(self.proc.stdout, self.stdout), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.proc.stderr, self.stderr), daemon=True).start()
        self.consumed = 0

    def _pump(self, stream, sink: bytearray) -> None:
        while True:
            chunk = stream.read1(65536)
            if not chunk:
                return
            with self._lock:
                sink.extend(chunk)

    def send(self, data: bytes) -> None:
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def _wait_for(self, parse):
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            with self._lock:
                result = parse(bytes(self.stdout[self.consumed :]))
            if result is not None:
                message, used = result
                self.consumed += used
                return message
            if self.proc.poll() is not None:
                time.sleep(0.2)
                with self._lock:
                    result = parse(bytes(self.stdout[self.consumed :]))
                if result is not None:
                    message, used = result
                    self.consumed += used
                    return message
                raise AssertionError(f"server exited early (code {self.proc.returncode}); {self.describe()}")
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for response; {self.describe()}")

    def read_framed(self) -> dict:
        def parse(buf: bytes):
            if not buf:
                return None
            assert buf.startswith(b"Content-Length: "), f"non-protocol bytes on stdout: {buf[:200]!r}"
            head_end = buf.find(b"\r\n\r\n")
            if head_end < 0:
                return None
            length = int(buf[len(b"Content-Length: ") : head_end].decode("ascii"))
            body_start = head_end + 4
            if len(buf) < body_start + length:
                return None
            return json.loads(buf[body_start : body_start + length].decode("utf-8")), body_start + length

        return self._wait_for(parse)

    def read_line(self) -> dict:
        def parse(buf: bytes):
            if not buf:
                return None
            assert buf.startswith(b"{"), f"non-protocol bytes on stdout: {buf[:200]!r}"
            end = buf.find(b"\n")
            if end < 0:
                return None
            return json.loads(buf[:end].decode("utf-8")), end + 1

        return self._wait_for(parse)

    def assert_alive(self) -> None:
        time.sleep(0.5)
        assert self.proc.poll() is None, f"server exited (code {self.proc.returncode}); {self.describe()}"

    def close(self) -> str:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        time.sleep(0.2)
        with self._lock:
            leftover = bytes(self.stdout[self.consumed :])
        assert leftover == b"", f"unexpected trailing stdout bytes: {leftover[:200]!r}"
        stderr = bytes(self.stderr)
        stderr.decode("utf-8")  # stderr must be valid UTF-8
        return stderr.decode("utf-8")

    def describe(self) -> str:
        with self._lock:
            return f"stdout={bytes(self.stdout)[:300]!r} stderr={bytes(self.stderr)[:500]!r}"


def _frame(message: dict) -> bytes:
    body = json.dumps(message).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body


INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "codex-regression", "version": "0"},
    },
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


def _check_initialize(response: dict) -> None:
    assert response.get("jsonrpc") == "2.0" and response.get("id") == 0, response
    assert "error" not in response, response
    assert response["result"]["serverInfo"]["name"] == "easygee", response


def _check_tools(response: dict) -> None:
    assert response.get("id") == 1 and "error" not in response, response
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert "easygee_preview_plan" in names, names


def test_content_length_framing_through_launcher() -> None:
    server = LauncherProcess()
    try:
        server.send(_frame(INITIALIZE))
        _check_initialize(server.read_framed())
        server.send(_frame(INITIALIZED))
        server.assert_alive()
        server.send(_frame(TOOLS_LIST))
        _check_tools(server.read_framed())
        server.assert_alive()
    finally:
        server.close()


def test_newline_json_through_launcher() -> None:
    server = LauncherProcess()
    try:
        server.send(json.dumps(INITIALIZE).encode("utf-8") + b"\n")
        _check_initialize(server.read_line())
        server.send(json.dumps(INITIALIZED).encode("utf-8") + b"\n")
        server.assert_alive()
        server.send(json.dumps(TOOLS_LIST).encode("utf-8") + b"\n")
        _check_tools(server.read_line())
    finally:
        server.close()


def test_launcher_failure_keeps_stdout_clean_and_stderr_utf8() -> None:
    server = LauncherProcess(env={"EASYGEE_PYTHON": str(ROOT / "missing-python-路径.exe")})
    server.proc.stdin.close()
    server.proc.wait(timeout=TIMEOUT)
    time.sleep(0.2)
    assert server.proc.returncode != 0
    assert bytes(server.stdout) == b"", server.describe()
    assert bytes(server.stderr), server.describe()
    bytes(server.stderr).decode("utf-8")


if __name__ == "__main__":
    failed = 0
    for test in (
        test_content_length_framing_through_launcher,
        test_newline_json_through_launcher,
        test_launcher_failure_keeps_stdout_clean_and_stderr_utf8,
    ):
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    sys.exit(1 if failed else 0)
