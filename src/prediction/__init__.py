"""Task 4: fetch readings from the API, preprocess them, and forecast household power use."""

from src.database.dataset_reader import MEASUREMENT_COLUMNS as MEASUREMENTS

TARGET = "global_active_power"

__all__ = ["MEASUREMENTS", "TARGET"]
