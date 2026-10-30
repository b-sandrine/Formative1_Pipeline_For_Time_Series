"""End-to-end Task 4 pipeline: load model -> fetch from API -> preprocess -> forecast."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.prediction.api_client import ReadingsClient
from src.prediction.forecast import MissingDataError, forecast
from src.prediction.model_loader import ModelBundle, load_bundle
from src.prediction.preprocessing import (
    PreprocessReport,
    fill_short_gaps,
    records_to_frame,
    required_history,
    resample_hourly,
)

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
    skipped_hours: list[pd.Timestamp] = field(default_factory=list)

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
    backtest_hours: int = 0,
) -> PipelineResult:
    """Forecasts `horizon` hours after the latest reading, or after `as_of` for a backtest.

    In backtest mode the real readings for the forecast window are fetched too, so the
    prediction can be compared with what actually happened. With `backtest_hours`, each of
    those hours is forecast one step ahead from the data available just before it; hours
    whose inputs fall in a data gap are skipped and listed in `skipped_hours`.
    """
    if horizon < 1:
        raise ValueError("--horizon must be at least 1.")
    if backtest_hours < 0:
        raise ValueError("--backtest-hours can't be negative.")
    if backtest_hours and (as_of is None or horizon != 1):
        raise ValueError("--backtest-hours needs --as-of and forecasts one hour at a time (horizon 1).")
    bundle = load_bundle(model_dir)
    freq, step = bundle.frequency, pd.Timedelta(bundle.frequency)
    lookback = lookback_hours or required_history(bundle.features) + bundle.sequence_length + HISTORY_BUFFER_HOURS

    live = as_of is None
    if live:
        anchor = records_to_frame(client.latest(), target=None)["timestamp"].max().floor(freq)
    else:
        anchor = pd.Timestamp(as_of).floor(freq)

    steps = max(backtest_hours, 1)
    start = anchor - (lookback - 1) * step
    # A backtest also needs the readings of every forecast hour, to compare against.
    end = anchor + (step if live else (steps + horizon) * step) - pd.Timedelta(seconds=1)
    records = client.by_range(start.to_pydatetime(), end.to_pydatetime())
    if not records:
        raise ValueError(f"The API returned no {client.source} readings between {start} and {end}.")
    readings = records_to_frame(records, bundle.target)

    # Hourly buckets are independent, so resampling once and slicing at each cutoff
    # gives exactly the history that was known at that hour.
    hourly_all, dropped_partial = resample_hourly(readings, freq, drop_partial=live)
    if live:
        anchor = min(anchor, hourly_all.index[-1])

    history, report, predictions, skipped = None, None, [], []
    for k in range(steps):
        cutoff = anchor + k * step
        window = hourly_all.reindex(pd.date_range(start, cutoff, freq=freq))
        hourly, imputed, longest_gap = fill_short_gaps(window, bundle.target)
        if history is None:
            history = hourly
            report = PreprocessReport(len(readings), len(hourly), imputed, longest_gap, dropped_partial)
        try:
            predictions.append(forecast(hourly, bundle, horizon))
        except MissingDataError:
            if not backtest_hours:
                raise
            skipped.append(cutoff + step)
    if not predictions:
        raise MissingDataError(f"None of the {steps} backtest hours had enough readings before them to forecast.")

    predictions = pd.concat(predictions)
    actuals = None if live else _actuals(readings, predictions.index, bundle)
    return PipelineResult(client.source, anchor, bundle, history, report, predictions, actuals, skipped)


def _actuals(readings: pd.DataFrame, index: pd.DatetimeIndex, bundle: ModelBundle) -> pd.Series:
    # No gap filling here: the comparison should only use hours that were really measured.
    hourly = readings.set_index("timestamp")[bundle.target].resample(bundle.frequency).mean()
    return hourly.reindex(index).rename(f"actual_{bundle.target}")
