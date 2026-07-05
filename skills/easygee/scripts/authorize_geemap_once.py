#!/usr/bin/env python
"""Run EasyGEE's one-sentence geemap and quota authorization flow.

Default behavior is a dry plan. Passing --run may open the user's browser for
Google OAuth, set the Earth Engine project, verify ee/geemap initialization,
and check Google Cloud quota/usage access. This script never reads credential
files and suppresses OAuth command output so auth URLs, verification codes, and
tokens are not copied into chat or logs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ee_auth_workflow  # noqa: E402
import ensure_gcloud_cli  # noqa: E402
import show_ee_quotas  # noqa: E402


PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


@dataclass(frozen=True)
class Preflight:
    project: str
    python: str
    earthengine_cli: str | None
    gcloud_cli: str | None
    gcloud_active_account_present: bool
    gcloud_configured_project: str | None
    ee_importable: bool
    geemap_importable: bool
    credentials_present: bool
    credential_paths_checked: tuple[str, ...]
    project_id_warning: str | None


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    detail: str


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def build_preflight(project: str) -> Preflight:
    credential_paths = ee_auth_workflow.credential_paths()
    gcloud = show_ee_quotas.find_gcloud()
    warning = None
    if not PROJECT_RE.match(project):
        warning = (
            "Project ID looks unusual. Use the Google Cloud Project ID, not "
            "the project name, project number, OAuth code, token, or auth URL."
        )
    return Preflight(
        project=project,
        python=sys.executable,
        earthengine_cli=(ee_auth_workflow.earthengine_candidates()[0] if ee_auth_workflow.earthengine_candidates() else None),
        gcloud_cli=gcloud,
        gcloud_active_account_present=gcloud_has_active_account(gcloud) if gcloud else False,
        gcloud_configured_project=show_ee_quotas.get_config_project(gcloud) if gcloud else None,
        ee_importable=has_module("ee"),
        geemap_importable=has_module("geemap"),
        credentials_present=any(path.exists() and path.is_file() for path in credential_paths),
        credential_paths_checked=tuple(str(path) for path in credential_paths),
        project_id_warning=warning,
    )


def redact(text: str, limit: int = 600) -> str:
    """Return a short diagnostic excerpt without URLs or token-looking values."""
    redacted = re.sub(r"https?://\S+", "[redacted-url]", text)
    redacted = re.sub(r"(?i)(token|code|secret|credential)[=:]\S+", r"\1=[redacted]", redacted)
    redacted = redacted.strip()
    if len(redacted) > limit:
        redacted = redacted[:limit] + "..."
    return redacted


def print_plan(preflight: Preflight) -> None:
    print("EasyGEE one-sentence geemap authorization + quota readiness")
    print("")
    print("What one sentence can do:")
    print("  The agent can start a browser-based Earth Engine OAuth flow, set the")
    print("  default Earth Engine project, verify that geemap can initialize, and")
    print("  check Google Cloud quota access for total/used/remaining quota status.")
    print("")
    print("What still needs the user:")
    print("  Google requires the account owner to approve OAuth in the browser.")
    print("  Live quota and usage checks require Google Cloud CLI plus project IAM permissions.")
    print("  Do not paste OAuth codes, browser auth URLs, credential files, or tokens into chat.")
    print("")
    print("Planned flow:")
    print("  1. Check this Python environment for earthengine-api, geemap, and earthengine CLI.")
    print("  2. If credentials are missing, launch `earthengine authenticate --auth_mode=localhost`.")
    print("  3. Suppress OAuth command output so auth URLs/codes/tokens are not logged.")
    print("  4. Run `earthengine set_project PROJECT_ID`.")
    print("  5. Verify with `check_gee_geemap.py --project PROJECT_ID --initialize`.")
    print("  6. Check Google Cloud CLI login and set the same Cloud project for quota APIs.")
    print("  7. Probe Cloud Quotas and Cloud Monitoring for quota totals and usage.")
    print("")
    print("Current preflight:")
    print(f"  project: {preflight.project}")
    print(f"  python: {preflight.python}")
    print(f"  earthengine CLI: {preflight.earthengine_cli or 'missing'}")
    print(f"  gcloud CLI: {preflight.gcloud_cli or 'missing'}")
    print(f"  gcloud active account: {'yes' if preflight.gcloud_active_account_present else 'no'}")
    print(f"  gcloud configured project: {preflight.gcloud_configured_project or 'none'}")
    print(f"  earthengine-api importable: {'yes' if preflight.ee_importable else 'no'}")
    print(f"  geemap importable: {'yes' if preflight.geemap_importable else 'no'}")
    print(f"  credential file present: {'yes' if preflight.credentials_present else 'no'}")
    if preflight.project_id_warning:
        print(f"  project warning: {preflight.project_id_warning}")
    print("")
    print("Run command when the user explicitly asks to proceed:")
    print(
        f"  {ee_auth_workflow.powershell_call(sys.executable, str(Path(__file__).resolve()), '--project', preflight.project, '--run', '--quota-mode', 'required')}"
    )


def preflight_errors(preflight: Preflight) -> list[str]:
    errors: list[str] = []
    if not preflight.ee_importable:
        errors.append("earthengine-api is not importable in this Python.")
    if not preflight.geemap_importable:
        errors.append("geemap is not importable in this Python.")
    if not preflight.earthengine_cli:
        errors.append("earthengine CLI is missing from this Python environment or PATH.")
    return errors


def run_gcloud(gcloud: str, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        show_ee_quotas.subprocess_command(gcloud, args),
        env=show_ee_quotas.gcloud_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )


def gcloud_has_active_account(gcloud: str | None) -> bool:
    if not gcloud:
        return False
    try:
        result = run_gcloud(gcloud, ["config", "get-value", "account", "--quiet"], timeout=20)
    except Exception:
        return False
    account = result.stdout.strip()
    if result.returncode != 0 or not account or account == "(unset)":
        return False
    try:
        token_result = run_gcloud(gcloud, ["auth", "print-access-token"], timeout=30)
    except Exception:
        return False
    return token_result.returncode == 0 and bool(token_result.stdout.strip())


def run_gcloud_auth(preflight: Preflight, args: argparse.Namespace) -> StepResult:
    if args.quota_mode == "skip":
        return StepResult("cloud-auth", True, "skipped by --quota-mode=skip")
    if not preflight.gcloud_cli:
        return StepResult(
            "cloud-auth",
            args.quota_mode not in {"required", "required-usage"},
            "Google Cloud CLI is missing; install gcloud to read live quota totals, usage, and remaining values",
        )
    if preflight.gcloud_active_account_present and not args.force_gcloud_auth:
        return StepResult("cloud-auth", True, "valid gcloud credentials already present")
    print("[wait] Opening Google Cloud CLI login in the browser if needed. Approve access there; do not paste codes or URLs here.")
    try:
        result = subprocess.run(
            show_ee_quotas.subprocess_command(preflight.gcloud_cli, ["auth", "login", "--brief", "--quiet"]),
            env=show_ee_quotas.gcloud_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        return StepResult("cloud-auth", False, f"timed out after {args.timeout} seconds waiting for gcloud browser login")
    return StepResult(
        "cloud-auth",
        result.returncode == 0,
        "gcloud login completed" if result.returncode == 0 else f"gcloud login exited with code {result.returncode}",
    )


def run_gcloud_project(preflight: Preflight, args: argparse.Namespace) -> StepResult:
    if args.quota_mode == "skip":
        return StepResult("cloud-project", True, "skipped by --quota-mode=skip")
    if not preflight.gcloud_cli:
        return StepResult("cloud-project", args.quota_mode not in {"required", "required-usage"}, "Google Cloud CLI is missing")
    try:
        result = run_gcloud(preflight.gcloud_cli, ["config", "set", "project", preflight.project, "--quiet"], timeout=30)
    except subprocess.TimeoutExpired:
        return StepResult("cloud-project", False, "gcloud config set project timed out")
    if result.returncode == 0:
        return StepResult("cloud-project", True, f"gcloud project set to {preflight.project}")
    detail = f"gcloud config set project exited with code {result.returncode}"
    if args.verbose:
        detail += ": " + redact(result.stderr or result.stdout)
    return StepResult("cloud-project", False, detail)


def run_quota_probe(preflight: Preflight, args: argparse.Namespace) -> StepResult:
    if args.quota_mode == "skip":
        return StepResult("quota-probe", True, "skipped by --quota-mode=skip")
    if not preflight.gcloud_cli:
        return StepResult("quota-probe", args.quota_mode not in {"required", "required-usage"}, "Google Cloud CLI is missing")
    report_args = argparse.Namespace(
        project=preflight.project,
        console_url=None,
        service=None,
        no_live=False,
        include_usage=not args.no_quota_usage,
        minutes=args.quota_minutes,
    )
    report = show_ee_quotas.build_report(report_args)
    if report.live_quotas and report.usage_rows:
        return StepResult(
            "quota-probe",
            True,
            f"live quota totals and usage available ({len(report.live_quotas)} limits, {len(report.usage_rows)} usage rows)",
        )
    if report.live_quotas:
        detail = f"live quota totals available via {report.live_source}; usage/remaining not available from Cloud Monitoring"
        if report.warnings and args.verbose:
            detail += ": " + redact("; ".join(report.warnings))
        return StepResult("quota-probe", args.quota_mode != "required-usage", detail)
    detail = "live quota totals unavailable; official defaults would not show true remaining quota"
    if report.warnings:
        detail += ": " + redact("; ".join(report.warnings))
    return StepResult("quota-probe", args.quota_mode not in {"required", "required-usage"}, detail)


def run_auth(preflight: Preflight, timeout: int, force_auth: bool) -> StepResult:
    if preflight.credentials_present and not force_auth:
        return StepResult("authenticate", True, "credentials already present; skipped OAuth")
    if not preflight.earthengine_cli:
        return StepResult("authenticate", False, "earthengine CLI is missing")
    command = [preflight.earthengine_cli, "authenticate", "--auth_mode=localhost"]
    print("[wait] Opening Google OAuth in the browser. Approve access there; do not paste codes or URLs here.")
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return StepResult("authenticate", False, f"timed out after {timeout} seconds waiting for browser OAuth")
    return StepResult(
        "authenticate",
        result.returncode == 0,
        "OAuth command completed" if result.returncode == 0 else f"OAuth command exited with code {result.returncode}",
    )


def run_set_project(preflight: Preflight, verbose: bool) -> StepResult:
    if not preflight.earthengine_cli:
        return StepResult("set-project", False, "earthengine CLI is missing")
    result = subprocess.run(
        [preflight.earthengine_cli, "set_project", preflight.project],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode == 0:
        return StepResult("set-project", True, f"default project set to {preflight.project}")
    detail = f"set_project exited with code {result.returncode}"
    if verbose:
        detail += ": " + redact(result.stderr or result.stdout)
    return StepResult("set-project", False, detail)


def run_verify(preflight: Preflight, verbose: bool) -> StepResult:
    checker = SCRIPT_DIR / "check_gee_geemap.py"
    result = subprocess.run(
        [sys.executable, "-B", str(checker), "--project", preflight.project, "--initialize"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode == 0:
        return StepResult("verify", True, "ee.Initialize(...) succeeded for geemap workflows")
    detail = f"verification exited with code {result.returncode}"
    if verbose:
        detail += ": " + redact((result.stdout + "\n" + result.stderr).strip())
    return StepResult("verify", False, detail)


def run_flow(args: argparse.Namespace) -> list[StepResult]:
    preflight = build_preflight(args.project)
    errors = preflight_errors(preflight)
    if errors:
        return [StepResult("preflight", False, "; ".join(errors))]
    results: list[StepResult] = []
    if not args.skip_auth:
        results.append(run_auth(preflight, timeout=args.timeout, force_auth=args.force_auth))
        if not results[-1].ok:
            return results
    results.append(run_set_project(preflight, verbose=args.verbose))
    if not results[-1].ok:
        return results
    results.append(run_verify(preflight, verbose=args.verbose))
    if not results[-1].ok:
        return results
    if args.quota_mode != "skip" and not preflight.gcloud_cli:
        install = ensure_gcloud_cli.install_from_archive(
            ensure_gcloud_cli.default_fixed_root(),
            ensure_gcloud_cli.default_cache_dir(),
            ensure_gcloud_cli.WINDOWS_ARCHIVE_URL,
            timeout=args.timeout,
        )
        results.append(StepResult(install.name, install.ok, install.detail))
        preflight = build_preflight(args.project)
        if not install.ok and args.quota_mode in {"required", "required-usage"}:
            return results
    results.append(run_gcloud_auth(preflight, args))
    if not results[-1].ok:
        return results
    results.append(run_gcloud_project(preflight, args))
    if not results[-1].ok:
        return results
    results.append(run_quota_probe(preflight, args))
    return results


def print_results(results: list[StepResult]) -> None:
    print("EasyGEE geemap authorization run")
    for result in results:
        prefix = "ok" if result.ok else "fail"
        print(f"[{prefix}] {result.name}: {result.detail}")
    if all(result.ok for result in results):
        print("")
        print("Done. geemap can now use Earth Engine layers after ee.Initialize(project=...).")
        print("Quota access was checked in the same flow; see quota-probe for live usage availability.")
    else:
        print("")
        print("Stopped before completion. No credential contents were read or printed.")


def smoke() -> int:
    preflight = build_preflight("demo-project")
    plan = {
        "project": preflight.project,
        "credential_paths_checked": preflight.credential_paths_checked,
        "run_flag_required": True,
        "oauth_output_suppressed": True,
        "quota_mode_supported": True,
    }
    if plan["project"] != "demo-project" or not plan["credential_paths_checked"]:
        print("authorize_geemap_once smoke failed")
        return 1
    print("authorize_geemap_once smoke passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Earth Engine / Google Cloud project id")
    parser.add_argument("--run", action="store_true", help="Launch OAuth if needed, set project, and verify")
    parser.add_argument("--skip-auth", action="store_true", help="Only set the project and verify existing credentials")
    parser.add_argument("--force-auth", action="store_true", help="Run browser OAuth even if a credential file is present")
    parser.add_argument(
        "--quota-mode",
        choices=["auto", "skip", "required", "required-usage"],
        default="auto",
        help="Also configure/check Google Cloud quota access. required fails if live quota totals are unavailable; required-usage also requires Monitoring usage rows.",
    )
    parser.add_argument("--no-quota-usage", action="store_true", help="Do not query Cloud Monitoring usage during quota probe")
    parser.add_argument("--quota-minutes", type=int, default=60, help="Cloud Monitoring usage lookback window")
    parser.add_argument("--force-gcloud-auth", action="store_true", help="Run gcloud auth login even when an active gcloud account is present")
    parser.add_argument("--timeout", type=int, default=900, help="Seconds to wait for browser OAuth when --run is used")
    parser.add_argument("--verbose", action="store_true", help="Show sanitized diagnostics for failed non-OAuth steps")
    parser.add_argument("--json", action="store_true", help="Emit JSON for plan or run results")
    parser.add_argument("--smoke", action="store_true", help="Offline self-test; does not open OAuth")
    args = parser.parse_args()

    if args.smoke:
        return smoke()
    if not args.project:
        parser.error("--project is required unless --smoke is used")
    if args.skip_auth and args.force_auth:
        parser.error("--skip-auth and --force-auth cannot be used together")
    if args.no_quota_usage and args.quota_mode == "required-usage":
        parser.error("--quota-mode required-usage cannot be combined with --no-quota-usage")

    preflight = build_preflight(args.project)
    if not args.run:
        if args.json:
            print(json.dumps({"preflight": asdict(preflight), "run_required": False}, ensure_ascii=False, indent=2))
        else:
            print_plan(preflight)
        return 0

    results = run_flow(args)
    if args.json:
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    else:
        print_results(results)
    return 0 if results and all(result.ok for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
