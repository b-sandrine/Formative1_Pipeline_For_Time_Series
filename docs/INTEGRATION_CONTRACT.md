# Integration contract

What each task hands to the next, so the four parts connect without last-minute changes.
If you need to change something here, post in the group chat first, because another task depends on it.

```
Task 1 (EDA + model) ──► models/model.joblib + models/model_metadata.json ──┐
Task 2 (MySQL + MongoDB) ──► energy_measurements / energy_readings (1 per minute)│
Task 3 (API) ──► /sql/... and /mongo/... routes over Task 2                   │
                                                                              ▼
Task 4 (scripts/predict.py) ── fetches from Task 3, preprocesses, loads Task 1 model, forecasts
```

## 1. The problem

- **Target:** `global_active_power` (kW), the household's **hourly mean**.
- **Task:** forecast the next hour (and up to 24 hours ahead, recursively).
- **Granularity:** the data is one reading per minute (about 2.07M rows, 2006-12-16 17:24 to
  2010-11-26 21:02), stored that way in both databases. The model works on **hourly means**
  (34,589 hours). Task 4 averages the minutes into hours itself, after fetching them.

## 2. Column names (all tasks)

Lowercase snake_case everywhere: in the DB, the API JSON and the notebook (as in Task 2's schema).

| Column | Unit | Raw dataset name |
|---|---|---|
| `measured_at` (MySQL) / `timestamp` (MongoDB) | ISO 8601, local time | `Date` + `Time` |
| `global_active_power` | kW | `Global_active_power` |
| `global_reactive_power` | kW | `Global_reactive_power` |
| `voltage` | V | `Voltage` |
| `global_intensity` | A | `Global_intensity` |
| `sub_metering_1` | Wh (kitchen) | `Sub_metering_1` |
| `sub_metering_2` | Wh (laundry) | `Sub_metering_2` |
| `sub_metering_3` | Wh (water heater + AC) | `Sub_metering_3` |

## 3. Task 1 → Task 4: the saved model

Save to the `models/` folder:

- `model.joblib`, a fitted scikit-learn model or `Pipeline` (`joblib.dump(model, "models/model.joblib")`), **or**
  `model.keras` for an LSTM.
- `model_metadata.json`:

```json
{
  "model_type": "sklearn",
  "model_name": "Random Forest (tuned, experiment 3)",
  "model_file": "model.joblib",
  "target": "global_active_power",
  "frequency": "1h",
  "features": ["lag_1", "lag_2", "lag_3", "lag_24", "lag_168",
               "rolling_mean_24", "rolling_std_24", "rolling_mean_168",
               "hour", "dayofweek", "month", "is_weekend"]
}
```

`features` (or `feature_names`) must be in the **same order as the training columns**. Task 4 rebuilds
them from the API data by name, using this scheme. Task 1's own style (`power_lag_1h`,
`intensity_lag_1h`, `rolling_mean_24h`) is accepted too:

| Name | Meaning at hour t |
|---|---|
| `lag_k` | target at t-k (e.g. `lag_24` = same hour yesterday, `lag_168` = same hour last week) |
| `rolling_mean_w`, `rolling_std_w`, `rolling_min_w`, `rolling_max_w` | stat of target over hours t-w to t-1 |
| `<column>_lag_k` | another column at t-k, e.g. `voltage_lag_1`, `sub_metering_3_lag_24` |
| `<column>_rolling_mean_w` | rolling mean of another column over t-w to t-1 |
| `hour`, `dayofweek`, `month`, `dayofyear`, `is_weekend` | calendar of hour t |
| `hour_sin`, `hour_cos`, `dow_sin`, `dow_cos`, `month_sin`, `month_cos` | cyclical calendar encodings |

**Easiest way to guarantee a match:** build the training features with the same function Task 4 uses:

```python
from src.prediction.preprocessing import build_features
X = build_features(hourly_df, FEATURES)          # hourly_df: hourly DatetimeIndex, columns from section 2
data = X.assign(y=hourly_df["global_active_power"]).dropna()
```

Two rules that keep this a real forecast:

1. **No same-hour inputs.** Don't use `global_intensity` or `voltage` at hour t to predict power
   at hour t. Intensity is roughly power ÷ voltage, so that leaks the answer. Use their lags instead.
2. Features made only from the target's own past plus calendar features allow 24-hour forecasts.
   Lags of other columns cap the horizon (with `voltage_lag_1`, only 1 hour ahead).

**LSTM instead?** Set `"model_type": "keras"`, `"model_file": "model.keras"`, `"sequence_length": 24`
(hours the network reads), and if you scaled data, `"feature_scaler_file": "feature_scaler.joblib"` and
`"target_scaler_file": "target_scaler.joblib"`. The input is the last `sequence_length` rows of
`features`, shape `(1, sequence_length, n_features)`. In this case `features` may include raw columns
such as `global_active_power`.

## 4. Task 2: storage (done)

As built by Task 2 (see `sql/schema.sql` and `mongodb/collection_design.md`):

- MySQL `energy_measurements`: one row per minute, `measured_at` + the seven columns, `NULL` when missing.
- MongoDB `energy_readings`: one document per minute, `timestamp` (local time stored as if UTC, so it
  ends in `Z`) and the seven values nested under `measurements`, `null` when missing.

Task 4 handles both shapes as they are. It averages minutes into hours, ignoring missing minutes, and
interpolates hours that have no readings at all.

## 5. Task 3 → Task 4: API routes

Base URL `http://localhost:5000` (Task 3's default). The same routes exist under `/sql` and `/mongo`.

| Method | Route | Purpose |
|---|---|---|
| GET | `/{db}/readings/latest` | most recent reading |
| GET | `/{db}/readings?start_date=...&end_date=...&limit=...` | readings with `start_date <= time <= end_date`, **ascending** |
| GET | `/{db}/readings/{id}` | one reading |
| POST | `/{db}/readings` | create |
| PUT | `/{db}/readings/{id}` | update |
| DELETE | `/{db}/readings/{id}` | delete |

- Dates are ISO 8601 (`2010-11-20T17:00:00`).
- The range route caps `limit` at 20,000. Task 4 asks for pages of 20,000 and fetches the next
  page from the last timestamp when a page comes back full.
- Return the records as the databases store them. Either of these works:

```json
{"measurement_id": 2, "source_id": 1, "measured_at": "2006-12-16T17:25:00",
 "global_active_power": 5.36, "global_reactive_power": 0.436, "voltage": 233.63, "global_intensity": 23.0,
 "sub_metering_1": 0.0, "sub_metering_2": 1.0, "sub_metering_3": 16.0}
```

```json
{"_id": "...", "source_id": "...", "timestamp": "2006-12-16T17:25:00Z",
 "measurements": {"global_active_power": 5.36, "global_reactive_power": 0.436, "voltage": 233.63,
                  "global_intensity": 23.0, "sub_metering_1": 0.0, "sub_metering_2": 1.0, "sub_metering_3": 16.0}}
```

A bare list or a list wrapped as `{"data": [...]}` are both fine, and so are Mongo `$date` objects.
Keep the field names from section 2. `Decimal` values serialized as strings (`"5.360"`) are fine too.

Without MySQL or MongoDB, `python -m src.prediction.mock_api --data dataset/household_power_consumption.txt`
runs the real Task 3 Flask app on in-memory data, so Task 4 can still be run end to end.
