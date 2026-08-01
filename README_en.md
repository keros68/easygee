<div align="center">
  <img src="./assets/logo.png" alt="EasyGEE" width="96" />
  <h1>EasyGEE</h1>

  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-0F766E?style=flat-square" /></a>
  <a href="./.codex-plugin/plugin.json"><img alt="Plugin" src="https://img.shields.io/badge/plugin-Codex%20%7C%20Claude-2563EB?style=flat-square" /></a>
  <a href="./.mcp.json"><img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-111827?style=flat-square" /></a>

  [中文](./README.md) · **English**

  A Google Earth Engine / geemap workbench plugin for AI agents.

  [Capabilities](#capabilities) · [Layout](#layout) · [Usage](#usage) · [Security](#security) · [Acknowledgements](#acknowledgements)
</div>

## Capabilities

EasyGEE packages Google Earth Engine, geemap, GeoMaster method knowledge, and a local browser map console into one reusable agent plugin. It is not trying to clone the classic GEE Code Editor. It helps agents turn natural-language requests into dataset discovery, auth guidance, quota checks, map previews, and hybrid cloud/local geospatial workflows.

- Search 5,000+ official and community GEE records by dataset id, name, theme, or bilingual task, with provenance, deprecation, and match evidence in the ranking.
- Turn an outcome into role-based data bundles—for example flood event, historical baseline, terrain, rainfall, and population/building exposure—and compare or verify candidates before coding.
- Standardize Earth Engine / geemap authorization without exposing OAuth tokens, verification codes, credential files, or service account keys.
- Query Earth Engine quota limits and usage as agent-readable summaries.
- Generate the lightweight EasyGEE Map Console for AOI drawing, layer overlays, basemap switching, and visual QA.
- Bundle GeoMaster as a skill for CRS, local GIS, remote sensing, ML, STAC/COG, scientific-domain methods, and troubleshooting.
- Bundle the GeoAI Encyclopedia as EasyGEE's task-method layer for image recognition, object detection, semantic/instance segmentation, change detection, pixel regression, SAM, satellite embeddings, vision-language models, and QGIS GeoAI. The router loads only the relevant chapter and keeps GEE/export orchestration separate from local model execution.
- Bundle GEE Growth Diary as a distilled method skill from 153 GEEer成长日记 articles covering dataset choice, indices, time series, classification, water extraction, charts, and exports.

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
│   ├── geomaster/       # Local GIS and remote-sensing method knowledge
│   └── gee-growth-diary/ # Distilled GEEer成长日记 method playbook
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

Just tell the agent what you want in plain language. These examples cover common daily workflows:

```text
Authorize geemap for example-ee-project-123456.

Open the EasyGEE map around Beijing Chaoyang Park so I can draw an AOI.

I want summer 2024 NDVI for Beijing Chaoyang Park. Pick a suitable GEE dataset and explain why.

Search 5,000+ records for DEMs, keep current official products, and compare the top three.

I need a mountain flood-risk assessment but have not chosen data. Recommend a bundle by hazard, terrain, rainfall, and exposure roles.

Compare COPERNICUS/DEM/GLO30_2024_1 with USGS/SRTMGL1_003 and verify the final id before writing code.

Add Sentinel-2 true color and NDVI layers to the map so I can inspect clouds and vegetation in the browser.

Show my Earth Engine project quota, usage tier, and remaining capacity.

Export NDVI for the current AOI to Google Drive and check whether the export parameters make sense.

I have a local GeoJSON. Decide whether this should run in GEE or local GIS, then generate a runnable script.
```

## Security

EasyGEE treats the browser and credentials as private user space. Agents may prepare auth plans, launch local tools, and summarize safe checks, but must not ask the user to paste OAuth URLs, verification codes, tokens, credential files, service account keys, or short-lived access tokens into chat, logs, docs, or commits.

GeoMaster is bundled as a skill snapshot rather than a nested git checkout. This keeps the plugin self-contained, lightweight, offline-friendly, and free from dependency folders, repository state, or unknown remote sync behavior.

## Acknowledgements

EasyGEE distills patterns from many open geospatial resources and projects. Special thanks to:

- [Google Earth Engine documentation](https://developers.google.com/earth-engine) for authentication, initialization, quotas, exports, the client/server model, and remote-sensing workflow guidance.
- [Earth Engine Data Catalog](https://developers.google.com/earth-engine/datasets/) and the [Earth Engine STAC Catalog](https://storage.googleapis.com/earthengine-stac/catalog/catalog.json) as the main sources for dataset discovery and dataset detail cards.
- [GEE Community Catalog](https://gee-community-catalog.org/) and [community_datasets.csv](https://github.com/sadassimov/geemu-skill/blob/main/awesome-gee-community-datasets/community_datasets.csv) for community dataset coverage beyond the official catalog.
- The WeChat public account [GEEer成长日记](https://mp.weixin.qq.com/mp/appmsgalbum?__biz=MzkzNjMxNDk1NQ==&action=getalbum&album_id=2182256849633247236) for Chinese GEE practice cases and task inspiration that helped EasyGEE better cover Chinese-language remote-sensing workflows.
- The WeChat public account [野火遥感Fire Centre](https://mp.weixin.qq.com/s/pEVuV8Q4dH2BWv_zQCDmZQ) for Chinese wildfire remote-sensing, disaster monitoring, and applied case-study references.
- [GEEMu Skill](https://github.com/sadassimov/geemu-skill) for inspiration around lightweight local knowledge search, data-layer records, boundary/compute gates, and export dry-run patterns.
- [geemap](https://geemap.org/) / [gee-community/geemap](https://github.com/gee-community/geemap) for Python-based GEE maps, notebooks, export helpers, and dataset exploration patterns.
- [Qiusheng Wu's Earth-Engine-Catalog](https://github.com/giswqs/Earth-Engine-Catalog) for a lightweight machine-readable Earth Engine catalog index.
- [OpenGeoAgent / GeoAgent](https://github.com/opengeos/GeoAgent), [GeoLibre](https://github.com/opengeos/GeoLibre), [leafmap](https://leafmap.org/), and [anymap](https://github.com/opengeos/anymap) for map-first, agentic, and local-first GIS workbench ideas.
- [Insight Maps](https://map.insightmaps.app/) for compact map tools, layer catalog interactions, and polished Web GIS UI references.
- [netease-youdao/LobsterAI](https://github.com/netease-youdao/LobsterAI) for README hero structure, badges, and language-switch layout inspiration.

See [skills/easygee/references/SOURCES.md](./skills/easygee/references/SOURCES.md) for the fuller source and attribution record.
