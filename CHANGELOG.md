# Changelog

## 0.4.0 - 2026-08-30

### Added

- Configurable XYZ, TMS, ArcGIS, WMS, WMTS, raster PMTiles, and COG basemaps,
  including built-in Tianditu vector, imagery, and terrain presets.
- GeoLibre-inspired high-performance data paths: HTTP Range-backed raster
  PMTiles, lazy MapLibre WebGL COG rendering, in-session caches, and compact
  first-render/readiness diagnostics.
- A GIS-style basemap-to-layer workflow with overlay stacking, opacity and
  visibility controls, source details, default basemaps, and zoom-to-layer.
- Durable per-user Map Console profiles for favorites, custom basemaps, map
  view, recent reproducible layers, and per-project layer state.

### Security

- Tianditu keys stay session-only by default; optional device persistence uses
  Windows DPAPI and excludes plaintext credentials from profiles and agent
  state.
- Custom source URLs reject embedded credentials and credential-shaped query
  parameters, while stale browser protocol state can no longer overwrite a
  newer persisted profile.

### Fixed

- Basemap selection and layer checkboxes now update the rendered map and saved
  state consistently, including SRTM visibility and primary-basemap controls.
- Terrain basemaps reuse the last available native zoom where providers lack
  higher-resolution tiles instead of filling the view with unavailable tiles.

### Validation

- Added focused coverage for PMTiles/COG adapters, custom basemap sanitation,
  secure Tianditu credential persistence, byte-range serving, stale-protocol
  handling, profile restoration, basemap overlays, and zoom-to-layer.

## 0.3.2 - 2026-08-18

### Added

- A generic `multimodal-geo-vector` skill for turning local or GEE imagery
  annotations into CRS-aware GeoPackage/GeoJSON artifacts.
- AOI-local recent-scene selection, polygon-hole preservation, and automatic
  raster/vector QA overlays.
- Routing regression coverage for short photovoltaic, vehicle, tree-crown,
  field-parcel, and vessel prompts.

### Changed

- Short multimodal prompts now treat center coordinates as spatial seeds and
  GeoPackage as a local GIS deliverable without asking redundant questions.
- GEE visual-boundary workflows prefer one traceable clear acquisition over a
  median composite and report valid-pixel coverage.

## 0.3.1 - 2026-08-01

### Changed

- Updated Chinese and English README acknowledgements with the official HLS,
  USGS CFMask, Sentinel-1, and Earth Engine compositing sources used by the
  remote-sensing method layer.
- Collapsed the project-layout tree inside an expandable README section and
  documented the new remote-sensing references and scripts.

## 0.3.0 - 2026-08-01

### Added

- Compact remote-sensing method references for Landsat cloud masking, HLS
  cross-sensor harmonization, temporal compositing, and Sentinel-1 SAR.
- Visual and numeric teaching cases comparing Sentinel-2 cloud masks and
  Landsat/Sentinel-2 observations.
- Task-planner and dataset-catalog routes for HLS, SAR geometry, and temporal
  composite semantics.
- Eleven offline evaluation prompts covering the expanded Earth Engine and
  geemap workflows.

### Changed

- Sentinel-2 minimal examples now apply Cloud Score+ pixel-level masking after
  scene-level filtering.
- Landsat Collection 2 defaults now mask fill, cloud/shadow/snow, and saturated
  pixels with `QA_PIXEL` and `QA_RADSAT`.
- Local reference search now prioritizes curated EasyGEE method cards over
  secondary teaching material.

### Validation

- EasyGEE coverage audit: 363/363 checks passed.
- Evaluation prompts: 11/11 passed.
- Project tests: 5 passed.

## 0.2.0 - 2026-07-19

### Added

- A standard-library, bilingual catalog engine for more than 5,000 official
  Earth Engine and community catalog records.
- Exact-id, name, theme, and task retrieval with inspectable match reasons,
  provenance-aware ranking, deprecation handling, and metadata filters.
- Role-based task recommendations for flood risk, vegetation monitoring, soil
  moisture, and land-cover workflows.
- Dataset comparison, catalog verification, optional live Earth Engine asset
  checks, and catalog coverage statistics.
- MCP tools for search, recommendation, comparison, and verification.
- Offline unit tests for DEM, Chinese soil-moisture search, flood-risk bundles,
  filters/comparison, and no-match behavior.

### Changed

- Removed unrelated generic dataset fallbacks when a query has no evidence.
- Updated the curated Copernicus DEM record to the current 2024_1 product.
- Enabled `community` and `all` catalog modes in the Map Console CLI.
