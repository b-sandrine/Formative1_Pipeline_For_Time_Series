"""One-step and recursive multi-step forecasting on top of a loaded ModelBundle."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.prediction.model_loader import ModelBundle
from src.prediction.preprocessing import MAX_GAP_HOURS, build_features, max_horizon, required_history


class MissingDataError(ValueError):
    pass


def forecast(hourly: pd.DataFrame, bundle: ModelBundle, horizon: int = 1) -> pd.Series:
    """Forecasts the `horizon` hours after the last row of `hourly`.

    Each step appends an empty hour, computes its features from the history, predicts it,
    and writes the prediction back so the next step's lags can use it.
    """
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    limit = max_horizon(bundle.features, bundle.target, bundle.is_sequence)
    if horizon > limit:
        raise ValueError(
            f"The model's features only support forecasting {limit} hour(s) ahead: features built from "
            f"measurements other than {bundle.target!r} are unknown further into the future."
        )

    # Only the most recent rows affect the next hour's features.
    frame = hourly.iloc[-(required_history(bundle.features) + bundle.sequence_length + 1) :].copy()
    step = pd.Timedelta(bundle.frequency)
    predictions = {}
    for _ in range(horizon):
        next_ts = frame.index[-1] + step
        frame.loc[next_ts] = np.nan
        features = build_features(frame, bundle.features, bundle.target)
        X = features.iloc[-bundle.sequence_length - 1 : -1] if bundle.is_sequence else features.iloc[[-1]]
        if X.isna().any().any() or len(X) < max(bundle.sequence_length, 1):
            missing = X.columns[X.isna().any()].tolist() or bundle.features
            raise MissingDataError(
                f"Can't forecast {next_ts}: {', '.join(missing)} need readings that are missing "
                f"(a gap longer than {MAX_GAP_HOURS}h, or the database doesn't cover the hours before it)."
            )
        value = max(bundle.predict(X), 0.0)
        frame.loc[next_ts, bundle.target] = value
        predictions[next_ts] = value
    return pd.Series(predictions, name=f"predicted_{bundle.target}")
