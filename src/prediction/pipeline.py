"""End-to-end Task 4 pipeline: load model -> fetch from API -> preprocess -> forecast."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.prediction.api_client import ReadingsClient
from src.prediction.forecast import forecast
from src.prediction.model_loader import ModelBundle, load_bundle
from src.prediction.preprocessing import PreprocessReport, records_to_frame, required_history, to_hourly

HISTORY_BUFFER_HOURS = 24


@dataclass
class PipelineResult:
    source: str
    anchor: pd.Timestamp  # last complete hour of history; the forecast starts the hour after
    bundle: ModelBundle
    history: pd.DataFrame
    report: PreprocessReport
    predictions: pd.Series
    actuals: pd.Series | None = None

    @property
    def mae(self) -> float | None:
        if self.actuals is None or self.actuals.dropna().empty:
            return None
        return float((self.predictions - self.actuals).abs().mean())


def run(
    client: ReadingsClient,
    model_dir: str | Path = "models",
    horizon: int = 1,
    as_of: datetime | str | None = None,
    lookback_hours: int | None = None,
) -> PipelineResult:
    """Forecasts `horizon` hours after the latest reading, or after `as_of` for a backtest.

    In backtest mode the real readings for the forecast window are fetched too, so the
    prediction can be compared with what actually happened.
    """
    bundle = load_bundle(model_dir)
    step = pd.Timedelta(bundle.frequency)
    needed = required_history(bundle.features) + bundle.sequence_length
    lookback = lookback_hours or needed + HISTORY_BUFFER_HOURS

    if as_of is not None:
        anchor = pd.Timestamp(as_of).floor(bundle.frequency)
    else:
        anchor = records_to_frame(client.latest())["timestamp"].max().floor(bundle.frequency)

    start = anchor - (lookback - 1) * step
    end = anchor + step - pd.Timedelta(seconds=1)
    records = client.by_range(start.to_pydatetime(), end.to_pydatetime())
    if not records:
        raise ValueError(f"The API returned no {client.source} readings between {start} and {end}.")

    hourly, report = to_hourly(records_to_frame(records), bundle.frequency)
    hourly = hourly[hourly.index <= anchor]
    if len(hourly) < needed:
        raise ValueError(
            f"Got {len(hourly)} hours of history from the API but the model needs {needed}. "
            f"Check that the database covers {start} to {anchor} and that the range endpoint isn't capping results."
        )

    predictions = forecast(hourly, bundle, horizon)
    actuals = _fetch_actuals(client, predictions.index, bundle) if as_of is not None else None
    return PipelineResult(client.source, hourly.index[-1], bundle, hourly, report, predictions, actuals)


def _fetch_actuals(client: ReadingsClient, index: pd.DatetimeIndex, bundle: ModelBundle) -> pd.Series | None:
    end = index[-1] + pd.Timedelta(bundle.frequency) - pd.Timedelta(seconds=1)
    records = client.by_range(index[0].to_pydatetime(), end.to_pydatetime())
    if not records:
        return None
    # No interpolation here: the comparison should only use hours that were really measured.
    readings = records_to_frame(records).set_index("timestamp")[bundle.target]
    hourly = readings.resample(bundle.frequency).mean()
    return hourly.reindex(index).rename(f"actual_{bundle.target}")
