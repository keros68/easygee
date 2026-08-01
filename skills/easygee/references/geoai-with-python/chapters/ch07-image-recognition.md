# Chapter 7: Image Recognition

## Core idea

Image recognition assigns one or more scene-level labels to an image/tile. It is the right abstraction when the question is “what type of place is this?” rather than “where is each object?”

## Frameworks introduced

- **Transfer-learning baseline**: load a structured image dataset → inspect class balance/examples → fine-tune a pre-trained backbone → evaluate on held-out images → inspect confusion/predictions → publish if useful.
- **Architecture ladder**: compare ResNet, EfficientNet, Vision Transformer, or ConvNeXt only after the data split, transforms, and metric are fixed.

## Practical workflow

The book uses EuroSAT RGB as a reproducible example. `load_image_dataset` discovers classes and paths; `train_image_classifier` returns a model, datasets, class names, and training artifacts.

```python
result = train_image_classifier(
    data_dir=data_dir,
    model_name="resnet50",
    num_epochs=5,
    batch_size=32,
    learning_rate=1e-3,
    image_size=64,
    in_channels=3,
    pretrained=True,
    output_dir="image_recognition_output/resnet50",
    seed=42,
)
```

Use `evaluate_classifier` for test metrics and confusion matrix; use `predict_images` for selected examples and show probabilities alongside true labels. Compare EfficientNet-B0 or another architecture with the same seed/split. `push_classifier_to_hub` and `predict_images_from_hub` provide a reuse path, but keep the class order and image preprocessing configuration with the model.

## Key concepts

- **ImageFolder structure**: directory/class organization can define labels.
- **Pretrained weights**: useful when target imagery resembles the source domain; fine-tuning depth and learning rate control adaptation.
- **Confusion matrix**: reveals classes that visually overlap even when aggregate accuracy looks acceptable.
- **Class probability**: useful for triage, but not automatically calibrated confidence.

## Mental models

Use recognition as a **routing stage** when it can select scenes for more expensive detection/segmentation. Think of a tile label as **context**, not geometry; do not use it to claim exact object counts.

## Anti-patterns

- **Evaluating only accuracy** on imbalanced classes: report per-class behavior and confusion.
- **Changing model and preprocessing together**: you cannot attribute improvement.
- **Applying RGB-only model to multispectral data** without matching channels/weights.

## Key takeaways

1. Keep class names, transforms, split, and seed with the checkpoint.
2. Inspect confusion and representative errors.
3. Use recognition for scene classification or routing, not object boundaries.

## Connects to

- **Ch06**: dataset layout and split quality.
- **Ch08**: upgrade from image labels to object locations.
- **Ch16**: embeddings as a lightweight alternative for classification.
