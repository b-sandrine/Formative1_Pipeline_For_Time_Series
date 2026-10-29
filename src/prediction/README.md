# Task 4: Prediction / forecast script

`scripts/predict.py` runs the full pipeline end to end:

1. **Loads the trained model** from `models/` (`model.joblib` / `model.keras` + `model_metadata.json` from Task 1).
2. **Fetches** the latest reading, then the preceding history, from the Task 3 API (`--source sql` or `--source mongo`).
3. **Preprocesses** it the same way as Task 1: flattens MySQL rows or MongoDB documents, averages the minute readings into hourly
   means, time-interpolates missing hours, and rebuilds the model's lag, rolling-mean and calendar features.
4. **Forecasts** `global_active_power` for the next hour, or up to N hours by feeding each prediction back in as a lag.

Results are printed, saved as JSON, and plotted to `outputs/predictions/`.

## Run it

```bash
pip install -r requirements.txt

# 1. Start the API (Task 3), or the mock while it isn't ready:
python -m src.prediction.mock_api --data dataset/household_power_consumption.txt

# 2. Forecast
python scripts/predict.py                                   # next hour, MySQL API
python scripts/predict.py --source mongo --horizon 24       # next 24 hours, MongoDB API
python scripts/predict.py --as-of 2010-11-20T17:00 --horizon 12   # backtest: compare with real readings
```

| Option | Default | |
|---|---|---|
| `--api-url` | `$API_URL` or `http://localhost:8000` | Task 3 API base URL |
| `--source` | `sql` | `sql` or `mongo` |
| `--model-dir` | `models/` | folder with the model and `model_metadata.json` |
| `--horizon` | `1` | hours to forecast |
| `--as-of` | none | forecast from a past hour and report error against actual readings |
| `--lookback-hours` | model's need + 24 | history to fetch |
| `--no-plot` | off | skip the PNG |

Example backtest output (real data, 12 hours from 2010-11-20 17:00):

```
[1/4] Model     sklearn model, 12 features, target global_active_power
[2/4] Fetched   11580 records up to 2010-11-20 17:00:00 (mongo)
[3/4] Cleaned   193 hourly rows, 0 missing hours interpolated (longest gap 0h)
[4/4] Forecast  12 hour(s) ahead

  hour                 predicted kW   actual kW    error
  2010-11-20 18:00            2.041       5.627   -3.586
  2010-11-20 19:00            2.380       3.260   -0.879
  ...
```

## Code layout

| File | Responsibility |
|---|---|
| `src/prediction/api_client.py` | HTTP calls to `/{sql,mongo}/readings/latest` and the date-range route |
| `src/prediction/preprocessing.py` | record flattening, hourly resampling and imputation, `build_features` |
| `src/prediction/model_loader.py` | loads scikit-learn or Keras models plus optional scalers from the metadata |
| `src/prediction/forecast.py` | one-step and recursive multi-step forecasting |
| `src/prediction/pipeline.py` | wires the steps together, plus backtest actuals |
| `src/prediction/mock_api.py` | development-only stand-in for the Task 3 API |
| `scripts/predict.py` | command line, console table, JSON and plot output |
| `tests/test_prediction.py` | unit and end-to-end tests (`pytest tests`) |

## Design choices

- **Model-agnostic.** Features are rebuilt from the names in `model_metadata.json`, so Task 1 can change
  the feature set or the model without any change here. The naming scheme is in
  [`docs/INTEGRATION_CONTRACT.md`](../docs/INTEGRATION_CONTRACT.md).
- **No train/serve skew.** Task 1 can import `src.prediction.preprocessing.build_features` to train on the same
  feature code used at prediction time.
- **No look-ahead.** Every feature for hour t uses data up to t-1 only.
- **Safe multi-step forecasts.** The script refuses horizons that would need future values of measurements
  other than the target (e.g. `voltage_lag_1` allows only 1 hour ahead).
- **Incomplete hours are dropped.** If the API serves minute data and the latest hour isn't finished,
  that partial hour is not treated as a real reading.
- **Predictions are clipped at 0 kW**, since power use can't be negative.
