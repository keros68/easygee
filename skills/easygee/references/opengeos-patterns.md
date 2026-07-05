# OpenGeo Ecosystem Patterns

Use this reference when a task mentions OpenGeoAgent, GeoLibre, opengeos,
Qiusheng Wu, geemap beyond basic setup, leafmap, anymap, QGIS GEE plugins,
GEE agents, catalog-driven workflows, or map-first AI assistants.

These notes distill public project documentation and READMEs. They are not a
copy of project code. Verify live APIs before implementing against a current
release.

## Source Map

- `geemap`: Python package for interactive GEE analysis in Jupyter. It fills
  Python API visualization gaps, supports Earth Engine JS-to-Python migration,
  inspectors, drawing tools, local data integration, exports, timelapse maps,
  catalog search, and map publishing.
- `leafmap`: broader interactive mapping layer across backends and notebooks,
  with MapLibre examples, STAC/COG/PMTiles/local raster/vector workflows, and
  publication-oriented map components.
- `anymap`: anywidget bridge for Python-to-JavaScript maps. Its core design is
  bidirectional Python <-> JS communication, MapLibre support, and an API that
  feels familiar to notebook map users.
- `GeoAgent`: shared agent layer for geospatial Python packages, live maps, and
  QGIS plugins. It binds runtime context such as maps or QGIS `iface`, exposes
  functions as structured tools, keeps optional dependencies optional, supports
  many model providers, and adds confirmation hooks before destructive or
  expensive operations.
- `OpenGeoAgent` QGIS plugin: project-aware QGIS chat surface. It inspects
  layers, map state, CRS, selections, STAC results, screenshots, and can use a
  confirmation-gated PyQGIS fallback when dedicated tools are insufficient.
- `GeoLibre`: local-first cloud-native GIS workbench using Tauri, React,
  TypeScript, MapLibre GL JS, DuckDB-WASM Spatial, deck.gl, and a Jupyter
  widget package. It runs in browser, desktop, mobile, and notebooks while
  keeping data local.
- `qgis-gee-data-catalogs-plugin`: QGIS catalog workflow for official Earth
  Engine datasets and the Awesome GEE Community Catalog. It emphasizes search,
  filters, catalog cache, time-series layers, pixel inspectors, code console,
  JS-to-Python conversion, export queues, and QGIS Processing integration.
- `qgis-geemap-plugin`: geemap/GEE bridge inside QGIS, with a core map class
  and Earth Engine layer conversion into QGIS.
- `gee-agents`: packaging pattern for portable GEE agents: `agent.yaml`,
  `main.py`, `tools/`, `requirements.txt`, `README.md`, `example.ipynb`, public
  datasets only, no private EE assets or secrets in commits.
- `geoai-skills`: skills-style decomposition for geospatial tasks: inspect
  files, search/download STAC, fetch Overture data, process rasters, detect
  objects, and keep session memory.

## Distilled Design Laws

1. Bind context first. A useful geospatial agent is attached to a live map,
   QGIS project, active layer, ROI, dataset, notebook, or serialized project,
   not just a chat prompt.
2. Expose a structured tool surface before falling back to code generation:
   inspect, list layers, search catalogs, add layers, set opacity/style, zoom,
   sample pixels, create time series, export, save project.
3. Make fallbacks explicit and gated. Generated PyQGIS, browser JavaScript, or
   expensive processing jobs need confirmation and a clear transcript.
4. Keep dependencies optional. Split install modes for notebook, QGIS, STAC,
   Earthdata, Earth Engine, browser UI, and providers. Do not force heavy GIS
   stacks into a simple script workflow.
5. Prefer local-first and privacy-preserving workflows. Use local files,
   DuckDB-WASM, GeoParquet/COG/PMTiles/STAC URLs, and project JSON when they
   solve the task without uploading private data.
6. Make catalog workflows repeatable: dataset id, bbox/ROI, date range, cloud
   threshold, reducer/composite, bands, visualization parameters, export scale,
   output format, and task history should be explicit.
7. Keep the map in the loop. Alternate between search/filter, add layer,
   inspect sample/pixel/time series, style, export. Avoid writing a long
   analysis script before validating the map state.
8. Use cloud-native data patterns. Prefer STAC search, COG loading through
   `/vsicurl/` in QGIS, PMTiles/vector tiles for web maps, and DuckDB spatial
   queries for local/browser analysis.
9. Serialize state. Save notebooks, map HTML, QGIS projects, or `.geolibre.json`
   style project state so a workflow can resume without hidden UI state.
10. Separate UI from reusable geospatial logic. Put reusable tools in plain
    Python modules; let QGIS plugins, notebooks, and browser apps consume the
    same metadata and functions.

## Apply To GEE/geemap Work

Use this canonical workflow unless the user gives a better one:

1. Clarify AOI, time window, dataset family, output type, and environment
   (notebook, script, QGIS, browser app, GeoLibre-style local app).
2. Search or identify the dataset. Prefer official catalog ids and record the
   dataset URL/id in code comments or metadata.
3. Filter by AOI, dates, cloud/quality fields, and collection-specific QA.
4. Build a small visual composite first. Add it to a map with explicit bands,
   min/max, palette, opacity, and layer name.
5. Inspect values or time series before exporting. For a point/ROI, use a
   reducer or FeatureCollection rather than repeated `getInfo()`.
6. Export with explicit region, scale, CRS when needed, `maxPixels`, task name,
   destination, and output format.
7. Save the workflow as notebook plus plain script when it may become
   production: notebook for exploration, script for replay.

## Apply To AI Map Agents

When designing an AI assistant or skill around maps:

- Define runtime context: map object, QGIS `iface`, project, active layer, ROI,
  provider/model config, and permission profile.
- Define tool categories: inspect, navigate, layer management, data loading,
  catalog search, analysis, export, project persistence, fallback code.
- Annotate each tool with risk level: read-only, visual-only, file-writing,
  network-heavy, quota-heavy, destructive.
- Add confirmation gates for file writes, layer deletion, project saves,
  exports, uploads, and arbitrary code execution.
- Return compact, structured results: layer names, CRS, extent, asset ids, task
  ids, output paths, and warnings.

## Apply To QGIS Work

- Use dedicated QGIS tools for common operations before writing PyQGIS.
- Run GUI-affecting actions through the QGIS-safe path for the environment; do
  not assume arbitrary background-thread PyQGIS is safe.
- For remote COG/STAC rasters, prefer GDAL `/vsicurl/` style loading and
  background tasks when possible, then validate the layer before zooming.
- Always report active layer, CRS, extent, selected feature count, and output
  layer names when modifying a project.

## Apply To GeoLibre-Style Apps

- Design local-first: browser/desktop should work without accounts or servers
  when data sources permit.
- Use MapLibre GL JS for the map, DuckDB spatial for browser-local analytics,
  and deck.gl for rich visual layers when appropriate.
- Keep a project JSON as the handoff format between app, notebook, and saved
  sessions.
- For notebooks, use an anywidget-style two-way bridge when the UI needs to
  stay synchronized with Python state.

## Safety And Attribution

- Cite upstream projects when reusing ideas, documentation, or code.
- Check license compatibility before copying code. Most referenced projects are
  MIT-licensed, but verify per repo and preserve notices.
- Do not include private Earth Engine assets, OAuth credentials, service
  account keys, provider API keys, or browser auth material in examples,
  notebooks, commits, or exported skill files.

## Key Public Sources

- https://github.com/gee-community/geemap
- https://leafmap.org/
- https://github.com/opengeos/anymap
- https://github.com/opengeos/GeoAgent
- https://geoagent.gishub.org/qgis-plugin/
- https://github.com/opengeos/GeoLibre
- https://geolibre.app/
- https://github.com/opengeos/qgis-gee-data-catalogs-plugin
- https://github.com/opengeos/qgis-geemap-plugin
- https://github.com/opengeos/gee-agents
- https://github.com/opengeos/geoai-skills
