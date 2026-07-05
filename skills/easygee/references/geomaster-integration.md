# GeoMaster Integration

Use this reference when an EasyGEE task needs geospatial method knowledge beyond
GEE/geemap plumbing: CRS, local vector/raster processing, spectral indices, SAR,
machine learning, STAC/COG, scientific domains, point clouds, network analysis,
or desktop/cloud-native GIS workflows.

Core principle: EasyGEE remains the GEE agent workbench. GeoMaster becomes the
method backend. In the EasyGEE plugin, GeoMaster is bundled as
`../geomaster`, so the plugin can work as a self-contained geospatial package
without requiring the user's global skill registry. Do not load every
GeoMaster example at once; route to the
smallest useful GeoMaster reference and keep EasyGEE responsible for
authentication, quota, catalog, export, browser handoff, and Earth Engine code
review.

## Routing Order

1. Run or apply `scripts/route_easygee_interaction.py` to decide whether the
   user needs computation, browser map state, or both.
2. Run `scripts/route_geospatial_method.py "<task>" --json` when the task has
   data/method choices, local files, CRS, ML, STAC/COG, domain science, or
   uncertainty about GEE vs local GIS.
3. Load only the referenced GeoMaster sections required by the route. Prefer
   the bundled plugin skill at `skills/geomaster` when available; otherwise use
   the user's global `geomaster` skill.
4. Execute the workflow and report the backend split: GEE, local, hybrid,
   catalog, or browser.

## Backend Decisions

| Method | Use When | Primary backend | Required habit |
| --- | --- | --- | --- |
| `gee_first` | Cloud-scale remote sensing, GEE catalog data, reducers, exports, geemap visualization | Earth Engine | Keep computation server-side; set project; avoid large `getInfo()` |
| `local_first` | Local GeoTIFF/Shapefile/GeoJSON/GPKG, CRS-heavy work, topology, windowed raster, point clouds, network analysis | Local Python/R/GIS | Inspect CRS, nodata, units, geometry validity, memory, and output format |
| `hybrid` | GEE data access plus local COG/STAC/ML/advanced stats or exact file-based GIS | Earth Engine plus local tools | Make handoff explicit: region, scale, projection, bands, masks, file paths |
| `catalog_first` | User asks which dataset/source to use | GEE catalog plus GeoMaster data sources | Rank candidates and verify cadence, scale, bands, masks, licensing |
| `browser_first` | User needs AOI drawing, layer inspection, annotation, or visual QA | EasyGEE Map Console | Treat map state as visual context, not analytical proof |

## GeoMaster Knowledge Index

`geomaster-knowledge-index.json` is the compact lookup table for the whole
GeoMaster reference set. Use it as the first stop when deciding which heavy
reference to read.

| GeoMaster Reference | Route Triggers | EasyGEE Use |
| --- | --- | --- |
| `geomaster:coordinate-systems.md` | CRS, EPSG, UTM, area, distance, axis order | Projection and unit correctness for local/hybrid results |
| `geomaster:core-libraries.md` | GeoPandas, Rasterio, GDAL, Shapely, PyProj | Local vector/raster IO and operations |
| `geomaster:remote-sensing.md` | Sentinel, Landsat, MODIS, SAR, indices, cloud masks | Domain methods for dataset QA and preprocessing |
| `geomaster:machine-learning.md` | Classification, RF, CNN, GNN, TorchGeo, training | Local/hybrid modeling and validation |
| `geomaster:gis-software.md` | QGIS, ArcGIS, GRASS, PostGIS | Desktop/database handoff when browser is not enough |
| `geomaster:scientific-domains.md` | Marine, atmosphere, hydrology, agriculture, forestry | Domain-specific assumptions and indicators |
| `geomaster:advanced-gis.md` | 3D, topology, networks, trajectories, viewshed | Local/hybrid advanced GIS methods |
| `geomaster:big-data.md` | Dask, COG, STAC, Planetary Computer, Zarr, Parquet | Cloud-native and large-data workflows |
| `geomaster:industry-applications.md` | Urban, disaster, infrastructure, environmental monitoring | Application framing and output expectations |
| `geomaster:programming-languages.md` | R, Julia, JavaScript, C++, Java, Go, Rust | Non-Python translations when requested |
| `geomaster:data-sources.md` | Catalogs, APIs, satellite sources, STAC | Compare GEE with external data sources |
| `geomaster:troubleshooting.md` | GDAL install, CRS mismatch, memory, geometry, coordinate order | Diagnose local GIS failures |
| `geomaster:code-examples.md` | Examples, snippets, templates | Pull examples after backend routing |
| `geomaster:specialized-topics.md` | Geostatistics, kriging, optimization, privacy, provenance | Specialized local/hybrid methods |

## Fusion Rules

- Prefer `gee_first` for global/regional satellite workflows already available
  in the GEE catalog and expressible with server-side reducers/exports.
- Prefer `local_first` when the user names local files, exact file formats,
  CRS-sensitive calculations, topology, routing, point clouds, or windowed
  raster access.
- Prefer `hybrid` when GEE is best for finding/compositing/exporting imagery
  but local libraries are better for COG/STAC packaging, ML, advanced
  statistics, or reproducible file-based delivery.
- Prefer `catalog_first` when the user is not yet asking for analysis but for
  "which dataset/source should I use?"
- Prefer `browser_first` only for drawing, visual checking, comments, or map
  state tasks. Browser use does not replace numerical validation.

## Final Answer Contract

When method routing materially affects the work, state:

- Method: `gee_first`, `local_first`, `hybrid`, `catalog_first`, or
  `browser_first`.
- Backends used and why.
- GeoMaster references consulted or deferred.
- Artifact handoff: EE object, export task, local file, table, model, map layer,
  AOI, or dataset candidates.
- Unrun pieces caused by credentials, missing local dependencies, quota, or
  unavailable data.
