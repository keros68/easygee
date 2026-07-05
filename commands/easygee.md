---
description: Route a Google Earth Engine / geemap request through EasyGEE
argument-hint: <task>
allowed-tools: Read, Glob, Grep, Bash, PowerShell, mcp__easygee__easygee_check_environment, mcp__easygee__easygee_search_catalog, mcp__easygee__easygee_quota_summary, mcp__easygee__easygee_create_map_console
---

Use the EasyGEE skill for this request. Route the task first:

1. Use the EasyGEE interaction router for non-trivial requests.
2. Use the EasyGEE MCP tools when environment, catalog, quota, or map-console operations are needed.
3. Keep browser work map-first only when the user asks to see, inspect, draw, annotate, or compare map state.

User request:

```
$ARGUMENTS
```
