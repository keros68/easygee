# Changelog

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
