# Task 4: Prediction / forecast script

`scripts/predict.py` runs the whole pipeline end to end:

1. **Loads the trained model** from `models/`: `model.joblib` and `model_metadata.json` from Task 1.
2. **Fetches** the latest reading, then the history before it, from the Task 3 API (`--source sql` or `--source mongo`).
3. **Preprocesses** the readings the same way as Task 1. It averages the minute readings into hourly means,
   fills gaps of up to 3 hours by time interpolation, and rebuilds the model's lag and rolling-mean features.
4. **Forecasts** `global_active_power` for the next hour.

Results are printed, saved as JSON, and plotted to `outputs/predictions/`.

## Run it

```bash
pip install -r requirements.txt

# 1. Start the Task 3 API (needs the databases loaded, see the main README)
python scripts/run_api.py

#    ...or, without MySQL/MongoDB, the same API on in-memory data:
python -m src.prediction.mock_api --data dataset/household_power_consumption.txt

# 2. Forecast
python scripts/predict.py                        # next hour, from MySQL
python scripts/predict.py --source mongo         # next hour, from MongoDB
python scripts/predict.py --as-of 2010-11-20T17:00 --backtest-hours 24   # 24 one-hour forecasts vs real readings
```

| Option | Default | What it does |
|---|---|---|
| `--api-url` | `$API_URL` or `http://localhost:5000` | Task 3 API base URL |
| `--source` | `sql` | `sql` or `mongo` |
| `--model-dir` | `models/` | folder with the model and `model_metadata.json` |
| `--as-of` | none | forecast from a past hour and compare with the real readings |
| `--backtest-hours` | none | with `--as-of`: forecast each of the next N hours one step ahead, report the mean error |
| `--horizon` | `1` | hours ahead; more than 1 only works if the model doesn't use other measurements' lags |
| `--lookback-hours` | model's need + 24 | history to fetch |
| `--no-plot` | off | skip the PNG |

Example: a walk-forward backtest on real data with the Task 1 model, through the Task 3 API on MongoDB:

```
[1/4] Model     sklearn model, 5 features, target global_active_power
[2/4] Fetched   2940 records up to 2010-11-20 17:00:00 (mongo)
[3/4] Cleaned   49 hourly rows, 0 missing hours interpolated (longest gap 0h)
[4/4] Forecast  24 hours, each one hour ahead (walk-forward backtest)

  hour                 predicted kW   actual kW    error
  2010-11-20 18:00            1.622       5.627   -4.005
  2010-11-20 19:00            3.425       3.260   +0.165
  2010-11-20 20:00            2.864       2.117   +0.747
  ...
  MAE over the window: 0.518 kW
```

## Code layout

| File | Responsibility |
|---|---|
| `src/prediction/api_client.py` | calls `/{sql,mongo}/readings/latest` and the date-range route, paging past the API's 20,000-row limit |
| `src/prediction/preprocessing.py` | record flattening, hourly resampling and gap filling, `build_features` |
| `src/prediction/model_loader.py` | loads the model and its metadata (scikit-learn, or Keras for an LSTM) |
| `src/prediction/forecast.py` | one-step and multi-step forecasting |
| `src/prediction/pipeline.py` | wires the steps together; backtests and actuals |
| `src/prediction/mock_api.py` | the real Task 3 Flask app on in-memory data, for running without databases |
| `scripts/predict.py` | command line, console table, JSON and plot output |
| `tests/test_prediction.py` | unit and end-to-end tests (`pytest tests/test_prediction.py`) |

## Design choices

- **Same features as training.** Features are rebuilt from the names in `model_metadata.json`.
  `power_lag_1h`, `voltage_lag_1h` and `rolling_mean_24h` are computed exactly as in `scripts/train_model.py`,
  and a test checks the two give identical values.
- **No look-ahead.** Every feature for hour t uses data up to t-1 only. In a backtest each step is
  preprocessed using only readings up to that hour, so gap filling never sees later values.
- **Honest horizon.** The Task 1 model uses last hour's voltage and intensity, which aren't known further
  ahead, so the script forecasts 1 hour and refuses longer horizons rather than guessing them.
  `--backtest-hours` measures accuracy over many hours instead.
- **Incomplete hours are dropped.** If the latest hour isn't finished yet, its partial average isn't
  treated as a real reading; that hour is forecast instead.
- **No invented data.** Null minutes are ignored in the hourly mean. Only gaps of up to 3 hours are
  interpolated, and only between real readings. Task 1 trains on measured hours only, so if a forecast
  needs readings from a longer outage, the script says so instead of guessing. Backtests skip those hours
  and list them, and errors are only computed against hours that were really measured.
- **Clear failures.** If the API is down, the model is missing, the arguments are invalid, or the needed
  readings aren't there, the script says exactly what's wrong.
- **Predictions are clipped at 0 kW**, since power use can't be negative.
