# Chapter 17: Setting Up the GeoAI QGIS Plugin

## Core idea

The GeoAI QGIS plugin brings the book’s workflows into a desktop GIS. Setup is complete only when QGIS, plugin, Python dependencies, model cache/access, GPU/CPU choice, and a small test raster all work together.

## Installation routes

- **Plugin Manager**: recommended for normal QGIS users; install/update from QGIS.
- **Helper script**: clone the official `opengeos/geoai` repository, enter `qgis_plugin`, and run `python install.py`; removal uses `python install.py --remove`.
- **Manual**: use when packaging or enterprise constraints require explicit placement.

## Dependency routes

The built-in dependency installer is the simplest route. Advanced users can use Pixi and verify PyTorch/CUDA:

```bash
pixi run python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
pixi run pip install deepforest
pixi run pip install -U numpy transformers
```

Set a writable cache when model downloads fail or the default location is unsuitable. On Windows PowerShell, the book uses:

```powershell
$env:GEOAI_CACHE_DIR = "D:\geoai_cache"
```

SAM 3 may require Hugging Face access/authentication and model download; do not assume access is automatic.

## Frameworks introduced

- **Plugin setup gate**: install → enable → install dependencies → verify torch/GPU → verify model access → run a small panel job.
- **Resource-aware GUI**: QGIS shares memory with the model and map canvas; clear GPU memory between large models and keep one task active when possible.

## Anti-patterns

- **Debugging the panel before the dependency smoke test**.
- **Installing packages into a different Python than QGIS uses**.
- **Deleting the model cache to fix every error**: first inspect permissions, disk space, model access, and versions.

## Key takeaways

1. Record QGIS, plugin, Python, PyTorch, CUDA, and model revisions.
2. Test on a small raster before a full scene.
3. Treat GPU memory and cache paths as part of the workflow configuration.

## Connects to

- **Ch02**: environment verification.
- **Ch18–Ch23**: panel-specific configuration.
