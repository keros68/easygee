#!/usr/bin/env python
"""Check local Google Earth Engine and geemap readiness without exposing secrets."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import shutil
import sys
from pathlib import Path

import easygee_project


PACKAGES = [
    ("ee", "earthengine-api"),
    ("geemap", "geemap"),
    ("ipyleaflet", "ipyleaflet"),
    ("eerepr", "eerepr"),
]


def package_status(module_name: str, dist_name: str) -> dict:
    spec = importlib.util.find_spec(module_name)
    version = None
    if spec is not None:
        try:
            version = importlib.metadata.version(dist_name)
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
    return {
        "module": module_name,
        "distribution": dist_name,
        "installed": spec is not None,
        "version": version,
        "origin": getattr(spec, "origin", None) if spec is not None else None,
    }


def credential_paths() -> list[dict]:
    home = Path.home()
    candidates = [
        home / ".config" / "earthengine" / "credentials",
        Path(os.environ.get("APPDATA", "")) / "earthengine" / "credentials",
    ]
    seen = set()
    rows = []
    for path in candidates:
        if not str(path) or path in seen:
            continue
        seen.add(path)
        rows.append({
            "path": str(path),
            "exists": path.exists(),
            "is_file": path.is_file(),
        })
    return rows


def earthengine_cli() -> str | None:
    candidates = []
    scripts_dir = Path(sys.executable).resolve().parent
    for name in ("earthengine.exe", "earthengine"):
        path = scripts_dir / name
        if path.exists():
            candidates.append(str(path))
    which = shutil.which("earthengine")
    if which:
        candidates.append(which)
    return candidates[0] if candidates else None


def try_initialize(project: str | None) -> dict:
    try:
        import ee
    except Exception as exc:  # pragma: no cover - diagnostic script
        return {"ok": False, "error": f"import ee failed: {type(exc).__name__}: {exc}"}

    try:
        if project:
            ee.Initialize(project=project)
        else:
            ee.Initialize()
        return {"ok": True, "project": project}
    except Exception as exc:  # pragma: no cover - depends on user auth
        message = str(exc)
        if len(message) > 500:
            message = message[:500] + "..."
        return {"ok": False, "project": project, "error": f"{type(exc).__name__}: {message}"}


def build_report(args: argparse.Namespace) -> dict:
    resolved_project = easygee_project.resolve_project(args.project, remember_discovered=False)
    report = {
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "packages": [package_status(*pkg) for pkg in PACKAGES],
        "earthengine_cli": earthengine_cli(),
        "credential_paths": credential_paths(),
        "resolved_project": {
            "project": resolved_project.project,
            "source": resolved_project.source,
            "settings_path": resolved_project.settings_path,
        },
    }
    if args.initialize:
        project = resolved_project.project if easygee_project.is_concrete_project(resolved_project.project) else args.project
        report["initialize"] = try_initialize(project)
    return report


def print_text(report: dict) -> None:
    print(f"Python: {report['python']} ({report['python_version']})")
    print("Packages:")
    for row in report["packages"]:
        status = "ok" if row["installed"] else "missing"
        version = row["version"] or "-"
        print(f"  - {row['distribution']}: {status} {version}")
    cli = report["earthengine_cli"] or "missing"
    print(f"Earth Engine CLI: {cli}")
    print("Credential files:")
    for row in report["credential_paths"]:
        status = "exists" if row["exists"] else "missing"
        print(f"  - {row['path']}: {status}")
    resolved = report.get("resolved_project") or {}
    print(f"Resolved project: {resolved.get('project') or 'none'} ({resolved.get('source') or 'none'})")
    if "initialize" in report:
        init = report["initialize"]
        print(f"Initialize: {'ok' if init['ok'] else 'failed'}")
        if not init["ok"]:
            print(f"  {init['error']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Earth Engine / Google Cloud project id")
    parser.add_argument(
        "--initialize",
        action="store_true",
        help="Try ee.Initialize(); does not run ee.Authenticate()",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    report = build_report(args)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_text(report)

    if args.initialize and not report.get("initialize", {}).get("ok", False):
        return 2
    missing_required = [p for p in report["packages"] if p["distribution"] in {"earthengine-api", "geemap"} and not p["installed"]]
    return 1 if missing_required else 0


if __name__ == "__main__":
    raise SystemExit(main())
