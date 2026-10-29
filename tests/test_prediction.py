import json
from pathlib import Path

import httpx
import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.linear_model import Ridge

from src.prediction import TARGET
from src.prediction.api_client import APIError, ReadingsClient
from src.prediction.forecast import forecast
from src.prediction.mock_api import create_app, synthetic_hourly
from src.prediction.model_loader import load_bundle
from src.prediction.pipeline import run
from src.prediction.preprocessing import (
    build_features,
    max_horizon,
    records_to_frame,
    required_history,
    to_hourly,
)

ROOT = Path(__file__).resolve().parents[1]
TARGET_ONLY = ["lag_1", "lag_2", "lag_24", "lag_168", "rolling_mean_24", "rolling_std_24", "hour", "dayofweek", "is_weekend"]


def save_model(model_dir: Path, hourly: pd.DataFrame, features: list[str]) -> Path:
    """Trains a model the way Task 1 is expected to: build_features + dropna + fit."""
    X = build_features(hourly, features)
    data = X.assign(y=hourly[TARGET]).dropna()
    model = Ridge(alpha=1.0).fit(data[features], data["y"])
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_dir / "model.joblib")
    (model_dir / "model_metadata.json").write_text(
        json.dumps({"model_type": "sklearn", "model_file": "model.joblib", "target": TARGET, "features": features})
    )
    return model_dir


@pytest.fixture(scope="module")
def hourly():
    return synthetic_hourly(hours=24 * 28)


@pytest.fixture(scope="module")
def http(hourly):
    return TestClient(create_app(hourly))


@pytest.fixture(scope="module")
def minute_http(hourly):
    """Minute-level readings like the Task 2 databases, with a few missing ("?") minutes."""
    minutes = hourly.resample("1min").ffill()
    minutes.iloc[::97] = np.nan
    return TestClient(create_app(minutes))


@pytest.fixture(scope="module")
def model_dir(tmp_path_factory, hourly):
    return save_model(tmp_path_factory.mktemp("models"), hourly, TARGET_ONLY)


def test_records_to_frame_flattens_nested_mongo_documents():
    docs = [
        {
            "_id": "a",
            "timestamp": {"$date": "2010-01-01T01:00:00Z"},
            "measurements": {"Global_active_power": "1.5", "voltage": 240},
            "sub_metering": {"kitchen": 1, "laundry": 2, "water_heater_ac": 3},
        },
        {"_id": "b", "datetime": "2010-01-01T00:00:00Z", "measurements": {"global_active_power": 1.0}},
    ]
    df = records_to_frame(docs)
    assert list(df["timestamp"]) == [pd.Timestamp("2010-01-01 00:00"), pd.Timestamp("2010-01-01 01:00")]
    assert df["global_active_power"].tolist() == [1.0, 1.5]
    assert df.loc[1, "sub_metering_3"] == 3


def test_records_to_frame_reads_task2_mongo_sample_documents():
    docs = json.loads((ROOT / "mongodb" / "sample_documents.json").read_text())["energy_readings"]
    df = records_to_frame(docs)
    assert df.loc[0, "timestamp"] == pd.Timestamp("2006-12-16 17:24")
    assert df.loc[0, "global_active_power"] == 4.216
    assert df.loc[0, "sub_metering_3"] == 17.0
    assert df.iloc[-1].drop("timestamp").isna().all()


def test_records_to_frame_reads_task2_mysql_rows():
    rows = [
        {"measurement_id": 2, "source_id": 1, "measured_at": "2006-12-16 17:25:00", "global_active_power": "5.360"},
        {"measurement_id": 3, "source_id": 1, "measured_at": "2006-12-16 17:26:00", "global_active_power": None},
    ]
    df = records_to_frame(rows)
    assert list(df["timestamp"]) == [pd.Timestamp("2006-12-16 17:25"), pd.Timestamp("2006-12-16 17:26")]
    assert df["global_active_power"].iloc[0] == 5.36
    assert np.isnan(df["global_active_power"].iloc[1])
    assert "source_id" not in df.columns


def test_records_to_frame_joins_raw_date_and_time_columns():
    df = records_to_frame([{"Date": "16/12/2006", "Time": "17:24:00", "Global_active_power": "?"}])
    assert df.loc[0, "timestamp"] == pd.Timestamp("2006-12-16 17:24")
    assert np.isnan(df.loc[0, "global_active_power"])


def test_records_to_frame_rejects_records_without_target():
    with pytest.raises(ValueError, match="global_active_power"):
        records_to_frame([{"timestamp": "2010-01-01T00:00:00", "voltage": 240}])


def test_to_hourly_averages_minutes_and_drops_incomplete_last_hour():
    index = pd.date_range("2010-01-01 00:00", "2010-01-01 02:29", freq="1min")
    df = pd.DataFrame({"timestamp": index, TARGET: np.r_[np.full(60, 1.0), np.full(60, 3.0), np.full(30, 9.0)]})
    hourly, report = to_hourly(df)
    assert hourly[TARGET].tolist() == [1.0, 3.0]
    assert report.dropped_partial_hour


def test_to_hourly_interpolates_missing_hours():
    df = pd.DataFrame({"timestamp": pd.to_datetime(["2010-01-01 00:00", "2010-01-01 03:00"]), TARGET: [1.0, 4.0]})
    hourly, report = to_hourly(df)
    assert hourly[TARGET].tolist() == [1.0, 2.0, 3.0, 4.0]
    assert (report.imputed_hours, report.longest_gap_hours) == (2, 2)


def test_build_features_uses_only_past_values(hourly):
    feats = build_features(hourly, ["lag_1", "lag_24", "rolling_mean_24", "voltage_lag_2", "hour"])
    y = hourly[TARGET]
    t = hourly.index[100]
    assert feats.loc[t, "lag_1"] == y.iloc[99]
    assert feats.loc[t, "lag_24"] == y.iloc[76]
    assert feats.loc[t, "rolling_mean_24"] == pytest.approx(y.iloc[76:100].mean())
    assert feats.loc[t, "voltage_lag_2"] == hourly["voltage"].iloc[98]
    assert feats.loc[t, "hour"] == t.hour


def test_build_features_rejects_unknown_names(hourly):
    with pytest.raises(ValueError, match="Unknown feature"):
        build_features(hourly, ["lag24"])


def test_history_and_horizon_limits():
    assert required_history(TARGET_ONLY) == 168
    assert required_history(["rolling_mean_168"]) == 169
    assert max_horizon(TARGET_ONLY) == 10_000
    assert max_horizon(["lag_1", "voltage_lag_3"]) == 3
    assert max_horizon(["lag_1", "voltage"]) == 0
    assert max_horizon(["lag_1", "voltage"], sequence_model=True) == 1


def test_forecast_is_recursive_and_accurate(hourly, model_dir):
    bundle = load_bundle(model_dir)
    history, future = hourly.iloc[:-24], hourly[TARGET].iloc[-24:]
    predictions = forecast(history, bundle, horizon=24)
    assert list(predictions.index) == list(future.index)
    assert (predictions >= 0).all()
    assert (predictions - future).abs().mean() < 0.2


def test_forecast_refuses_horizon_beyond_exogenous_lags(hourly, tmp_path):
    bundle = load_bundle(save_model(tmp_path, hourly, ["lag_1", "lag_24", "voltage_lag_1"]))
    assert len(forecast(hourly, bundle, horizon=1)) == 1
    with pytest.raises(ValueError, match="1 hour"):
        forecast(hourly, bundle, horizon=2)


@pytest.mark.parametrize("source", ["sql", "mongo"])
def test_pipeline_forecasts_next_hour_after_latest(http, hourly, model_dir, source):
    result = run(ReadingsClient(source=source, http=http), model_dir, horizon=3)
    assert result.anchor == hourly.index[-1]
    assert list(result.predictions.index) == list(pd.date_range(hourly.index[-1], periods=4, freq="1h")[1:])
    assert result.actuals is None


@pytest.mark.parametrize("source", ["sql", "mongo"])
def test_pipeline_backtest_compares_with_actuals(http, hourly, model_dir, source):
    as_of = hourly.index[-30]
    result = run(ReadingsClient(source=source, http=http), model_dir, horizon=6, as_of=as_of)
    assert result.history.index[-1] == as_of
    assert result.actuals.tolist() == pytest.approx(hourly[TARGET].iloc[-29:-23].round(4).tolist())
    assert result.mae < 0.2


@pytest.mark.parametrize("source", ["sql", "mongo"])
def test_pipeline_handles_minute_level_readings(minute_http, hourly, model_dir, source):
    result = run(ReadingsClient(source=source, http=minute_http), model_dir, horizon=2)
    # The last hour only has its first minute, so it is dropped and forecast instead.
    assert result.report.dropped_partial_hour
    assert result.anchor == hourly.index[-2]
    assert result.predictions.index[0] == hourly.index[-1]
    assert result.history[TARGET].iloc[-24:].tolist() == pytest.approx(hourly[TARGET].iloc[-25:-1].tolist(), abs=1e-4)


def test_pipeline_reports_too_little_history(http, hourly, model_dir):
    with pytest.raises(ValueError, match="needs 168"):
        run(ReadingsClient(http=http), model_dir, as_of=hourly.index[100])


def test_missing_model_metadata_is_explained(http, tmp_path):
    with pytest.raises(FileNotFoundError, match="model_metadata.json"):
        run(ReadingsClient(http=http), tmp_path)


def test_unreachable_api_is_explained():
    client = ReadingsClient("http://127.0.0.1:9", http=httpx.Client(base_url="http://127.0.0.1:9", timeout=1))
    with pytest.raises(APIError, match="Is it running"):
        client.latest()
