"""Turns raw API records into a clean hourly series and builds model features from it.

`build_features` is the single definition of every lag, rolling and calendar feature, so
the Task 1 notebook can import it and train on exactly what this script predicts with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.prediction import MEASUREMENTS, TARGET

KEY_ALIASES = {
    "measured_at": "timestamp",
    "datetime": "timestamp",
    "date_time": "timestamp",
    "time_stamp": "timestamp",
    "kitchen": "sub_metering_1",
    "laundry": "sub_metering_2",
    "water_heater_ac": "sub_metering_3",
    "water_heater": "sub_metering_3",
}
IGNORED_KEYS = {"_id", "id", "measurement_id", "source_id", "reading_id", "household_id"}

# Task 1 names features like power_lag_1h / intensity_lag_1h / rolling_mean_24h.
COLUMN_ALIASES = {"power": TARGET, "intensity": "global_intensity", "reactive_power": "global_reactive_power"}

LAG_RE = re.compile(r"^(?:(?P<col>[a-z0-9_]+?)_)?lag_(?P<k>\d+)$")
ROLLING_RE = re.compile(r"^(?:(?P<col>[a-z0-9_]+?)_)?rolling_(?P<stat>mean|std|min|max)_(?P<w>\d+)$")

CALENDAR = {
    "hour": lambda idx: idx.hour,
    "dayofweek": lambda idx: idx.day_of_week,
    "day_of_week": lambda idx: idx.day_of_week,
    "month": lambda idx: idx.month,
    "dayofyear": lambda idx: idx.dayofyear,
    "is_weekend": lambda idx: (idx.day_of_week >= 5).astype(int),
    "hour_sin": lambda idx: np.sin(2 * np.pi * idx.hour / 24),
    "hour_cos": lambda idx: np.cos(2 * np.pi * idx.hour / 24),
    "dow_sin": lambda idx: np.sin(2 * np.pi * idx.day_of_week / 7),
    "dow_cos": lambda idx: np.cos(2 * np.pi * idx.day_of_week / 7),
    "month_sin": lambda idx: np.sin(2 * np.pi * (idx.month - 1) / 12),
    "month_cos": lambda idx: np.cos(2 * np.pi * (idx.month - 1) / 12),
}


@dataclass
class PreprocessReport:
    raw_records: int
    hours: int
    imputed_hours: int
    longest_gap_hours: int
    dropped_partial_hour: bool


def records_to_frame(records: list[dict]) -> pd.DataFrame:
    """Flattens API records (flat SQL rows or nested Mongo documents) into one row per reading."""
    if not records:
        raise ValueError("No records to preprocess.")
    df = pd.DataFrame([_flatten(r) for r in records])

    if "timestamp" not in df.columns:
        if {"date", "time"} <= set(df.columns):
            df["timestamp"] = pd.to_datetime(df["date"] + " " + df["time"], dayfirst=True)
        else:
            raise ValueError(f"Records have no timestamp field. Keys seen: {sorted(df.columns)}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="mixed").dt.tz_localize(None)

    if TARGET not in df.columns:
        raise ValueError(f"Records have no {TARGET!r} field. Keys seen: {sorted(df.columns)}")
    columns = [c for c in MEASUREMENTS if c in df.columns]
    df[columns] = df[columns].apply(pd.to_numeric, errors="coerce")
    return df[["timestamp", *columns]].sort_values("timestamp").reset_index(drop=True)


def to_hourly(df: pd.DataFrame, freq: str = "1h") -> tuple[pd.DataFrame, PreprocessReport]:
    """Resamples to `freq` means and fills gaps by time interpolation, as in Task 1.

    Works for both minute-level and already-hourly records. A trailing bucket that is
    still filling up (minute data whose last hour is incomplete) is dropped so a partial
    average is never treated as a real reading.
    """
    series = df.set_index("timestamp")
    series = series[~series.index.duplicated(keep="last")].sort_index()
    step = pd.Timedelta(freq)

    dropped_partial = False
    if len(series) > 1:
        spacing = series.index.to_series().diff().median()
        last = series.index[-1]
        if spacing < step and last + spacing < last.floor(freq) + step:
            series = series[series.index < last.floor(freq)]
            dropped_partial = True

    hourly = series.resample(freq).mean()
    missing = hourly[TARGET].isna()
    longest_gap = int(missing.groupby((~missing).cumsum()).sum().max()) if missing.any() else 0
    hourly = hourly.interpolate(method="time", limit_direction="both")

    report = PreprocessReport(
        raw_records=len(df),
        hours=len(hourly),
        imputed_hours=int(missing.sum()),
        longest_gap_hours=longest_gap,
        dropped_partial_hour=dropped_partial,
    )
    return hourly, report


def build_features(hourly: pd.DataFrame, features: list[str], target: str = TARGET) -> pd.DataFrame:
    """Computes the named features for every row of an hourly frame.

    Row t only ever sees values up to t-1, so the frame can be used directly for training
    (target = hourly[target]) and for forecasting the next hour:
      lag_k                 target at t-k
      rolling_<stat>_w      mean/std/min/max of target over t-w .. t-1
      <col>_lag_k           another measurement at t-k (e.g. voltage_lag_1)
      <col>_rolling_mean_w  same as rolling, for another measurement
      hour, dayofweek, ...  calendar features of hour t (see CALENDAR)
      <col>                 the raw measurement at t (only valid for sequence models)
    """
    out = pd.DataFrame(index=hourly.index)
    for name in features:
        out[name] = _feature(hourly, canonical_feature(name), target)
    return out


def canonical_feature(name: str) -> str:
    """Maps alternative spellings onto the scheme above: power_lag_1h -> global_active_power_lag_1."""
    name = re.sub(r"(\d+)h$", r"\1", name.strip().lower())
    for alias, column in COLUMN_ALIASES.items():
        if name.startswith((f"{alias}_lag_", f"{alias}_rolling_")):
            return column + name[len(alias):]
    return name


def required_history(features: list[str]) -> int:
    """Hours of past data needed before the first row has every feature defined."""
    needed = 1
    for name in map(canonical_feature, features):
        if m := LAG_RE.match(name):
            needed = max(needed, int(m["k"]))
        elif m := ROLLING_RE.match(name):
            needed = max(needed, int(m["w"]) + 1)
    return needed


def max_horizon(features: list[str], target: str = TARGET, sequence_model: bool = False) -> int:
    """Longest recursive forecast the features allow.

    Forecasts beyond one hour feed predictions back in as the target, but other
    measurements (voltage, intensity, ...) are unknown in the future, so a feature like
    voltage_lag_2 caps the horizon at 2 hours.
    """
    limit = 10_000
    for name in map(canonical_feature, features):
        if name in CALENDAR:
            continue
        if m := LAG_RE.match(name):
            if (m["col"] or target) != target:
                limit = min(limit, int(m["k"]))
        elif m := ROLLING_RE.match(name):
            if (m["col"] or target) != target:
                limit = min(limit, 1)
        elif name != target:
            limit = min(limit, 1 if sequence_model else 0)
    return limit


def _feature(hourly: pd.DataFrame, name: str, target: str) -> pd.Series:
    if name in CALENDAR:
        return pd.Series(np.asarray(CALENDAR[name](hourly.index)), index=hourly.index, dtype=float)
    if m := LAG_RE.match(name):
        return _source(hourly, m["col"], target, name).shift(int(m["k"]))
    if m := ROLLING_RE.match(name):
        window = _source(hourly, m["col"], target, name).shift(1).rolling(int(m["w"]))
        return getattr(window, m["stat"])()
    if name in hourly.columns:
        return hourly[name]
    raise ValueError(
        f"Unknown feature {name!r}. Use the naming scheme in src/prediction/preprocessing.py "
        f"(lag_24, rolling_mean_24, voltage_lag_1, hour, ...)."
    )


def _source(hourly: pd.DataFrame, col: str | None, target: str, feature: str) -> pd.Series:
    column = col or target
    if column not in hourly.columns:
        raise ValueError(f"Feature {feature!r} needs column {column!r}, which the API data does not have.")
    return hourly[column]


def _flatten(record: dict, out: dict | None = None) -> dict:
    out = {} if out is None else out
    for key, value in record.items():
        norm = str(key).strip().lower().replace(" ", "_")
        key = KEY_ALIASES.get(norm, norm)
        if key in IGNORED_KEYS:
            continue
        if isinstance(value, dict) and "$date" not in value:
            _flatten(value, out)
        elif isinstance(value, dict):
            out[key] = value["$date"]
        elif not isinstance(value, list):
            out[key] = value
    return out
