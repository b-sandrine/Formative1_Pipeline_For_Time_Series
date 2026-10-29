"""Development stand-in for the Task 3 API, so the forecast script can be run before the real one is ready.

It serves only the read routes the script uses (docs/INTEGRATION_CONTRACT.md), with records
shaped like the Task 2 databases: flat MySQL rows under /sql, nested MongoDB documents under /mongo.

    python -m src.prediction.mock_api --data dataset/household_power_consumption.txt
    python -m src.prediction.mock_api --synthetic
"""

from __future__ import annotations

import argparse
from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import FastAPI, Query

from src.prediction import MEASUREMENTS


def create_app(readings: pd.DataFrame) -> FastAPI:
    """Serves `readings` (DatetimeIndex, MEASUREMENTS columns) at any frequency."""
    readings = readings.sort_index()
    app = FastAPI(title="Mock household power API (development only)")

    def select(start: datetime | None, end: datetime | None, limit: int) -> pd.DataFrame:
        rows = readings.loc[start:end] if start or end else readings
        return rows.iloc[:limit]

    @app.get("/sql/readings/latest")
    def sql_latest():
        return sql_rows(readings.iloc[[-1]])[0]

    @app.get("/sql/readings")
    def sql_range(start_date: datetime | None = None, end_date: datetime | None = None, limit: int = Query(1000, ge=1)):
        return sql_rows(select(start_date, end_date, limit))

    @app.get("/mongo/readings/latest")
    def mongo_latest():
        return mongo_docs(readings.iloc[[-1]])[0]

    @app.get("/mongo/readings")
    def mongo_range(start_date: datetime | None = None, end_date: datetime | None = None, limit: int = Query(1000, ge=1)):
        docs = mongo_docs(select(start_date, end_date, limit))
        return {"count": len(docs), "data": docs}

    return app


def sql_rows(frame: pd.DataFrame) -> list[dict]:
    """Rows shaped like the Task 2 MySQL table energy_measurements."""
    return [
        {"measurement_id": int(ts.timestamp() // 60), "source_id": 1, "measured_at": ts.isoformat(), **values}
        for ts, values in zip(frame.index, _values(frame))
    ]


def mongo_docs(frame: pd.DataFrame) -> list[dict]:
    """Documents shaped like the Task 2 MongoDB collection energy_readings."""
    return [
        {"_id": f"{ts:%Y%m%d%H%M}", "source_id": "1", "timestamp": ts.isoformat() + "Z", "measurements": values}
        for ts, values in zip(frame.index, _values(frame))
    ]


def _values(frame: pd.DataFrame) -> list[dict]:
    rounded = frame[MEASUREMENTS].round(4).astype(object)
    return rounded.where(rounded.notna(), None).to_dict("records")


def load_raw_dataset(path: str) -> pd.DataFrame:
    """Reads the Kaggle minute-level file, keeping missing ("?") readings as NaN like Task 2 does."""
    raw = pd.read_csv(path, sep=";", na_values="?", low_memory=False)
    raw.columns = [c.lower() for c in raw.columns]
    raw.index = pd.to_datetime(raw.pop("date") + " " + raw.pop("time"), format="%d/%m/%Y %H:%M:%S")
    return raw[MEASUREMENTS].astype(float)


def synthetic_hourly(hours: int = 24 * 30, start: str = "2010-01-01", seed: int = 0) -> pd.DataFrame:
    """A month of hourly data with daily and weekly cycles, for tests and quick demos."""
    rng = np.random.default_rng(seed)
    index = pd.date_range(start, periods=hours, freq="1h")
    daily = 0.8 * np.sin(2 * np.pi * (index.hour - 7) / 24) + 0.4 * np.sin(4 * np.pi * index.hour / 24)
    weekly = 0.3 * (index.day_of_week >= 5)
    power = np.clip(1.2 + daily + weekly + rng.normal(0, 0.08, hours), 0.1, None)
    voltage = 240 + rng.normal(0, 1.5, hours)
    return pd.DataFrame(
        {
            "global_active_power": power,
            "global_reactive_power": 0.12 + rng.normal(0, 0.02, hours).clip(-0.1),
            "voltage": voltage,
            "global_intensity": power * 1000 / voltage,
            "sub_metering_1": rng.choice([0, 0, 0, 20], hours).astype(float),
            "sub_metering_2": rng.choice([0, 1, 2], hours).astype(float),
            "sub_metering_3": (power * 6).round(),
        },
        index=index,
    )


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--data", help="path to household_power_consumption.txt")
    group.add_argument("--synthetic", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    readings = synthetic_hourly() if args.synthetic else load_raw_dataset(args.data)
    print(f"Serving {len(readings)} readings from {readings.index[0]} to {readings.index[-1]}")
    uvicorn.run(create_app(readings), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
