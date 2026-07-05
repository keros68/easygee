<div align="center">
  <img src="./assets/logo.png" alt="EasyGEE" width="96" />
  <h1>EasyGEE</h1>

  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-0F766E?style=flat-square" /></a>
  <a href="./.codex-plugin/plugin.json"><img alt="Plugin" src="https://img.shields.io/badge/plugin-Codex%20%7C%20Claude-2563EB?style=flat-square" /></a>
  <a href="./.mcp.json"><img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-111827?style=flat-square" /></a>

  [中文](./README.md) · **English**

  A Google Earth Engine / geemap workbench plugin for AI agents.

  [Capabilities](#capabilities) · [Layout](#layout) · [Usage](#usage) · [Security](#security)
</div>

## Capabilities

EasyGEE packages Google Earth Engine, geemap, GeoMaster method knowledge, and a local browser map console into one reusable agent plugin. It is not trying to clone the classic GEE Code Editor. It helps agents turn natural-language requests into dataset discovery, auth guidance, quota checks, map previews, and hybrid cloud/local geospatial workflows.

- Search and explain datasets from the official GEE catalog and the GEE Community Catalog from Chinese or English task prompts.
- Standardize Earth Engine / geemap authorization without exposing OAuth tokens, verification codes, credential files, or service account keys.
- Query Earth Engine quota limits and usage as agent-readable summaries.
- Generate the lightweight EasyGEE Map Console for AOI drawing, layer overlays, basemap switching, and visual QA.
- Bundle GeoMaster as a skill for CRS, local GIS, remote sensing, ML, STAC/COG, scientific-domain methods, and troubleshooting.

## Layout

```text
easygee/
├── .codex-plugin/       # Codex plugin metadata
├── .claude-plugin/      # Claude plugin metadata
├── assets/              # EasyGEE icon and logo
├── commands/            # Claude-style command entrypoints
├── hooks/               # Hook config and lightweight scripts
├── scripts/             # EasyGEE MCP server entrypoint
├── skills/
│   ├── easygee/         # GEE / geemap / map-console workflows
│   └── geomaster/       # Local GIS and remote-sensing method knowledge
└── adapters/            # Codex, Claude, Zcode, and Qoder notes
```

## Usage

### 1. Quick Install

One-sentence agent install:

```text
Install this plugin for me: [Rimagination/easygee](https://github.com/Rimagination/easygee)
```

After seeing that sentence, an agent should clone or update the repository, write the personal marketplace entry, validate the plugin, and run `codex plugin add easygee@local-plugins` when the Codex CLI is available.

On Windows, you can also run this one-liner:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command '$p=Join-Path $HOME "plugins\easygee"; if(Test-Path $p){ git -C $p pull --ff-only } else { gh repo clone Rimagination/easygee $p }; & (Join-Path $p "scripts\install-easygee.ps1")'
```

The default install location is:

```text
%USERPROFILE%\plugins\easygee
```

The installer adds the plugin path to the local marketplace. Codex discovers EasyGEE from:

```text
C:\Users\Liang\.agents\plugins\marketplace.json
```

The installer also validates the plugin structure. The manual validation command is:

```powershell
python C:\Users\Liang\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py C:\Users\Liang\plugins\easygee
```

### 2. Quick Use

The plugin exposes a local stdio MCP server with these tools:

- `easygee_check_environment`
- `easygee_auth_plan`
- `easygee_search_catalog`
- `easygee_quota_summary`
- `easygee_create_map_console`
- `easygee_preview_plan`

Typical prompts:

```text
Authorize geemap for example-ee-project-123456.
Find GEE datasets for NDVI around Beijing Chaoyang Park.
Open the EasyGEE map console so I can draw an AOI.
Show my Earth Engine project quota and remaining capacity.
```

## Security

EasyGEE treats the browser and credentials as private user space. Agents may prepare auth plans, launch local tools, and summarize safe checks, but must not ask the user to paste OAuth URLs, verification codes, tokens, credential files, service account keys, or short-lived access tokens into chat, logs, docs, or commits.

GeoMaster is bundled as a skill snapshot rather than a nested git checkout. This keeps the plugin self-contained, lightweight, offline-friendly, and free from dependency folders, repository state, or unknown remote sync behavior.
