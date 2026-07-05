#!/usr/bin/env python
"""Print a credential-safe geemap authorization workflow.

geemap uses the Earth Engine Python API for authentication. This wrapper gives
agents and users a geemap-named entrypoint while reusing the same safe
Earth Engine OAuth/project initialization workflow.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ee_auth_workflow  # noqa: E402


def geemap_snippet(mode: str, project: str | None, include_auth: bool) -> str:
    project_expr = repr(project or "YOUR_EE_PROJECT")
    lines = ["import ee", "import geemap", ""]
    if include_auth:
        if mode in {"localhost", "notebook", "gcloud", "colab"}:
            lines.append(f"ee.Authenticate(auth_mode={mode!r})")
        else:
            lines.append("ee.Authenticate()")
    else:
        lines.append("# Run authentication once during setup if credentials are missing.")
    lines.extend(
        [
            f"ee.Initialize(project={project_expr})",
            "m = geemap.Map()",
            "m.add_basemap('SATELLITE')",
            "m",
        ]
    )
    return "\n".join(lines)


def print_text(plan: ee_auth_workflow.AuthPlan, include_auth: bool) -> None:
    print("geemap authorization workflow")
    print("")
    print("How geemap authorization works:")
    print("  geemap does not keep separate Google credentials. It uses the Earth Engine Python API.")
    print("  Authorize once with Earth Engine OAuth, then initialize every geemap notebook/script with ee.Initialize(project='...').")
    print("")
    print("Environment:")
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
    print("geemap notebook setup snippet:")
    print(geemap_snippet(plan.mode, plan.project, include_auth=include_auth))
    print("")
    print("Verification commands:")
    for command in plan.verify_commands:
        print(f"  {command}")
    print("")
    print("Cautions:")
    for caution in plan.cautions:
        print(f"  - {caution}")
    print("  - Do not paste OAuth codes, browser auth URLs, credential files, service account keys, or tokens into chat.")
    print("  - geemap maps can render local basemaps before EE auth, but Earth Engine layers require a successful ee.Initialize(...).")
    print("")
    print("Official links:")
    for link in plan.official_links:
        print(f"  - {link}")


def smoke() -> int:
    for mode in ee_auth_workflow.AUTH_MODES:
        args = argparse.Namespace(mode=mode, project="demo-project", include_auth_snippet=False)
        plan = ee_auth_workflow.build_plan(args)
        text = geemap_snippet(plan.mode, plan.project, include_auth=True)
        if "import geemap" not in text or "ee.Initialize(project='demo-project')" not in text:
            print(f"FAIL {mode}: geemap snippet missing expected setup")
            return 1
        if "Project ID" not in plan.required_input:
            print(f"FAIL {mode}: onboarding guidance missing")
            return 1
    print(f"geemap_auth_workflow smoke passed: {len(ee_auth_workflow.AUTH_MODES)} modes")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Earth Engine / Google Cloud project id")
    parser.add_argument("--mode", choices=ee_auth_workflow.AUTH_MODES, default="auto")
    parser.add_argument(
        "--include-auth-snippet",
        action="store_true",
        help="Include ee.Authenticate(...) in the geemap snippet. Keep off for reusable scripts.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        return smoke()

    plan = ee_auth_workflow.build_plan(args)
    if args.json:
        payload = asdict(plan)
        payload["geemap_auth_explanation"] = "geemap uses earthengine-api OAuth; initialize with ee.Initialize(project=...) before adding Earth Engine layers."
        payload["geemap_setup"] = geemap_snippet(plan.mode, plan.project, include_auth=args.include_auth_snippet)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text(plan, include_auth=args.include_auth_snippet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
