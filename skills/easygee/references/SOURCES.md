# Sources And Attribution

This file records public sources used to build and improve the `easygee`
skill. It exists for open-source transparency and future maintenance. It is not
a substitute for reading upstream documentation before relying on a specific
API, quota, or installation command.

Reviewed date: 2026-07-06.

## Google Earth Engine Official Sources

| Source | URL | Why It Matters For This Skill |
|---|---|---|
| Earth Engine platform overview | https://earthengine.google.com/platform/ | Defines Code Editor, Explorer, and client libraries as the main interaction modes. |
| Earth Engine signup | https://earthengine.google.com/signup/ | User-facing entry point for registering or signing in to Earth Engine access. |
| Earth Engine access guide | https://developers.google.com/earth-engine/guides/access | Source for commercial/noncommercial access registration, project eligibility, and reverification. |
| Authentication and initialization | https://developers.google.com/earth-engine/guides/auth | Establishes `ee.Authenticate()` and `ee.Initialize(project='my-project')` for Python and command-line workflows. |
| Python installation | https://developers.google.com/earth-engine/guides/python_install | Defines Python API install/update paths and notes that Python UI work needs third-party libraries such as geemap, Folium, or ipyleaflet. |
| Google Cloud Console | https://console.cloud.google.com/ | User entry point for creating/selecting a Cloud project and copying the Project ID. |
| Earth Engine API library page | https://console.cloud.google.com/apis/library/earthengine.googleapis.com | User entry point for enabling the Earth Engine API on a selected Cloud project. |
| Earth Engine configuration page | https://console.cloud.google.com/earth-engine/configuration | User entry point for project commercial/noncommercial Earth Engine configuration. |
| Service account guide | https://developers.google.com/earth-engine/guides/service_account | Source for when service accounts are appropriate and how to avoid committing key material. |
| Cloud Quotas view/manage guide | https://docs.cloud.google.com/docs/quotas/view-manage | Source for Console quota tables, API-specific quota views, current usage columns, and "Unlimited" display behavior. |
| Cloud Quotas API quotaInfos list | https://docs.cloud.google.com/docs/quotas/reference/rest/v1/projects.locations.services.quotaInfos/list | Source for programmatic listing of `QuotaInfo` rows for a project/service. |
| Cloud Quotas API QuotaInfo resource | https://docs.cloud.google.com/docs/quotas/reference/rest/v1/projects.locations.services.quotaInfos | Source for `quotaDisplayName`, `metric`, `metricUnit`, `dimensionsInfos`, and effective quota value fields. |
| gcloud beta quotas info list | https://docs.cloud.google.com/sdk/gcloud/reference/beta/quotas/info/list | Source for the preferred CLI path to list project quota values for `earthengine.googleapis.com`. |
| Google Cloud CLI install quickstart | https://docs.cloud.google.com/sdk/docs/install-sdk | Source for the official Windows installer and post-install initialization guidance. |
| Google Cloud CLI versioned archives | https://docs.cloud.google.com/sdk/docs/downloads-versioned-archives | Source for self-contained and bundled-Python archive installs that can be copied to a fixed local directory and used non-interactively. |
| Cloud Monitoring quota metrics | https://docs.cloud.google.com/monitoring/alerts/using-quota-metrics | Source for recent quota usage metrics through the `consumer_quota` monitored resource. |
| BigQuery raster data | https://docs.cloud.google.com/bigquery/docs/raster-data | Source for querying Earth Engine raster data from BigQuery with functions such as `ST_REGIONSTATS`. |
| Client vs server | https://developers.google.com/earth-engine/guides/client_server | Core mental model for agent code: `ee.*` objects are server-side proxies; `getInfo()` blocks and should be used cautiously. |
| Deferred execution | https://developers.google.com/earth-engine/guides/deferred_execution | Explains that computations are encoded and sent to Earth Engine only when results are requested or map tiles are displayed. |
| Coding best practices | https://developers.google.com/earth-engine/guides/best_practices | Source for avoiding client/server mixing, unnecessary list conversion, excessive `ee.Algorithms.If()`, and using batch `Export` for expensive work. |
| Debugging guide | https://developers.google.com/earth-engine/guides/debugging | Source for agent debugging tactics: inspect variables/layers, use `aside()`, test mapped functions on individual elements, and profile costly steps. |
| Usage quotas | https://developers.google.com/earth-engine/guides/usage | Source for quota categories, request concurrency/rate behavior, batch tasks, fixed limits, and exponential backoff expectations. |
| Noncommercial tiers | https://developers.google.com/earth-engine/guides/noncommercial_tiers | Source for Community, Contributor, and Partner noncommercial tier limits and monthly EECU-hour allowances. |
| Earth Engine ProjectConfig REST resource | https://developers.google.com/earth-engine/reference/rest/v1/ProjectConfig | Source for documented project configuration fields; used to verify that tier-name display should be inferred from quota limits rather than assumed from a documented tier field. |
| Mapping over ImageCollections | https://developers.google.com/earth-engine/guides/ic_mapping | Source for mapped-function limitations: no external mutation, printing, or native `if`/`for` inside mapped functions. |
| Reducer overview | https://developers.google.com/earth-engine/guides/reducers_intro | Establishes reducers as the aggregation primitive over time, space, bands, arrays, lists, and other structures. |
| ImageCollection reductions | https://developers.google.com/earth-engine/guides/reducers_image_collection | Source for pixel-wise compositing/reduction over image collections. |
| FeatureCollection reductions | https://developers.google.com/earth-engine/guides/feature_collection_reducing | Source for `reduceColumns()` and `reduceRegions()` patterns. |
| Grouped reductions and zonal statistics | https://developers.google.com/earth-engine/guides/reducers_grouping | Source for grouped area/class summaries and zonal-statistics patterns. |
| Image visualization | https://developers.google.com/earth-engine/guides/image_visualization | Source for visualization parameter semantics: bands, min/max, gain, bias, gamma, palette. |
| ImageCollection charts | https://developers.google.com/earth-engine/guides/charts_image_collection | Source for charting image collections and time-series summaries. |
| Supervised classification | https://developers.google.com/earth-engine/guides/classification | Source for classifier workflow, sampleRegions, class-label requirements, and accuracy assessment. |
| Join overview | https://developers.google.com/earth-engine/guides/joins_intro | Source for joining collections, including companion QA/cloud collections. |
| Exporting data overview | https://developers.google.com/earth-engine/guides/exporting | Source for Earth Engine export destinations and task-oriented export model. |
| Exporting images | https://developers.google.com/earth-engine/guides/exporting_images | Source for Drive, Cloud Storage, Asset exports, `scale`, `crs`, `crsTransform`, COG, nodata, `maxPixels`, and large-file behavior. |
| Exporting tables | https://developers.google.com/earth-engine/guides/exporting_tables | Source for CSV/SHP/GeoJSON/KML/KMZ/TFRecord table export behavior. |
| Projections | https://developers.google.com/earth-engine/guides/projections | Source for default WGS84/1-degree projection behavior in composites/mosaics and cautions around `reproject()`. |
| Scale | https://developers.google.com/earth-engine/guides/scale | Source for Earth Engine's output-driven scale model and why reducer/export scale must be explicit. |
| Sentinel-2 SR Harmonized catalog | https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED | Source for S2 SR band scale, SCL classes, QA60 caveat, and cloud-mask companion datasets. |
| Cloud Score+ S2 Harmonized catalog | https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_CLOUD_SCORE_PLUS_V1_S2_HARMONIZED | Source for `cs`/`cs_cdf` clear-pixel quality bands and linking pattern with S2. |
| Sentinel-2 Cloud Probability catalog | https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_CLOUD_PROBABILITY | Source for s2cloudless probability band and join-based cloud masking pattern. |
| S2 cloudless tutorial | https://developers.google.com/earth-engine/tutorials/community/sentinel-2-s2cloudless | Public tutorial for cloud and shadow masking with S2 cloud probability. |
| Sentinel-1 GRD catalog | https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S1_GRD | Source for SAR GRD product metadata, polarizations, update cadence, and flood/all-weather dataset selection. |
| Sentinel-1 algorithms guide | https://developers.google.com/earth-engine/guides/sentinel1 | Source for Sentinel-1 preprocessing and backscatter interpretation in Earth Engine. |
| Landsat 8 C2 L2 catalog | https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC08_C02_T1_L2 | Source for Landsat Collection 2 Level 2 scale factors and geemap/Python example. |
| MOD13Q1 vegetation indices catalog | https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD13Q1 | Source for MODIS NDVI/EVI scale and DetailedQA bitmask. |
| MOD11A2 land surface temperature catalog | https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD11A2 | Source for MODIS 8-day 1 km LST, scale conversion, and QC bands. |
| VIIRS monthly DNB catalog | https://developers.google.com/earth-engine/datasets/catalog/NOAA_VIIRS_DNB_MONTHLY_V1_VCMSLCFG | Source for monthly stray-light-corrected nighttime lights, radiance band, coverage, cadence, and proxy limitations. |
| Dynamic World V1 catalog | https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_DYNAMICWORLD_V1 | Source for Dynamic World probability bands and `label` semantics. |
| ESA WorldCover v200 catalog | https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200 | Source for categorical 10 m land-cover product details. |
| JRC Global Surface Water v1.4 catalog | https://developers.google.com/earth-engine/datasets/catalog/JRC_GSW1_4_GlobalSurfaceWater | Source for water occurrence, seasonality, transition, and historical surface-water date range. |
| WorldPop 100 m population catalog | https://developers.google.com/earth-engine/datasets/catalog/WorldPop_GP_100m_pop | Source for WorldPop population counts, approximate 100 m grid, years, and modeled-population caveats. |
| GHSL population P2023A catalog | https://developers.google.com/earth-engine/datasets/catalog/JRC_GHSL_P2023A_GHS_POP | Source for GHSL multi-epoch population surfaces and projection years. |
| Open Buildings V3 polygons catalog | https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings_v3_polygons | Source for building-footprint coverage, geometry fields, confidence, and large-collection handling. |
| Copernicus DEM GLO-30 catalog | https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_DEM_GLO30 | Source for 30 m DEM use and band metadata. |
| NDVI and quality mosaicking tutorial | https://developers.google.com/earth-engine/tutorials/tutorial_api_06 | Source for mapping functions over collections, NDVI, and quality mosaic task patterns. |
| Forest change tutorial | https://developers.google.com/earth-engine/tutorials/tutorial_forest_03 | Source for area quantification and change-analysis task framing. |
| Global Surface Water occurrence tutorial | https://developers.google.com/earth-engine/tutorials/tutorial_global_surface_water_02 | Source for water occurrence visualization, threshold masks, and inspector workflow. |
| Earth Engine API GitHub | https://github.com/google/earthengine-api | Upstream Python/JavaScript bindings and release reference. |
| Earth Engine Community GitHub | https://github.com/google/earthengine-community | Official community tutorial repository and contribution route. |
| Earth Engine public STAC catalog | https://storage.googleapis.com/earthengine-stac/catalog/catalog.json | Machine-readable official catalog root used to ground dataset discovery and catalog source attribution. |
| GEE Community datasets CSV | https://github.com/sadassimov/geemu-skill/blob/main/awesome-gee-community-datasets/community_datasets.csv | Machine-readable community dataset index used to expand EasyGEE Add Layers and catalog search beyond the official Earth Engine STAC catalog. |
| GEEMu skill repository | https://github.com/sadassimov/geemu-skill | Reviewed as an upstream skill pattern for lightweight local JSONL knowledge search, data-layer records, boundary/compute gates, dry-run/export switches, and community dataset attribution. EasyGEE absorbs the patterns selectively; GEEMu's local knowledge database is not treated as an authoritative source for current API or dataset semantics. |

## geemap / Qiusheng Wu Sources

| Source | URL | Why It Matters For This Skill |
|---|---|---|
| geemap documentation home | https://geemap.org/ | Feature inventory: JS-to-Python conversion, interactive layers, inspector, plotting, drawing, shapefiles, exports, zonal stats, timelapse, catalog search. |
| geemap usage page | https://geemap.org/usage/ | Source for common API calls: maps, layers, local data conversion, exports, zonal stats, split maps, legends, timelapse, conversion, and map publishing. |
| geemap API reference | https://geemap.org/geemap/ | Main ipyleaflet-based mapping API reference. |
| geemap common functions | https://geemap.org/common/ | Source for export helper names and implementation shape for image/table/vector exports. |
| geemap AI module | https://geemap.org/ai/ | Source for dataset search helpers such as `EarthEngineDatasetIndex.find_top_matches`. |
| geemap GitHub | https://github.com/gee-community/geemap | Upstream package source and README. |
| Earth-Engine-Catalog JSON index | https://github.com/giswqs/Earth-Engine-Catalog | Qiusheng Wu maintained machine-readable index of Earth Engine Data Catalog entries; used as a lightweight source of dataset ids, titles, keywords, and official Google catalog URLs. |
| geemap examples index | https://github.com/gee-community/geemap/blob/master/examples/README.md | Tutorial map from basic intro through inspector, split panels, drawing tools, GeoJSON, exports, zonal stats, JS conversion, Gemini, MapLibre, and dataset explorer. |
| geemap installation | https://geemap.org/installation/ | Install paths and Earth Engine account requirement. |
| geemap FAQ | https://geemap.org/faq/ | Citation and project support details. |
| Earth Engine and Geemap book | https://book.geemap.org/ | Structured long-form learning path for GEE plus geemap. |
| Geemap book data export chapter | https://book.geemap.org/chapters/07_data_export.html | Source for local image download, Drive exports, image collection download, table/vector export, and map export patterns. |
| geebook repository | https://github.com/giswqs/geebook | Open book repository and CC-BY-4.0 attribution context. |
| Export image notebook | https://geemap.org/notebooks/11_export_image/ | Source for `ee_export_image`, image collection download, Drive export, and NumPy extraction examples. |
| Zonal statistics notebook | https://geemap.org/notebooks/12_zonal_statistics/ | Source for `geemap.zonal_stats()` output/stat options. |
| Zonal statistics by group notebook | https://geemap.org/notebooks/13_zonal_statistics_by_group/ | Source for grouped zonal composition workflows. |
| JS to notebook/script conversion notebook | https://geemap.org/notebooks/08_ee_js_to_ipynb/ | Source for `geemap.conversion` and backend selection between ipyleaflet and folium/Colab. |
| Timeseries inspector notebook | https://geemap.org/notebooks/20_timeseries_inspector/ | Source for map-drawn ROI and landscape-change inspection patterns. |
| Water app notebook | https://geemap.org/notebooks/41_water_app/ | Source for geemap-based surface water dynamics app patterns. |
| Local random forest training notebook | https://geemap.org/notebooks/46_local_rf_training/ | Source for local sklearn model conversion into Earth Engine classifier workflows. |
| Layer to image notebook | https://geemap.org/notebooks/139_layer_to_image/ | Source for exporting styled map layers as images instead of screenshots. |
| Earth Engine Dataset Explorer notebook | https://geemap.org/notebooks/151_dataset_explorer/ | Catalog-driven discovery pattern. |
| geemap key features notebook | https://geemap.org/notebooks/00_geemap_key_features/ | Broad notebook covering maps, basemaps, EE layers, catalog/API search, inspector, plotting, drawing, JS conversion, shapefiles, timelapse, and exports. |
| Draw control notebook | https://geemap.org/notebooks/138_draw_control/ | Source for retrieving drawn geometries as `m.user_roi` or `m._user_rois`. |
| Export map to HTML/PNG notebook | https://geemap.org/notebooks/21_export_map_to_html_png/ | Source for `Map.to_html()` and `Map.to_image()` communication exports. |

## OpenGeo / Agentic GIS Sources

| Source | URL | Why It Matters For This Skill |
|---|---|---|
| GeoAgent | https://github.com/opengeos/GeoAgent | Multimodal geospatial agent architecture for Python packages, live maps, and QGIS plugins. |
| OpenGeoAgent QGIS plugin | https://geoagent.gishub.org/qgis-plugin/ | QGIS agent surface: inspect project/layers/map, run confirmed tools, and fall back to PyQGIS carefully. |
| GeoLibre | https://github.com/opengeos/GeoLibre | Local-first cloud-native GIS workbench architecture: web, desktop, mobile, and notebook. |
| GeoLibre website | https://geolibre.app/ | Product framing and end-user workflow. |
| qgis-gee-data-catalogs-plugin | https://github.com/opengeos/qgis-gee-data-catalogs-plugin | QGIS catalog workflow for official Earth Engine Data Catalog and Awesome GEE Community Catalog. |
| qgis-geemap-plugin | https://github.com/opengeos/qgis-geemap-plugin | QGIS bridge for geemap/GEE layers. |
| gee-agents | https://github.com/opengeos/gee-agents | Portable GEE agent packaging pattern. |
| geoai-skills | https://github.com/opengeos/geoai-skills | Skill decomposition examples for geospatial inspection, STAC, Overture, raster processing, and memory. |
| leafmap | https://leafmap.org/ | Broader mapping ecosystem around local/cloud geospatial data. |
| anymap | https://github.com/opengeos/anymap | anywidget bridge for bidirectional Python-JavaScript maps. |

## Web GIS UI References

| Source | URL | Why It Matters For This Skill |
|---|---|---|
| Insight Maps web app | https://map.insightmaps.app/ | Public app shell and static assets show a professional ArcGIS/Calcite-style map UI pattern: compact icon tools, layer catalog/filtering, drawing/measurement modules, basemap/layer management, charts, and theme presets. |

## Public Tutorial Sources

| Source | URL | Why It Matters For This Skill |
|---|---|---|
| Spatial Thoughts Advanced GEE course | https://courses.spatialthoughts.com/gee-advanced.html | Strong public course on reducers, joins, charts, apps, arrays, machine learning, and supervised classification. |
| World Bank Open Nighttime Lights geemap tutorial | https://worldbank.github.io/OpenNightLights/tutorials/mod2_5_GEE_PythonAPI_and_geemap.html | Clear explanation of geemap modules: geemap, eefolium, conversion, basemaps, legends. |
| NASA ARSET GEE land monitoring training | https://www.earthdata.nasa.gov/learn/trainings/using-google-earth-engine-land-monitoring-applications | Applied remote-sensing workflow themes: change detection, time series, classification, accuracy assessment. |
| Google Earth Engine community tutorials | https://developers.google.com/earth-engine/tutorials | Official route to community-contributed tutorials. |
| GEEer成长日记 WeChat album "GEE" | https://mp.weixin.qq.com/mp/appmsgalbum?__biz=MzkzNjMxNDk1NQ==&action=getalbum&album_id=2182256849633247236 | Secondary cookbook corpus used to identify Chinese GEE task patterns and source titles for `gee-growth-diary`; not authoritative for current dataset ids, QA masks, scale factors, or API behavior. |
| 野火遥感Fire Centre WeChat article | https://mp.weixin.qq.com/s/pEVuV8Q4dH2BWv_zQCDmZQ | Chinese wildfire remote-sensing and disaster-monitoring practice reference. Treat as a secondary applied source; verify dataset ids, algorithms, QA masks, and API behavior against official sources before using in EasyGEE workflows. |

## License And Reuse Notes

- This skill distills procedures and design patterns. It does not vendor
  upstream source code.
- Before copying code from any upstream project, verify the repository license
  and preserve attribution notices.
- Google documentation code samples are generally Apache 2.0 and text is
  generally CC-BY 4.0 unless otherwise noted on the page.
- The geebook repository advertises CC-BY-4.0; cite it if reusing educational
  structure or explanatory material.
- Never include private Earth Engine assets, OAuth tokens, service account
  keys, provider API keys, or browser authentication material in examples,
  notebooks, commits, or released skill packages.
