#!/usr/bin/env python
"""Resolve and persist EasyGEE's user-level Earth Engine project.

Project ids are user-local configuration, not repository state. This helper
prefers explicit values, then local environment/configuration, and never reads
or prints credential file contents.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_PROJECT = "YOUR_EE_PROJECT"
PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
IGNORED_PROJECTS = {DEFAULT_PROJECT, "earthengine-legacy", "(unset)", "unset", "none", "null"}
ENV_PROJECT_KEYS = (
    "EASYGEE_PROJECT",
    "EARTHENGINE_PROJECT",
    "GOOGLE_CLOUD_PROJECT",
    "GCLOUD_PROJECT",
    "CLOUDSDK_CORE_PROJECT",
)


@dataclass(frozen=True)
class ResolvedProject:
    project: str
    source: str
    settings_path: str
    remembered: bool = False


def is_concrete_project(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text and text not in IGNORED_PROJECTS and PROJECT_RE.match(text))


def local_app_data_root() -> Path:
    explicit = os.environ.get("EASYGEE_USER_CONFIG_DIR")
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "EasyGEE"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "easygee"


def settings_path() -> Path:
    explicit = os.environ.get("EASYGEE_SETTINGS")
    if explicit:
        return Path(explicit).expanduser()
    return local_app_data_root() / "settings.json"


def load_settings(path: Path | None = None) -> dict[str, Any]:
    target = path or settings_path()
    if not target.exists():
        return {"version": 1}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1}
    return payload if isinstance(payload, dict) else {"version": 1}


def save_settings(payload: dict[str, Any], path: Path | None = None) -> None:
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["version"] = 1
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def remember_project(project: str, source: str = "manual", path: Path | None = None) -> ResolvedProject:
    project = str(project or "").strip()
    if not is_concrete_project(project):
        raise ValueError("A concrete Google Cloud / Earth Engine project id is required")
    target = path or settings_path()
    settings = load_settings(target)
    settings["earthEngineProject"] = project
    settings["earthEngineProjectSource"] = source
    settings["earthEngineProjectUpdatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_settings(settings, target)
    return ResolvedProject(project=project, source=source, settings_path=str(target), remembered=True)


def project_from_explicit(value: object) -> ResolvedProject | None:
    if is_concrete_project(value):
        return ResolvedProject(str(value).strip(), "explicit", str(settings_path()))
    return None


def project_from_env() -> ResolvedProject | None:
    for key in ENV_PROJECT_KEYS:
        value = os.environ.get(key)
        if is_concrete_project(value):
            return ResolvedProject(str(value).strip(), f"env:{key}", str(settings_path()))
    return None


def project_from_settings() -> ResolvedProject | None:
    payload = load_settings()
    project = payload.get("earthEngineProject") or payload.get("project")
    if is_concrete_project(project):
        return ResolvedProject(str(project).strip(), "easygee-settings", str(settings_path()))
    return None


def project_from_earthengine_api() -> ResolvedProject | None:
    try:
        import ee  # type: ignore
        import ee.data  # type: ignore

        ee.Initialize()
        project = getattr(ee.data._get_state(), "cloud_api_user_project", None)
    except Exception:
        return None
    if is_concrete_project(project):
        return ResolvedProject(str(project).strip(), "earthengine-default", str(settings_path()))
    return None


def gcloud_candidates() -> list[str]:
    candidates: list[str] = []
    env_gcloud = os.environ.get("EASYGEE_GCLOUD")
    if env_gcloud:
        candidates.append(env_gcloud)
    if os.name == "nt":
        candidates.extend(
            [
                r"D:\Dev\tools\google-cloud-sdk\bin\gcloud.cmd",
                r"D:\Dev\tools\google-cloud-sdk\bin\gcloud",
            ]
        )
    which = shutil.which("gcloud")
    if which:
        candidates.append(which)
    seen: set[str] = set()
    result: list[str] = []
    for item in candidates:
        text = str(item)
        if text and text not in seen and Path(text).exists():
            seen.add(text)
            result.append(text)
    return result


def project_from_gcloud() -> ResolvedProject | None:
    for gcloud in gcloud_candidates():
        try:
            result = subprocess.run(
                [gcloud, "config", "get-value", "project", "--quiet"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=20,
            )
        except Exception:
            continue
        project = (result.stdout or "").strip().splitlines()[-1:] or [""]
        if result.returncode == 0 and is_concrete_project(project[0]):
            return ResolvedProject(project[0], "gcloud-config", str(settings_path()))
    return None


def resolve_project(explicit: object = None, remember_discovered: bool = True) -> ResolvedProject:
    for resolver in (
        lambda: project_from_explicit(explicit),
        project_from_env,
        project_from_settings,
        project_from_earthengine_api,
        project_from_gcloud,
    ):
        resolved = resolver()
        if resolved:
            if remember_discovered and resolved.source not in {"explicit", "easygee-settings"}:
                try:
                    return remember_project(resolved.project, source=resolved.source)
                except Exception:
                    return resolved
            return resolved
    return ResolvedProject(DEFAULT_PROJECT, "placeholder", str(settings_path()))


def smoke() -> int:
    with TemporarySettings() as path:
        if is_concrete_project(DEFAULT_PROJECT) or is_concrete_project("earthengine-legacy"):
            print("easygee_project smoke failed")
            return 1
        remembered = remember_project("demo-project", source="smoke", path=path)
        loaded = load_settings(path)
        if remembered.project != "demo-project" or loaded.get("earthEngineProject") != "demo-project":
            print("easygee_project smoke failed")
            return 1
    print("easygee_project smoke passed")
    return 0


class TemporarySettings:
    def __enter__(self) -> Path:
        import tempfile

        self._dir = tempfile.TemporaryDirectory(prefix="easygee-project-")
        self.path = Path(self._dir.name) / "settings.json"
        return self.path

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._dir.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve", help="Resolve the current user-level project.")
    resolve.add_argument("--project", help="Explicit project override")
    resolve.add_argument("--no-remember", action="store_true", help="Do not write discovered env/CLI defaults to settings")
    resolve.add_argument("--json", action="store_true")

    remember = subparsers.add_parser("remember", help="Persist a project id to user-level EasyGEE settings.")
    remember.add_argument("--project", required=True)
    remember.add_argument("--source", default="manual")
    remember.add_argument("--json", action="store_true")

    path_cmd = subparsers.add_parser("path", help="Print the user-level settings path.")
    path_cmd.add_argument("--json", action="store_true")

    subparsers.add_parser("smoke", help="Run offline self-checks.")
    args = parser.parse_args()

    if args.command == "smoke":
        return smoke()
    if args.command == "resolve":
        resolved = resolve_project(args.project, remember_discovered=not args.no_remember)
        payload = asdict(resolved)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(resolved.project)
        return 0 if resolved.project != DEFAULT_PROJECT else 2
    if args.command == "remember":
        resolved = remember_project(args.project, source=args.source)
        payload = asdict(resolved)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"remembered {resolved.project}")
        return 0
    if args.command == "path":
        payload = {"settingsPath": str(settings_path())}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(payload["settingsPath"])
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
