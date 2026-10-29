"""Loads the Task 1 model and its metadata (see docs/INTEGRATION_CONTRACT.md for the format)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.prediction import TARGET

METADATA_FILE = "model_metadata.json"
MODEL_TYPES = ("sklearn", "keras")


@dataclass
class ModelBundle:
    model: object
    features: list[str]
    target: str = TARGET
    model_type: str = "sklearn"
    frequency: str = "1h"
    sequence_length: int = 0
    feature_scaler: object = None
    target_scaler: object = None
    metadata: dict = field(default_factory=dict)

    @property
    def is_sequence(self) -> bool:
        return self.model_type == "keras"

    def predict(self, X: pd.DataFrame) -> float:
        """Predicts one value: X is one feature row (sklearn) or `sequence_length` rows (keras)."""
        if self.is_sequence:
            values = X.to_numpy(dtype=float)
            if self.feature_scaler is not None:
                values = self.feature_scaler.transform(values)
            y = self.model.predict(values[np.newaxis, ...], verbose=0)
        else:
            if self.feature_scaler is not None:
                X = pd.DataFrame(self.feature_scaler.transform(X), columns=X.columns, index=X.index)
            y = self.model.predict(X)
        y = np.asarray(y, dtype=float).reshape(-1, 1)[:1]
        if self.target_scaler is not None:
            y = self.target_scaler.inverse_transform(y)
        return float(y[0, 0])


def load_bundle(model_dir: str | Path) -> ModelBundle:
    model_dir = Path(model_dir)
    meta_path = model_dir / METADATA_FILE
    if not meta_path.exists():
        raise FileNotFoundError(
            f"{meta_path} not found. Task 1 must save the model and its metadata to {model_dir}/ "
            f"(see docs/INTEGRATION_CONTRACT.md)."
        )
    meta = json.loads(meta_path.read_text())

    model_type = meta.get("model_type", "sklearn")
    if model_type not in MODEL_TYPES:
        raise ValueError(f"model_type must be one of {MODEL_TYPES}, got {model_type!r}")
    features = meta.get("features")
    if not features:
        raise ValueError(f"{meta_path} must list the model's input columns under 'features', in training order.")
    sequence_length = int(meta.get("sequence_length") or 0)
    if model_type == "keras" and sequence_length < 1:
        raise ValueError("Keras models need 'sequence_length' (how many past hours the LSTM reads) in the metadata.")

    model_file = model_dir / meta.get("model_file", "model.keras" if model_type == "keras" else "model.joblib")
    if not model_file.exists():
        raise FileNotFoundError(f"Model file {model_file} not found.")

    return ModelBundle(
        model=_load_keras(model_file) if model_type == "keras" else joblib.load(model_file),
        features=list(features),
        target=meta.get("target", TARGET),
        model_type=model_type,
        frequency=meta.get("frequency", "1h"),
        sequence_length=sequence_length,
        feature_scaler=_optional(model_dir, meta.get("feature_scaler_file")),
        target_scaler=_optional(model_dir, meta.get("target_scaler_file")),
        metadata=meta,
    )


def _optional(model_dir: Path, name: str | None):
    return joblib.load(model_dir / name) if name else None


def _load_keras(path: Path):
    try:
        from tensorflow import keras
    except ImportError as exc:
        raise ImportError("This model is a Keras model; install tensorflow to load it.") from exc
    return keras.models.load_model(path)
