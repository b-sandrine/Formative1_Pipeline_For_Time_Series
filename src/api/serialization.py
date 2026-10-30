"""Turn database values into the JSON shape both APIs share.

Task 4 reads these field names. They are the same snake_case names as the
MySQL columns and the MongoDB ``measurements`` subdocument
(``global_active_power``, not ``globalactive_power``).
"""
from datetime import datetime
from decimal import Decimal

from src.database.dataset_reader import MEASUREMENT_COLUMNS


def format_timestamp(value) -> str:
    """Format a reading time as ``2006-12-16T17:24:00`` with no time zone.

    Stored times are the local clock time from the file. A trailing ``Z`` is
    not added, so the value matches the MySQL DATETIME text.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    return str(value)


def json_number(value):
    """Return a JSON number, or None when the measurement is missing.

    MySQL DECIMAL comes back as Decimal. Float keeps the stored value and
    still serializes with the standard library. Missing stays null, never 0.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def reading_json(measurement_id, source_id, measured_at, measurements: dict) -> dict:
    """One reading, with the seven measurements as top-level fields."""
    document = {
        "measurement_id": measurement_id,
        "source_id": source_id,
        "measured_at": format_timestamp(measured_at),
    }
    for column in MEASUREMENT_COLUMNS:
        document[column] = json_number(measurements.get(column))
    return document


def reading_from_sql_row(row: dict) -> dict:
    return reading_json(
        row["measurement_id"],
        row["source_id"],
        row["measured_at"],
        row,
    )


def reading_from_mongo(document: dict) -> dict:
    return reading_json(
        str(document["_id"]),
        str(document["source_id"]),
        document["timestamp"],
        document.get("measurements") or {},
    )
