# Household Power Consumption: Time-Series Pipeline

An end-to-end pipeline that forecasts a household's electricity use. It covers exploratory analysis and model
training, storage in MySQL and MongoDB, a CRUD API over both databases, and a script that pulls live
readings from the API and predicts the next hour.

## Problem and dataset

**Goal:** forecast the household's `global_active_power` (kW, hourly mean) for the next hour.

**Dataset:** [Individual Household Electric Power Consumption](https://www.kaggle.com/datasets/uciml/electric-power-consumption-data-set)
(UCI, via Kaggle). It has one reading per minute from a house near Paris, from 16 Dec 2006 to 26 Nov 2010:
2,075,259 rows, about 1.25% missing.

| Column | Meaning |
|---|---|
| `global_active_power` | total power drawn (kW), **the target** |
| `global_reactive_power` | reactive power (kW) |
| `voltage` | voltage (V) |
| `global_intensity` | current (A) |
| `sub_metering_1/2/3` | energy (Wh) in the kitchen, the laundry room, and for the water heater and AC |

**Why this dataset:**
- It has a clean timestamp and a meaningful, continuous target.
- It has several related variables measured at the same time.
- Household usage has strong daily and weekly cycles, so lag features and moving averages carry real signal.
- Short-term load forecasting is a practical problem: utilities use it to plan supply, and households use it
  to manage cost.

## Repository layout

```
├── Task1_Time_Series_Analysis.ipynb   Task 1: EDA, 6 analytical questions, modeling
├── train_model.ipynb                  Task 1: model training walkthrough
├── scripts/
│   ├── train_model.py                 Task 1: tune and train the model, save it to models/
│   ├── import_mysql.py                Task 2: load the dataset into MySQL
│   ├── import_mongodb.py              Task 2: load the dataset into MongoDB
│   ├── run_api.py                     Task 3: start the API
│   └── predict.py                     Task 4: fetch → preprocess → load model → forecast
├── models/                            trained model, metadata, experiment table
├── sql/                               Task 2: schema, ERD, queries and results
├── mongodb/                           Task 2: collection design, sample documents, queries and results
├── src/
│   ├── database/                      Task 2: connections, dataset reader, importers
│   ├── api/                           Task 3: Flask app, SQL/Mongo stores, validation
│   └── prediction/                    Task 4: API client, preprocessing, forecasting
├── docs/INTEGRATION_CONTRACT.md       how the four tasks connect
├── outputs/predictions/               forecasts written by predict.py (JSON + PNG)
└── tests/                             tests for every task
```

## Setup

Requires Python 3.10+, MySQL 8 and MongoDB.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then fill in your MySQL / MongoDB settings
```

Download `household_power_consumption.txt` from the Kaggle link above and put it in `dataset/`.
It's about 130 MB and isn't committed.

## Reproduce the results

Run these from the repository root, in order:

```bash
# Task 1: train the model (writes models/model.joblib, model_metadata.json, model_experiments.csv)
python scripts/train_model.py

# Task 2: create the databases and load the data
mysql -u <user> -p < sql/schema.sql
python scripts/import_mysql.py
python scripts/import_mongodb.py      # also creates the MongoDB indexes

# Task 3: start the API on http://127.0.0.1:5000
python scripts/run_api.py

# Task 4: in a second terminal, forecast the next hour
python scripts/predict.py                    # from MySQL
python scripts/predict.py --source mongo     # from MongoDB
python scripts/predict.py --as-of 2010-11-20T17:00 --backtest-hours 24   # compare with real readings
```

Run the tests with `pytest tests`. The live MySQL/MongoDB tests are skipped if those databases aren't running.

## Each task

### Task 1: Exploratory analysis and model
Notebook: `Task1_Time_Series_Analysis.ipynb`. It covers the time range and granularity, how missing values
were handled, and distributions. It then answers six analytical questions, each with a chart: the trend,
the daily peak, correlations, lag effects (1 h, 24 h, 1 week), moving averages, and weekday versus weekend.

The model is a random forest on hourly data. Features: power 1 hour and 24 hours ago, voltage and intensity
1 hour ago, and the 24-hour rolling mean. Hyperparameters were tuned on a chronological validation split:

| Experiment | Trees | Max depth | Validation RMSE | Validation MAE |
|---|---|---|---|---|
| **RF-50-depth8** (selected) | 50 | 8 | **0.566** | **0.395** |
| RF-100-depth10 | 100 | 10 | 0.568 | 0.397 |
| RF-150-depth14 | 150 | 14 | 0.576 | 0.404 |

On the held-out test period (last 20%), the selected model scores **RMSE 0.524 kW, MAE 0.374 kW**.

### Task 2: Databases
- **MySQL** ([sql/](sql/README.md)): four tables, `dataset_sources`, `energy_measurements`, `forecast_runs`
  and `forecast_predictions`. The ERD is in `sql/erd.mmd`; queries and their results are in `sql/query_results.md`.
- **MongoDB** ([mongodb/](mongodb/collection_design.md)): the same data as documents. Each reading nests its
  measurements in a subdocument. Sample documents, queries and results are in the same folder.

### Task 3: API
A Flask service ([api/README.md](api/README.md)) with full CRUD under both `/sql` and `/mongo`, plus
**latest reading** (`GET /{db}/readings/latest`) and **date range**
(`GET /{db}/readings?start_date=...&end_date=...`). Both databases return the same JSON shape.

### Task 4: Forecast script
`scripts/predict.py` ([src/prediction/README.md](src/prediction/README.md)) runs four steps:
1. Loads the Task 1 model.
2. Fetches the latest readings from the Task 3 API.
3. Rebuilds the hourly features exactly as in training.
4. Predicts the next hour.

The result is printed, saved as JSON, and plotted. With `--as-of` and `--backtest-hours` it replays past
hours and reports the error against real readings.

## Team

| Member | GitHub | Task | Main components |
|---|---|---|---|
| Premier | [primitivecodes](https://github.com/primitivecodes) | Task 1: EDA and modeling | analysis notebook, feature engineering, model tuning and training |
| Sandrine | [b-sandrine](https://github.com/b-sandrine) | Task 2: databases | MySQL schema and ERD, MongoDB design, importers, queries |
| Happy | [acele-happy](https://github.com/acele-happy) | Task 3: API | Flask CRUD and time-series routes for MySQL and MongoDB |
| Aimé | [igaimerca](https://github.com/igaimerca) | Task 4: forecasting | API client, preprocessing pipeline, forecast script, integration contract |
