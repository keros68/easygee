# Chapter 4: Downloading Remote Sensing Data

## Core idea

Acquire imagery by querying metadata first, not by guessing URLs. STAC lets the workflow constrain collection, bbox, date, cloud cover, and assets before downloading only the bands needed by the model.

## STAC workflow

```python
from pystac_client import Client
catalog = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
search = catalog.search(
    collections=["sentinel-2-l2a"],
    bbox=[-83.94, 35.96, -83.92, 35.98],
    datetime="2025-06-01/2025-08-31",
    query={"eo:cloud_cover": {"lt": 10}},
    max_items=1,
)
items = search.item_collection()
```

Inspect the chosen item ID, datetime, cloud cover, assets, spatial/temporal extent, and license. Use `geoai.download_pc_stac_item` to fetch selected bands, optionally merging them into one GeoTIFF. Band names are collection-specific: Sentinel-2 uses names such as `B02`, `B03`, `B04`, `B08`; Landsat examples use `blue`, `green`, `red`, `nir08`.

## Frameworks introduced

- **Metadata-first acquisition**: search → inspect item/assets → download → inspect raster.
  - Use it for Planetary Computer, STAC-compatible catalogs, and reproducible date/area selection.
- **Sensor-aware band contract**: name physical bands in configuration, then map them to raster indices.
- **Open-data route selection**: use `download_naip` for NAIP; use STAC for Sentinel-2/Landsat; use Overture/OSM utilities for vector context; use source.coop examples for smoke tests.

## Useful methods

- `geoai.download_naip(bbox, output_dir, year, max_items=...)`
- `geoai.download_pc_stac_item(item_url, bands=..., merge_bands=True, ...)`
- `geoai.pc_stac_download(items, output_dir, assets=..., max_workers=...)`
- `geoai.download_overture_buildings(...)` or `geoai.get_overture_data(...)`
- `leafmap.osm.quackosm_gdf_from_bbox(...)` for OSM features.

## Data organization

Keep raw downloads immutable. Store a manifest with source/catalog, item IDs, dates, bbox, cloud threshold, selected assets, output file, CRS, and checksum if available. Use a separate processed/tiles directory and make filenames encode sensor/date/area rather than only a sequential number.

## Anti-patterns

- **Downloading the first search result**: it may have clouds, wrong season, or insufficient coverage.
- **Hard-coding asset names across sensors**: the same word can refer to different bands/resolutions.
- **Mixing scenes without normalizing scale or resolution**: models learn acquisition artifacts.

## Key takeaways

1. Search by space, time, collection, and quality metadata.
2. Inspect assets and band semantics before download.
3. Preserve provenance so the same scene can be retrieved later.

## Connects to

- **Ch03**: metadata and raster contracts.
- **Ch05**: visual inspection of acquired data.
- **Ch06**: turning downloads into training-ready datasets.
