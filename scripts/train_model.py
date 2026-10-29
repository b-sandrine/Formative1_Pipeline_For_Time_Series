"""Train an hourly household power model and export its inference metadata.

Run from the repository root:
    python scripts/train_model.py
    python scripts/train_model.py --path path/to/household_power_consumption.txt
"""
import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.database.config import get_dataset_path

FEATURE_COLUMNS = [
    "power_lag_1h",
    "power_lag_24h",
    "voltage_lag_1h",
    "intensity_lag_1h",
    "rolling_mean_24h",
]
TARGET = "Global_active_power"


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=None, help="dataset file (default: DATASET_PATH or dataset/household_power_consumption.txt)")
    return parser.parse_args()


def main():
    args = parse_arguments()
    dataset_path = args.path or get_dataset_path()
    if not dataset_path.is_file():
        sys.exit(f"Dataset not found: {dataset_path}")

    df = pd.read_csv(dataset_path, sep=";", na_values=["?"], low_memory=False)
    required = {"Date", "Time", TARGET, "Voltage", "Global_intensity"}
    missing = sorted(required.difference(df.columns))
    if missing:
        sys.exit(f"Dataset is missing required columns: {', '.join(missing)}")

    df["Datetime"] = pd.to_datetime(df["Date"] + " " + df["Time"], format="%d/%m/%Y %H:%M:%S")
    df = df.set_index("Datetime").drop(columns=["Date", "Time"])
    for column in df.columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    hourly = df.resample("h").mean().interpolate(method="linear")
    hourly["power_lag_1h"] = hourly[TARGET].shift(1)
    hourly["power_lag_24h"] = hourly[TARGET].shift(24)
    hourly["voltage_lag_1h"] = hourly["Voltage"].shift(1)
    hourly["intensity_lag_1h"] = hourly["Global_intensity"].shift(1)
    # Shift after rolling so the feature contains the 24 completed prior hours.
    hourly["rolling_mean_24h"] = hourly[TARGET].rolling(window=24).mean().shift(1)
    hourly = hourly.dropna(subset=FEATURE_COLUMNS + [TARGET])
    if len(hourly) < 2:
        sys.exit("Not enough complete hourly rows to train and evaluate the model.")

    X, y = hourly[FEATURE_COLUMNS], hourly[TARGET]
    train_size = int(len(hourly) * 0.8)
    if train_size < 1 or train_size >= len(hourly):
        sys.exit("Not enough hourly rows for an 80/20 chronological split.")
    X_train, X_test = X.iloc[:train_size], X.iloc[train_size:]
    y_train, y_test = y.iloc[:train_size], y.iloc[train_size:]

    model = RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42)
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)
    print(f"Test RMSE: {np.sqrt(mean_squared_error(y_test, predictions)):.4f}")
    print(f"Test MAE: {mean_absolute_error(y_test, predictions):.4f}")

    models_dir = REPO_ROOT / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, models_dir / "model.joblib")
    with (models_dir / "model_metadata.json").open("w", encoding="utf-8") as metadata_file:
        json.dump({"feature_names": FEATURE_COLUMNS, "target": TARGET}, metadata_file, indent=4)
        metadata_file.write("\n")
    print(f"Model saved to {models_dir / 'model.joblib'}")
    print(f"Metadata saved to {models_dir / 'model_metadata.json'}")


if __name__ == "__main__":
    main()
