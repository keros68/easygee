#!/usr/bin/env python
"""Serve an EasyGEE map preview page with Python's standard library.

Use this for lightweight, persistent browser previews of geemap-exported HTML
or other local map artifacts. The script does not authenticate to Earth Engine,
open OAuth, or read credential files.
"""

from __future__ import annotations

import argparse
import functools
import html
import json
import os
import re
import socket
import tempfile
import threading
import time
import urllib.parse
from dataclasses import asdict, dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


@dataclass(frozen=True)
class PreviewPlan:
    root: str
    url: str
    target: str
    target_type: str
    title: str
    notes: tuple[str, ...]


def default_preview_root() -> Path:
    if os.name == "nt":
        scratch = Path("D:/Scratch")
        if scratch.exists() or scratch.parent.exists():
            return scratch / "easygee-preview"
    return Path(tempfile.gettempdir()) / "easygee-preview"


def write_placeholder(root: Path, title: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    index = root / "index.html"
    safe_title = html.escape(title)
    index.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: Inter, Segoe UI, system-ui, sans-serif;
      background: #f7f8fa;
      color: #111827;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
    }}
    main {{
      max-width: 760px;
      padding: 32px;
      line-height: 1.55;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 28px;
      letter-spacing: 0;
    }}
    code {{
      background: rgba(17, 24, 39, 0.08);
      border-radius: 4px;
      padding: 2px 5px;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{ background: #101318; color: #e5e7eb; }}
      code {{ background: rgba(229, 231, 235, 0.14); }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>{safe_title}</h1>
    <p>This local preview server is running. Export a geemap map to HTML, then serve that file with <code>serve_map_preview.py map.html</code>.</p>
    <p>Keep this terminal session open while using the preview page.</p>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return index


def choose_port(host: str, requested: int) -> int:
    if requested:
        return requested
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def build_plan(target: Path | None, host: str, port: int, title: str, root_arg: Path | None) -> PreviewPlan:
    notes: list[str] = []
    root = root_arg or default_preview_root()
    target_type = "placeholder"
    target_label = "generated placeholder"

    if target:
        target = target.expanduser().resolve()
        if not target.exists():
            raise FileNotFoundError(f"Preview target does not exist: {target}")
        if target.is_dir():
            root = target
            path = "index.html"
            target_type = "directory"
            target_label = str(target)
            if not (target / "index.html").exists():
                notes.append("Directory has no index.html; the browser will show a directory listing.")
                path = ""
        else:
            root = target.parent
            path = urllib.parse.quote(target.name)
            target_type = "file"
            target_label = str(target)
            if target.suffix.lower() not in {".html", ".htm"}:
                notes.append("Target is not an HTML file; the browser may download or render it as plain text.")
    else:
        placeholder = write_placeholder(root, title)
        path = urllib.parse.quote(placeholder.name)
        target_label = str(placeholder)
        notes.append("Generated a placeholder preview page.")

    root.mkdir(parents=True, exist_ok=True)
    actual_port = choose_port(host, port)
    url_path = f"/{path}" if path else "/"
    url = f"http://{host}:{actual_port}{url_path}"
    return PreviewPlan(
        root=str(root),
        url=url,
        target=target_label,
        target_type=target_type,
        title=title,
        notes=tuple(notes),
    )


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} {format % args}")


CATALOG_CACHE: dict[str, object] | None = None
SESSION_LOCK = threading.Lock()
SESSION_STATE: dict[str, object] = {}
SESSION_SYNCED_AT: float | None = None
SESSION_ACTIONS: list[dict[str, object]] = []
SESSION_ACTION_COUNTER = 0
SESSION_ACTION_LIMIT = 100
PROFILE_VERSION = 1
PROFILE_LOCK = threading.Lock()
PROFILE_PATH: Path | None = None
EXACT_FAVORITE_REASONS = {"favorites", "favorite-updated"}
CLEAR_AOI_REASONS = {"aoi-cleared"}
CLEAR_MEASUREMENT_REASONS = {"measurements-cleared"}


def contract_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / "map-console-agent-contract.json"


def load_agent_contract() -> dict[str, object]:
    try:
        payload = json.loads(contract_path().read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {"name": "EasyGEE Map Console Agent Contract", "version": 1}


def default_profile_path() -> Path:
    explicit = os.environ.get("EASYGEE_MAP_CONSOLE_PROFILE")
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return root / "EasyGEE" / "map-console-profile.json"


def configure_profile_path(path: Path | None) -> None:
    global PROFILE_PATH
    PROFILE_PATH = path.expanduser().resolve() if path else default_profile_path()


def profile_path() -> Path:
    global PROFILE_PATH
    if PROFILE_PATH is None:
        PROFILE_PATH = default_profile_path()
    return PROFILE_PATH


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def json_clone(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False))


def empty_profile() -> dict[str, object]:
    return {
        "version": PROFILE_VERSION,
        "favoriteDatasets": [],
        "projects": {},
        "updatedAt": None,
    }


def normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return sorted(result)


def normalize_profile(payload: object) -> dict[str, object]:
    profile = empty_profile()
    if isinstance(payload, dict):
        profile.update(payload)
    profile["version"] = PROFILE_VERSION
    profile["favoriteDatasets"] = normalize_string_list(profile.get("favoriteDatasets"))
    projects = profile.get("projects")
    profile["projects"] = projects if isinstance(projects, dict) else {}
    return profile


def read_profile_unlocked() -> dict[str, object]:
    path = profile_path()
    if not path.exists():
        return empty_profile()
    try:
        return normalize_profile(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return empty_profile()


def write_profile_unlocked(profile: dict[str, object]) -> None:
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalize_profile(profile), ensure_ascii=False, indent=2), encoding="utf-8")


def load_profile() -> dict[str, object]:
    with PROFILE_LOCK:
        return json_clone(read_profile_unlocked())  # type: ignore[return-value]


def project_key_from_state(state: dict[str, object]) -> str:
    project = str(state.get("project") or "").strip()
    title = str(state.get("title") or "").strip()
    source = project if project and project != "YOUR_EE_PROJECT" else title
    source = source or "default"
    key = re.sub(r"[^a-z0-9_-]+", "-", source, flags=re.IGNORECASE).strip("-")[:80]
    return key or "default"


def state_project_entry(profile: dict[str, object], state: dict[str, object]) -> dict[str, object]:
    projects = profile.setdefault("projects", {})
    if not isinstance(projects, dict):
        projects = {}
        profile["projects"] = projects
    key = project_key_from_state(state)
    entry = projects.get(key)
    if not isinstance(entry, dict):
        entry = {}
        projects[key] = entry
    project = str(state.get("project") or "").strip()
    title = str(state.get("title") or "").strip()
    if project:
        entry["project"] = project
    if title:
        entry["title"] = title
    entry["updatedAt"] = now_iso()
    return entry


def sanitize_recent_layers(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    allowed = {"id", "name", "dataset", "shown", "opacity", "summary", "aoi"}
    layers: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        safe = {key: json_clone(item[key]) for key in allowed if key in item}
        if safe:
            layers.append(safe)  # type: ignore[arg-type]
    return layers[:50]


def merge_profile_with_state(state: dict[str, object]) -> dict[str, object]:
    reason = str(state.get("sessionReason") or "").lower()
    with PROFILE_LOCK:
        profile = read_profile_unlocked()
        favorites = normalize_string_list(state.get("favoriteDatasets"))
        if reason in EXACT_FAVORITE_REASONS:
            profile["favoriteDatasets"] = favorites
        elif favorites:
            profile["favoriteDatasets"] = normalize_string_list([*normalize_string_list(profile.get("favoriteDatasets")), *favorites])

        language = state.get("language")
        if isinstance(language, str) and language:
            profile["language"] = language

        entry = state_project_entry(profile, state)
        center = state.get("center")
        zoom = state.get("zoom")
        basemap = state.get("basemap")
        if isinstance(center, list) and len(center) == 2 and isinstance(zoom, (int, float)):
            entry["view"] = {"center": json_clone(center), "zoom": zoom, "basemap": basemap}
        if isinstance(state.get("aoi"), dict):
            entry["aoi"] = json_clone(state["aoi"])
        elif "aoi" in state and reason in CLEAR_AOI_REASONS:
            entry.pop("aoi", None)
        measurements = state.get("measurements")
        if isinstance(measurements, list) and (measurements or reason in CLEAR_MEASUREMENT_REASONS):
            entry["measurements"] = json_clone(measurements)
        layers = sanitize_recent_layers(state.get("layers"))
        if layers:
            entry["recentLayers"] = layers

        profile["updatedAt"] = now_iso()
        write_profile_unlocked(profile)
        return json_clone(profile)  # type: ignore[return-value]


def session_state_payload() -> dict[str, object]:
    with SESSION_LOCK:
        state = json.loads(json.dumps(SESSION_STATE, ensure_ascii=False))
        synced_at = SESSION_SYNCED_AT
    profile = load_profile()
    return {
        "ok": True,
        "state": state,
        "syncedAt": synced_at,
        "profile": profile,
        "profileUpdatedAt": profile.get("updatedAt"),
    }


def enqueue_session_action(action: dict[str, object]) -> dict[str, object]:
    global SESSION_ACTION_COUNTER
    with SESSION_LOCK:
        SESSION_ACTION_COUNTER += 1
        queued = {
            "id": SESSION_ACTION_COUNTER,
            "queuedAt": time.time(),
            **action,
        }
        SESSION_ACTIONS.append(queued)
        del SESSION_ACTIONS[:-SESSION_ACTION_LIMIT]
        return {"ok": True, "action": queued, "pending": len(SESSION_ACTIONS)}


class EasyGeeHandler(QuietHandler):
    def send_json(self, payload: dict[str, object], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        if length > 1_000_000:
            raise ValueError("Request body is too large")
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Request JSON must be an object")
        return payload

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/session/capabilities":
            self.send_json({"ok": True, "contract": load_agent_contract()})
            return
        if parsed.path == "/api/session/profile":
            profile = load_profile()
            self.send_json({"ok": True, "profile": profile, "profileUpdatedAt": profile.get("updatedAt")})
            return
        if parsed.path == "/api/session/state":
            self.send_json(session_state_payload())
            return
        if parsed.path == "/api/session/actions":
            query = urllib.parse.parse_qs(parsed.query)
            try:
                since = int((query.get("since") or ["0"])[0] or "0")
            except Exception:
                since = 0
            with SESSION_LOCK:
                actions = [action for action in SESSION_ACTIONS if int(action.get("id") or 0) > since]
                latest = SESSION_ACTION_COUNTER
            self.send_json({"ok": True, "actions": actions, "latestActionId": latest})
            return
        if parsed.path == "/api/catalog":
            global CATALOG_CACHE
            try:
                if CATALOG_CACHE is None:
                    from create_map_console import build_catalog

                    catalog, source = build_catalog([], include_remote=True)
                    CATALOG_CACHE = {"ok": True, "catalog": catalog, "source": source}
                self.send_json(CATALOG_CACHE)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/session/state":
            try:
                payload = self.read_json()
                state = payload.get("state") if isinstance(payload.get("state"), dict) else payload
                if not isinstance(state, dict):
                    raise ValueError("state must be a JSON object")
                global SESSION_STATE, SESSION_SYNCED_AT
                state_copy = json.loads(json.dumps(state, ensure_ascii=False))
                with SESSION_LOCK:
                    SESSION_STATE = state_copy
                    SESSION_SYNCED_AT = time.time()
                    synced_at = SESSION_SYNCED_AT
                profile = merge_profile_with_state(state_copy)
                self.send_json({"ok": True, "syncedAt": synced_at, "profileUpdatedAt": profile.get("updatedAt")})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if parsed.path == "/api/session/actions":
            try:
                payload = self.read_json()
                action = payload.get("action") if isinstance(payload.get("action"), dict) else payload
                if not isinstance(action, dict):
                    raise ValueError("action must be a JSON object")
                self.send_json(enqueue_session_action(action))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if parsed.path == "/api/layer":
            try:
                from create_map_console import build_catalog_layer

                self.send_json(build_catalog_layer(self.read_json()))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        if parsed.path == "/api/analysis/ndvi":
            try:
                from create_map_console import build_ndvi_analysis

                self.send_json(build_ndvi_analysis(self.read_json()))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        self.send_error(404, "Not Found")


def print_plan(plan: PreviewPlan) -> None:
    print("EasyGEE browser preview")
    print(f"  root: {plan.root}")
    print(f"  target: {plan.target}")
    print(f"  type: {plan.target_type}")
    print(f"  url: {plan.url}")
    if plan.notes:
        print("  notes:")
        for note in plan.notes:
            print(f"    - {note}")
    print("")
    print("Keep this process running while the in-app browser is using the preview.")


def serve(plan: PreviewPlan, host: str, port: int) -> None:
    parsed = urllib.parse.urlparse(plan.url)
    actual_port = port or int(parsed.port or 0)
    handler = functools.partial(EasyGeeHandler, directory=plan.root)
    with ThreadingHTTPServer((host, actual_port), handler) as server:
        print_plan(plan)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nEasyGEE browser preview stopped.")


def smoke() -> int:
    with tempfile.TemporaryDirectory(prefix="easygee-preview-smoke-") as tmp:
        root = Path(tmp)
        configure_profile_path(root / "profile.json")
        plan = build_plan(None, "127.0.0.1", 0, "EasyGEE Smoke", root)
        if not Path(plan.target).exists():
            print("FAIL: placeholder was not created")
            return 1
        if not plan.url.startswith("http://127.0.0.1:"):
            print("FAIL: preview URL was not generated")
            return 1
        sample = root / "map.html"
        sample.write_text("<!doctype html><title>map</title>", encoding="utf-8")
        file_plan = build_plan(sample, "127.0.0.1", 5000, "EasyGEE Smoke", None)
        if file_plan.root != str(root) or not file_plan.url.endswith("/map.html"):
            print("FAIL: file plan is wrong")
            return 1
        contract = load_agent_contract()
        if contract.get("stateEndpoint") != "/api/session/state":
            print("FAIL: agent contract was not loaded")
            return 1
        action_response = enqueue_session_action({"type": "noop"})
        if not action_response.get("ok") or not action_response.get("action", {}).get("id"):
            print("FAIL: session action queue is not working")
            return 1
        profile = merge_profile_with_state(
            {
                "title": "Smoke Map",
                "project": "YOUR_EE_PROJECT",
                "favoriteDatasets": ["COPERNICUS/S2_SR_HARMONIZED"],
                "measurements": [{"id": "m1", "start": [0, 0], "end": [0, 1], "lengthMeters": 1}],
                "sessionReason": "favorites",
            }
        )
        if profile.get("favoriteDatasets") != ["COPERNICUS/S2_SR_HARMONIZED"]:
            print("FAIL: profile favorites were not persisted")
            return 1
        payload = session_state_payload()
        if not isinstance(payload.get("profile"), dict):
            print("FAIL: session state does not include profile")
            return 1
    print("serve_map_preview smoke passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", type=Path, help="HTML file or directory to serve. If omitted, creates a placeholder page.")
    parser.add_argument("--root", type=Path, help="Directory for the generated placeholder page.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="Bind port. Default: choose a free port.")
    parser.add_argument("--title", default="EasyGEE Preview", help="Title for generated placeholder pages.")
    parser.add_argument("--profile", type=Path, help="Persistent Map Console profile JSON path. Defaults to local app data.")
    parser.add_argument("--plan", action="store_true", help="Print the preview plan and exit without starting a server.")
    parser.add_argument("--json", action="store_true", help="Print the preview plan as JSON. Implies --plan.")
    parser.add_argument("--smoke", action="store_true", help="Run offline self-checks.")
    args = parser.parse_args()

    configure_profile_path(args.profile)

    if args.smoke:
        return smoke()

    plan = build_plan(args.target, args.host, args.port, args.title, args.root)
    if args.json:
        print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
        return 0
    if args.plan:
        print_plan(plan)
        return 0
    serve(plan, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
