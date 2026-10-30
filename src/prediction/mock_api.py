"""Runs the real Task 3 Flask API on in-memory data, for when MySQL or MongoDB isn't available.

The routes, validation, limits and JSON are the Task 3 API's (src/api); only the database is swapped
for the dataset file held in memory. Read routes work; writes return 405.

    python -m src.prediction.mock_api --data dataset/household_power_consumption.txt
    python -m src.prediction.mock_api --synthetic
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from src.api.app import create_app as create_api_app
from src.api.errors import ApiError
from src.api.serialization import reading_json
from src.prediction import MEASUREMENTS


class InMemoryReadingStore:
    """Read-only stand-in for SqlReadingStore / MongoReadingStore."""

    def __init__(self, readings: pd.DataFrame, string_ids: bool = False):
        self.readings = readings.sort_index()
        self.string_ids = string_ids

    def latest(self):
        return self._json(self.readings.iloc[[-1]])[0] if len(self.readings) else None

    def list_recent(self, limit: int):
        return self._json(self.readings.iloc[::-1].iloc[:limit])

    def list_range(self, start, end, limit: int):
        index = self.readings.index
        return self._json(self.readings[(index >= start) & (index < end)].iloc[:limit])

    def get(self, measurement_id):
        return None

    def create(self, fields):
        raise ApiError("The mock API is read-only", 405)

    update = delete = create

    def _json(self, frame: pd.DataFrame) -> list[dict]:
        rounded = frame[MEASUREMENTS].round(4).astype(object)
        values = rounded.where(rounded.notna(), None).to_dict("records")
        ids = (frame.index.astype("int64") // 60_000_000_000).tolist()
        return [
            reading_json(str(i) if self.string_ids else i, "1" if self.string_ids else 1, ts.to_pydatetime(), v)
            for i, ts, v in zip(ids, frame.index, values)
        ]


def create_app(readings: pd.DataFrame):
    sql, mongo = InMemoryReadingStore(readings), InMemoryReadingStore(readings, string_ids=True)
    return create_api_app(open_sql=lambda: (sql, lambda: None), open_mongo=lambda: (mongo, lambda: None))


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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--data", help="path to household_power_consumption.txt")
    group.add_argument("--synthetic", action="store_true")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    readings = synthetic_hourly() if args.synthetic else load_raw_dataset(args.data)
    print(f"Serving {len(readings)} readings from {readings.index[0]} to {readings.index[-1]}")
    create_app(readings).run(host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
