import json
from pathlib import Path

import httpx
import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge

from src.prediction import TARGET
from src.prediction.api_client import APIError, ReadingsClient
from src.prediction.forecast import MissingDataError, forecast
from src.prediction.mock_api import create_app, synthetic_hourly
from src.prediction.model_loader import load_bundle
from src.prediction.pipeline import run
from scripts.predict import parse_args
from src.prediction.preprocessing import (
    build_features,
    max_horizon,
    records_to_frame,
    required_history,
    fill_short_gaps,
    resample_hourly,
)

ROOT = Path(__file__).resolve().parents[1]
TARGET_ONLY = ["lag_1", "lag_2", "lag_24", "lag_168", "rolling_mean_24", "rolling_std_24", "hour", "dayofweek", "is_weekend"]


def api_client(app) -> httpx.Client:
    return httpx.Client(transport=httpx.WSGITransport(app=app), base_url="http://testserver")


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
    return api_client(create_app(hourly))


@pytest.fixture(scope="module")
def minute_http(hourly):
    """Minute-level readings like the Task 2 databases, with a few missing ("?") minutes."""
    minutes = hourly.resample("1min").ffill()
    minutes.iloc[::97] = np.nan
    return api_client(create_app(minutes))


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


def test_resample_averages_minutes_and_drops_incomplete_last_hour():
    index = pd.date_range("2010-01-01 00:00", "2010-01-01 02:29", freq="1min")
    df = pd.DataFrame({"timestamp": index, TARGET: np.r_[np.full(60, 1.0), np.full(60, 3.0), np.full(30, 9.0)]})
    hourly, dropped = resample_hourly(df, drop_partial=True)
    assert hourly[TARGET].tolist() == [1.0, 3.0]
    assert dropped
    # Historical data (backtests) keeps an hour whose final minutes are missing.
    assert resample_hourly(df)[0][TARGET].tolist() == [1.0, 3.0, 9.0]


def test_fill_short_gaps_interpolates_missing_hours():
    df = pd.DataFrame({"timestamp": pd.to_datetime(["2010-01-01 00:00", "2010-01-01 03:00"]), TARGET: [1.0, 4.0]})
    hourly, imputed, longest = fill_short_gaps(resample_hourly(df)[0])
    assert hourly[TARGET].tolist() == [1.0, 2.0, 3.0, 4.0]
    assert (imputed, longest) == (2, 2)


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
    with pytest.raises(MissingDataError, match="lag_168"):
        run(ReadingsClient(http=http), model_dir, as_of=hourly.index[100])


def test_missing_model_metadata_is_explained(http, tmp_path):
    with pytest.raises(FileNotFoundError, match="model_metadata.json"):
        run(ReadingsClient(http=http), tmp_path)


def test_unreachable_api_is_explained():
    client = ReadingsClient("http://127.0.0.1:9", http=httpx.Client(base_url="http://127.0.0.1:9", timeout=1))
    with pytest.raises(APIError, match="Is it running"):
        client.latest()


def test_task1_feature_names_match_task1_formulas(hourly):
    """Same math as scripts/train_model.py, so the model sees what it was trained on."""
    names = json.loads((ROOT / "models" / "model_metadata.json").read_text())["feature_names"]
    feats = build_features(hourly, names)
    expected = pd.DataFrame({
        "power_lag_1h": hourly[TARGET].shift(1),
        "power_lag_24h": hourly[TARGET].shift(24),
        "voltage_lag_1h": hourly["voltage"].shift(1),
        "intensity_lag_1h": hourly["global_intensity"].shift(1),
        "rolling_mean_24h": hourly[TARGET].rolling(window=24).mean().shift(1),
    })
    pd.testing.assert_frame_equal(feats, expected[names], check_freq=False)


@pytest.mark.parametrize("source", ["sql", "mongo"])
def test_pipeline_runs_with_task1_model_and_task3_api(minute_http, source):
    result = run(ReadingsClient(source=source, http=minute_http), ROOT / "models")
    assert result.bundle.target == TARGET
    assert len(result.predictions) == 1
    assert 0 <= result.predictions.iloc[0] < 10
    with pytest.raises(ValueError, match="1 hour"):
        run(ReadingsClient(source=source, http=minute_http), ROOT / "models", horizon=2)


def test_by_range_pages_through_the_api_limit(minute_http, hourly):
    client = ReadingsClient(http=minute_http)
    start, end = hourly.index[10].to_pydatetime(), hourly.index[20].to_pydatetime()
    paged = client.by_range(start, end, page_size=250)
    assert len(paged) == 600
    assert paged == client.by_range(start, end)


def test_walk_forward_backtest_forecasts_each_hour_from_its_own_past(minute_http, hourly):
    as_of = hourly.index[-30]
    result = run(ReadingsClient(http=minute_http), ROOT / "models", as_of=as_of, backtest_hours=12)
    assert list(result.predictions.index) == list(hourly.index[-29:-17])
    assert result.actuals.notna().all()
    assert result.history.index[-1] == as_of
    with pytest.raises(ValueError, match="--as-of"):
        run(ReadingsClient(http=minute_http), ROOT / "models", backtest_hours=12)


def test_long_gaps_stay_missing_and_tails_are_not_extrapolated():
    times = pd.to_datetime(["2010-01-01 00:00", "2010-01-01 02:00", "2010-01-01 08:00", "2010-01-01 09:00"])
    df = pd.DataFrame({"timestamp": times, TARGET: [1.0, 3.0, 9.0, 10.0]})
    raw = resample_hourly(df)[0]
    hourly, imputed, longest = fill_short_gaps(raw)
    assert hourly[TARGET].iloc[1] == 2.0
    assert hourly[TARGET].iloc[3:8].isna().all()
    assert (imputed, longest) == (1, 5)
    window = raw.reindex(pd.date_range("2009-12-31 20:00", "2010-01-01 11:00", freq="1h"))
    filled, _, longest = fill_short_gaps(window)
    assert filled[TARGET].iloc[:4].isna().all() and filled[TARGET].iloc[-2:].isna().all()
    assert longest == 5


def test_walk_forward_skips_hours_in_a_data_gap_without_repeating_any(hourly):
    minutes = hourly.resample("1min").ffill()
    gap = (minutes.index >= hourly.index[-20]) & (minutes.index < hourly.index[-15])
    http = api_client(create_app(minutes[~gap]))
    result = run(ReadingsClient(http=http), ROOT / "models", as_of=hourly.index[-30], backtest_hours=12)
    assert result.predictions.index.is_unique
    assert set(result.skipped_hours) == set(hourly.index[-19:-17])
    assert set(result.predictions.index) == set(hourly.index[-29:-17]) - set(result.skipped_hours)
    assert result.mae is not None


def test_by_range_does_not_lose_readings_that_share_a_timestamp():
    ts = "2010-01-01T00:00:00"
    minutes = [0, 1, 1, 2, 3, 3]
    rows = [{"measurement_id": i, "measured_at": f"2010-01-01T00:0{m}:00", TARGET: 1.0} for i, m in enumerate(minutes)]

    def handler(request):
        start = request.url.params["start_date"]
        limit = int(request.url.params["limit"])
        page = [r for r in rows if r["measured_at"] >= start][:limit]
        return httpx.Response(200, json={"readings": page})

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://testserver")
    client = ReadingsClient(http=http)
    got = client.by_range(pd.Timestamp(ts).to_pydatetime(), pd.Timestamp("2010-01-02").to_pydatetime(), page_size=2)
    assert sorted(r["measurement_id"] for r in got) == list(range(6))


def test_records_to_frame_uses_the_requested_target():
    df = records_to_frame([{"measured_at": "2010-01-01T00:00:00", "voltage": 240}], target="voltage")
    assert df.loc[0, "voltage"] == 240
    with pytest.raises(ValueError, match="global_intensity"):
        records_to_frame([{"measured_at": "2010-01-01T00:00:00", "voltage": 240}], target="global_intensity")


def test_cli_number_options(capsys):
    assert parse_args(["--backtest-hours", "0"]).backtest_hours == 0
    with pytest.raises(SystemExit):
        parse_args(["--lookback-hours", "0"])
    assert "must be at least 1" in capsys.readouterr().err


def test_run_validates_arguments_before_calling_the_api(model_dir):
    client = ReadingsClient(http=httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("API called"))))
    for kwargs in ({"horizon": 0}, {"backtest_hours": -3}, {"backtest_hours": 5}):
        with pytest.raises(ValueError):
            run(client, model_dir, **kwargs)


def test_client_closes_only_the_http_client_it_created():
    injected = httpx.Client()
    with ReadingsClient(http=injected):
        pass
    assert not injected.is_closed
    with ReadingsClient() as client:
        owned = client.http
    assert owned.is_closed


def test_gaps_are_judged_per_column():
    index = pd.date_range("2010-01-01", periods=10, freq="1h")
    hourly = pd.DataFrame({TARGET: np.arange(10.0), "voltage": np.arange(10.0) + 230}, index=index)
    hourly.loc[index[2], "voltage"] = np.nan  # 1h voltage gap, target complete: filled
    hourly.loc[index[4:9], TARGET] = np.nan  # 5h target gap: kept missing, real voltage kept
    filled, imputed, longest = fill_short_gaps(hourly)
    assert filled.loc[index[2], "voltage"] == 232.0
    assert filled[TARGET].iloc[4:9].isna().all()
    assert filled["voltage"].iloc[4:9].tolist() == [234.0, 235.0, 236.0, 237.0, 238.0]
    assert (imputed, longest) == (0, 5)

    long_voltage = hourly.assign(**{TARGET: np.arange(10.0)})
    long_voltage.loc[index[3:8], "voltage"] = np.nan
    assert fill_short_gaps(long_voltage)[0]["voltage"].iloc[3:8].isna().all()


def test_as_of_accepts_utc_z_and_rejects_offsets(http, hourly, model_dir):
    as_of = hourly.index[-30]
    utc = run(ReadingsClient(http=http), model_dir, as_of=f"{as_of.isoformat()}Z")
    assert utc.anchor == as_of
    with pytest.raises(ValueError, match="time-zone offset"):
        run(ReadingsClient(http=http), model_dir, as_of=f"{as_of.isoformat()}+02:00")


def test_live_run_with_only_an_unfinished_hour_is_explained(hourly, model_dir):
    minutes = hourly.resample("1min").ffill()
    minutes = minutes[(minutes.index >= hourly.index[-2]) & (minutes.index < hourly.index[-2] + pd.Timedelta("30min"))]
    http = api_client(create_app(minutes))
    with pytest.raises(ValueError, match="unfinished hour"):
        run(ReadingsClient(http=http), model_dir)


def test_report_counts_only_history_records(minute_http, hourly):
    as_of = hourly.index[-30]
    result = run(ReadingsClient(http=minute_http), ROOT / "models", as_of=as_of, backtest_hours=12)
    history_minutes = hourly.resample("1min").ffill()
    history_minutes.iloc[::97] = np.nan
    expected = int(((history_minutes.index >= result.history.index[0]) & (history_minutes.index < as_of + pd.Timedelta("1h"))).sum())
    assert result.report.raw_records == expected
