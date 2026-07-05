#!/usr/bin/env python3
"""Reserved EasyGEE stop hook."""

from __future__ import annotations

import json

print(json.dumps({"hookSpecificOutput": {"additionalContext": ""}}, ensure_ascii=False))
