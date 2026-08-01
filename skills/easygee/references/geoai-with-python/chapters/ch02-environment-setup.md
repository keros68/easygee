# Chapter 2: Setting Up Your Environment

## Core idea

GeoAI is easiest to debug when Python, PyTorch, CUDA, geospatial libraries, notebooks, and model caches are isolated and verified before a large download or training run.

## Recommended setup

Use a dedicated conda environment and choose GPU or CPU explicitly. The book’s baseline uses Python 3.13 and, for conda, packages such as `geoai`, `segment-geospatial`, and a CUDA-enabled PyTorch build.

```bash
conda create -n geoai python=3.13 -y
conda activate geoai
conda install -c conda-forge geoai segment-geospatial "pytorch=*=cuda*"
```

For a lightweight alternative, the book also shows:

```bash
uv pip install geoai-py segment-geospatial jupyterlab
```

Treat these as book-era starting points; verify current package constraints and CUDA compatibility before installation.

## Verification gate

Run `nvidia-smi` when a GPU is expected, then verify both PyTorch and GeoAI:

```python
import torch, geoai
print(torch.__version__, torch.cuda.is_available(), geoai.__version__)
if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0))
```

Also import `leafmap`, `geopandas`, `rasterio`, `samgeo`, and `torchgeo`. A missing optional package should be fixed before the workflow reaches that feature.

## Frameworks introduced

- **Environment ladder**: hardware/driver → Python manager → isolated environment → packages → model access → smoke test.
  - Use it when installation fails; stop at the first failing layer.
- **GPU fallback**: run a tiny CPU or small-tile test before assuming GPU acceleration is necessary.

## Operational rules

- Set a writable cache location for large models; QGIS examples use `GEOAI_CACHE_DIR`.
- Keep one environment per incompatible project and record package versions.
- Use smaller `batch_size`, `window_size`, or `tile_size` for out-of-memory errors before changing the model.
- Call `geoai.empty_cache()` between large inference/model stages when the library provides it.
- Use Jupyter/VS Code for interactive visualization, but save scripts or notebooks with configuration for reproducibility.

## Anti-patterns

- **Mixing system Python, conda, and pip without checking the interpreter**: packages install into a different environment.
- **Treating `torch.cuda.is_available()` as proof the model will fit**: memory and tensor shape still matter.
- **Installing latest everything blindly**: pin or record versions when reproducing a result.

## Key takeaways

1. Verify imports and CUDA before downloading large datasets.
2. Separate environment failure from data/model failure.
3. Keep cache, environment, and output paths explicit.

## Connects to

- **Ch17**: the same dependency logic inside QGIS.
- **Ch09–Ch16**: GPU memory and model access requirements.
