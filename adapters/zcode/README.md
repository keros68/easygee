# Zcode Adapter

Zcode has MCP-oriented config under `C:\Users\Liang\.zcode\v2\config.json`.

This adapter provides `mcp-config.example.json` as a safe merge reference instead of editing the live config automatically. Merge only the `easygee` MCP server and `easygee_*` tool entries, preserving existing providers, credentials, permissions, and other MCP servers.

The EasyGEE MCP entry runs:

```text
C:\Users\Liang\plugins\easygee\scripts\run-easygee-mcp.ps1
```
