#!/usr/bin/env python
"""Print a credential-safe Earth Engine authentication workflow.

The default behavior is advisory and non-interactive. It does not run OAuth,
open a browser, read credential files, or print tokens. The user should run the
printed authentication command in their own terminal/session.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


AUTH_MODES = ("auto", "localhost", "notebook", "gcloud", "colab", "service-account")


@dataclass(frozen=True)
class AuthPlan:
    mode: str
    project: str | None
    python: str
    earthengine_cli: str | None
    gcloud_cli: str | None
    credentials_present: bool
    required_input: str
    onboarding_steps: tuple[str, ...]
    official_links: tuple[str, ...]
    steps: tuple[str, ...]
    python_setup: str
    verify_commands: tuple[str, ...]
    cautions: tuple[str, ...]


def quote_ps(path: str) -> str:
    return "'" + path.replace("'", "''") + "'"


def powershell_call(executable: str | None, *args: str) -> str:
    exe = executable or "earthengine"
    if any(ch in exe for ch in (" ", "(", ")", "&")) or ":" in exe or "\\" in exe or "/" in exe:
        head = "& " + quote_ps(exe)
    else:
        head = exe
    return " ".join([head, *args])


def earthengine_candidates() -> list[str]:
    candidates: list[str] = []
    scripts_dir = Path(sys.executable).resolve().parent
    for name in ("earthengine.exe", "earthengine"):
        path = scripts_dir / name
        if path.exists():
            candidates.append(str(path))
    which = shutil.which("earthengine")
    if which:
        candidates.append(which)
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(Path(candidate)).casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return deduped


def credential_paths() -> list[Path]:
    home = Path.home()
    paths = [home / ".config" / "earthengine" / "credentials"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "earthengine" / "credentials")
    return paths


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def choose_mode(requested: str) -> str:
    if requested != "auto":
        return requested
    if os.environ.get("COLAB_RELEASE_TAG"):
        return "colab"
    if shutil.which("gcloud"):
        return "gcloud"
    return "localhost"


def python_setup_snippet(mode: str, project: str | None, include_auth: bool) -> str:
    project_expr = repr(project or "YOUR_EE_PROJECT")
    lines = ["import ee"]
    if include_auth:
        if mode == "auto":
            lines.append("ee.Authenticate()")
        elif mode in {"localhost", "notebook", "gcloud", "colab"}:
            lines.append(f"ee.Authenticate(auth_mode={mode!r})")
        else:
            lines.append("# Service account credentials should be passed explicitly; do not commit key files.")
    lines.append(f"ee.Initialize(project={project_expr})")
    lines.append("print(ee.String('Hello from the Earth Engine servers!').getInfo())")
    return "\n".join(lines)


def build_steps(mode: str, project: str | None, ee_cli: str | None) -> tuple[str, ...]:
    project_token = project or "YOUR_EE_PROJECT"
    if mode == "localhost":
        return (
            powershell_call(ee_cli, "authenticate", "--auth_mode=localhost"),
            powershell_call(ee_cli, "set_project", project_token),
            powershell_call(ee_cli, "--project", project_token, "ls"),
        )
    if mode == "gcloud":
        return (
            "gcloud auth application-default login",
            powershell_call(ee_cli, "authenticate", "--auth_mode=gcloud"),
            f"gcloud auth application-default set-quota-project {project_token}",
            powershell_call(ee_cli, "set_project", project_token),
            powershell_call(ee_cli, "--project", project_token, "ls"),
        )
    if mode == "notebook":
        return (
            "Run the Python setup snippet in a notebook and complete the browser/token prompt.",
            "Use an authentication project where you are Owner, Editor, or OAuth Config Editor.",
            "Then run the verification snippet or check_gee_geemap.py command below.",
        )
    if mode == "colab":
        return (
            "Run the Python setup snippet in Colab; ee.Authenticate(auth_mode='colab') will use Colab auth.",
            "Initialize with the Earth Engine project you own or can use.",
        )
    if mode == "service-account":
        return (
            "Use service accounts only for unattended apps/REST/VM workflows.",
            "Keep JSON keys out of repos; prefer managed runtime secrets or default service accounts.",
            "Pass credentials explicitly to ee.Initialize(credentials=..., project=...).",
        )
    return (
        "Run ee.Authenticate() once in an interactive setup cell or earthengine authenticate in a terminal.",
        "Then initialize every notebook/script with ee.Initialize(project='YOUR_EE_PROJECT').",
    )


def build_plan(args: argparse.Namespace) -> AuthPlan:
    ee_cli = earthengine_candidates()[0] if earthengine_candidates() else None
    mode = choose_mode(args.mode)
    project = args.project
    credentials_present = any(path.exists() and path.is_file() for path in credential_paths())
    verify_commands = (
        powershell_call(sys.executable, str(Path(__file__).resolve()), "--project", project or "YOUR_EE_PROJECT", "--mode", mode),
        powershell_call(sys.executable, str(Path(__file__).with_name("check_gee_geemap.py")), "--project", project or "YOUR_EE_PROJECT", "--initialize"),
    )
    cautions = (
        "Do not print, paste into chat, or commit OAuth tokens, credential files, service account keys, or browser auth URLs.",
        "Use ee.Initialize(project='...') in every reusable notebook/script; do not rely on an implicit project.",
        "Do not run authentication from a headless script unless the user explicitly asked for an interactive setup step.",
        "If initialization fails with an API-disabled or quota-project error, enable Earth Engine API on the selected Cloud project and verify IAM permissions.",
    )
    if not has_module("ee"):
        cautions += ("earthengine-api is not importable in this Python; install or switch environments before authenticating.",)
    if not has_module("geemap"):
        cautions += ("geemap is not importable in this Python; install it before geemap notebook work.",)

    required_input = "Earth Engine / Google Cloud Project ID, for example my-gee-project-123456. Do not send project name, project number, OAuth tokens, verification codes, credential files, or auth URLs."
    onboarding_steps = (
        "Sign in or register Earth Engine access at https://earthengine.google.com/signup/.",
        "Open Google Cloud Console at https://console.cloud.google.com/ and use the project selector to create or choose a project.",
        "Copy the Project ID from the project selector or project dashboard. It is not the project name or project number.",
        "Enable the Earth Engine API for that project at https://console.cloud.google.com/apis/library/earthengine.googleapis.com.",
        "Open https://console.cloud.google.com/earth-engine/configuration and confirm the project is registered for commercial or noncommercial Earth Engine access.",
        "Send the agent only the Project ID; keep all credentials and OAuth browser URLs private.",
    )
    official_links = (
        "Earth Engine signup: https://earthengine.google.com/signup/",
        "Earth Engine access and registration: https://developers.google.com/earth-engine/guides/access",
        "Google Cloud Console project selector: https://console.cloud.google.com/",
        "Enable Earth Engine API: https://console.cloud.google.com/apis/library/earthengine.googleapis.com",
        "Earth Engine project configuration: https://console.cloud.google.com/earth-engine/configuration",
        "Python authentication and initialization: https://developers.google.com/earth-engine/guides/auth",
        "Service accounts, when needed: https://developers.google.com/earth-engine/guides/service_account",
    )
    return AuthPlan(
        mode=mode,
        project=project,
        python=sys.executable,
        earthengine_cli=ee_cli,
        gcloud_cli=shutil.which("gcloud"),
        credentials_present=credentials_present,
        required_input=required_input,
        onboarding_steps=onboarding_steps,
        official_links=official_links,
        steps=build_steps(mode, project, ee_cli),
        python_setup=python_setup_snippet(mode, project, include_auth=args.include_auth_snippet),
        verify_commands=verify_commands,
        cautions=cautions,
    )


def print_text(plan: AuthPlan) -> None:
    print("Earth Engine auth workflow")
    print(f"  mode: {plan.mode}")
    print(f"  project: {plan.project or 'YOUR_EE_PROJECT'}")
    print(f"  python: {plan.python}")
    print(f"  earthengine CLI: {plan.earthengine_cli or 'missing'}")
    print(f"  gcloud CLI: {plan.gcloud_cli or 'missing'}")
    print(f"  credential file present: {'yes' if plan.credentials_present else 'no'}")
    print("")
    print("Required input from user:")
    print(f"  {plan.required_input}")
    print("")
    print("Where to get it:")
    for index, step in enumerate(plan.onboarding_steps, start=1):
        print(f"  {index}. {step}")
    print("")
    print("User-run setup steps:")
    for index, step in enumerate(plan.steps, start=1):
        print(f"  {index}. {step}")
    print("")
    print("Notebook/script setup snippet:")
    print(plan.python_setup)
    print("")
    print("Verification commands:")
    for command in plan.verify_commands:
        print(f"  {command}")
    print("")
    print("Cautions:")
    for caution in plan.cautions:
        print(f"  - {caution}")
    print("")
    print("Official links:")
    for link in plan.official_links:
        print(f"  - {link}")


def smoke() -> int:
    for mode in AUTH_MODES:
        plan = build_plan(argparse.Namespace(mode=mode, project="demo-project", include_auth_snippet=True))
        if not plan.steps or "demo-project" not in "\n".join(plan.steps + (plan.python_setup,)):
            print(f"FAIL {mode}: project missing from plan")
            return 1
        if "Project ID" not in plan.required_input or "earthengine.googleapis.com" not in "\n".join(plan.official_links):
            print(f"FAIL {mode}: onboarding guidance missing")
            return 1
    print(f"ee_auth_workflow smoke passed: {len(AUTH_MODES)} modes")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Earth Engine / Google Cloud project id")
    parser.add_argument("--mode", choices=AUTH_MODES, default="auto")
    parser.add_argument(
        "--include-auth-snippet",
        action="store_true",
        help="Include ee.Authenticate(...) in the printed Python snippet. Keep off for reusable scripts.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        return smoke()

    plan = build_plan(args)
    if args.json:
        print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
    else:
        print_text(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
