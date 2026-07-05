#!/usr/bin/env python3
"""Emit compact EasyGEE session context for hook-capable hosts."""

from __future__ import annotations

import json
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PLUGIN_ROOT / "skills" / "easygee"

payload = {
    "hookSpecificOutput": {
        "additionalContext": (
            "EasyGEE is available. For GEE/geemap work, use the easygee skill and "
            "the easygee MCP tools for environment checks, auth planning, catalog "
            "search, quota summaries, and map console generation. Do not print "
            "OAuth tokens, credential files, or service account keys."
        )
    },
    "reloadSkills": SKILL_ROOT.exists(),
}

print(json.dumps(payload, ensure_ascii=False))
