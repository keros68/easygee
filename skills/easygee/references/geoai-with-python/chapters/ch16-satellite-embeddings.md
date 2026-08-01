# Chapter 16: Satellite Embeddings

## Core idea

Satellite embeddings turn image patches, pixels, or scenes into vectors that can be searched, clustered, compared across time, or fed to lightweight classifiers. They decouple representation learning from task-specific modeling.

## Dataset-first workflow

Use GeoAI to list embedding datasets and inspect metadata before downloading:

```python
df = geoai.list_embedding_datasets(verbose=False)
info = geoai.get_embedding_info("clay")
```

For a Hugging Face dataset, download GeoParquet tiles with `hf_hub_download`, combine the `embeddings` column, and keep the GeoDataFrame CRS. Join labels spatially, split embeddings into train/validation sets, then train kNN, random forest, or logistic regression with `train_embedding_classifier`.

## Analysis methods

- `visualize_embeddings(..., method="pca")` to inspect separability.
- `cluster_embeddings(..., n_clusters=..., method="kmeans")` to find latent groups.
- `embedding_similarity(query, embeddings, metric="cosine", top_k=...)` for nearest-neighbor retrieval.
- `compare_embeddings(emb_a, emb_b, metric="cosine")` for temporal/paired similarity.
- `tessera_available_years`, `tessera_download`, `tessera_fetch_embeddings`, and `tessera_sample_points` for temporal TESSERA workflows.
- AlphaEarth GUI/map methods for inspecting embedding layers and change similarity.

## Frameworks introduced

- **Representation → simple learner**: use a stable embedding plus a small classifier before expensive fine-tuning.
- **Spatial join before labels**: match labels to embedding patches in a common CRS, then inspect unmatched/ambiguous cases.
- **Similarity is task-dependent**: cosine similarity indicates representation proximity, not necessarily physical change or semantic identity.

## Mental models

Think of an embedding as a searchable coordinate in learned feature space, not a measurement with inherent units. Use spatially independent validation because neighboring patches can be nearly identical.

## Anti-patterns

- **Mixing embeddings from different models/dimensions without a documented transform**.
- **Training and validating on neighboring patches from the same footprint**.
- **Assuming a missing/extra Parquet column is a model error**: official TorchGeo products and custom GeoParquet schemas differ.

## Key takeaways

1. Inspect dataset metadata, year, sensor, CRS, and embedding dimension.
2. Use PCA/similarity/cluster views to diagnose before training a classifier.
3. Validate embeddings on new geography or time, not only random rows.

## Connects to

- **Ch04**: data discovery/provenance.
- **Ch12**: temporal change via similarity.
- **Ch16 references/source-map**: current embedding providers and APIs must be verified.
