"""Check local and optional GEE dependencies without reading credentials."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import sys


REQUIRED = {
    "numpy": "numpy",
    "PIL": "Pillow",
    "rasterio": "rasterio",
    "geopandas": "geopandas",
    "shapely": "shapely",
    "skimage": "scikit-image",
}
GEE = {"ee": "earthengine-api", "geemap": "geemap"}


def inspect(packages: dict[str, str]) -> list[dict[str, object]]:
    rows = []
    for module, distribution in packages.items():
        installed = importlib.util.find_spec(module) is not None
        version = None
        if installed:
            try:
                version = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                pass
        rows.append({"module": module, "distribution": distribution, "installed": installed, "version": version})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["local", "gee", "all"], default="all")
    args = parser.parse_args()
    required = inspect(REQUIRED)
    gee = inspect(GEE) if args.mode in {"gee", "all"} else []
    ok = all(row["installed"] for row in required + gee)
    print(json.dumps({"python": sys.executable, "python_version": sys.version.split()[0], "required": required, "gee_optional": gee, "ok": ok}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
