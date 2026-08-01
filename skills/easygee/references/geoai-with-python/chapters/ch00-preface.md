# Chapter 0: Preface

## Core idea

GeoAI becomes useful when geospatial data engineering and model inference are treated as one reproducible workflow. The book is hands-on: real satellite/aerial imagery, open-source Python tools, runnable examples, and a progression from foundations to QGIS.

## Frameworks introduced

- **Five-part learning path**: foundations → data acquisition/preparation → core AI tasks → foundation models/embeddings → QGIS plugins.
  - Use it when starting a new project or deciding what prerequisite is missing.
  - How: establish environment and data contracts first; acquire and inspect data; learn the task-specific method; then choose a foundation model or GUI route.
- **Practice-first learning**: run, inspect, modify, and debug examples rather than only reading theory.

## Key concepts

- **Audience**: GIS professionals, remote-sensing researchers, data scientists, students, and developers.
- **Prerequisites**: basic Python, data analysis, raster/vector/CRS concepts, and command-line use.
- **Cross-cutting themes**: open source, scalability, real-world applications, and reproducibility.
- **Book scope**: seven core tasks plus SAM, VLMs, satellite embeddings, and QGIS workflows.

## Mental models

Use the book sequentially when the environment, formats, or tiling rules are unfamiliar; jump to a task chapter only after reading the relevant foundation chapter. Think of every notebook as an experiment template: change one variable, keep the data split and validation evidence stable, and record the result.

## Anti-patterns

- **Starting with a model before checking data**: CRS, band order, scaling, nodata, and label alignment can invalidate an apparently successful run.
- **Treating a score as a map**: metrics do not reveal seams, geographic bias, small-object loss, or invalid polygons.
- **Copying commands without version checks**: model access and package APIs evolve.

## Key takeaways

1. Define the spatial problem and success evidence before choosing a model.
2. Keep source imagery, labels, training configuration, and outputs linked by provenance.
3. Use the smallest baseline that can disprove a bad data pipeline.

## Connects to

- **Ch01**: vocabulary and task choice.
- **Ch02–Ch06**: prerequisites used by every later workflow.
- **References/source-map.md**: official repository, data, and licensing boundaries.
