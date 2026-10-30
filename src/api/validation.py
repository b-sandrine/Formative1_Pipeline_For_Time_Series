"""Check request bodies and date-range query parameters."""
import math
from datetime import datetime, timedelta

from src.api.errors import ApiError
from src.database.dataset_reader import MEASUREMENT_COLUMNS

# Fields a client may send. measurement_id is assigned by the database.
WRITABLE_FIELDS = ("measured_at", "source_id", *MEASUREMENT_COLUMNS)

# Query values and JSON measured_at. Date-only is handled separately so the
# end date can mean "the whole day".
_DATETIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
)
_DATE_FORMAT = "%Y-%m-%d"


def parse_measurement(name: str, value):
    """A measurement is a finite number or null. Booleans are rejected."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ApiError(f"{name} must be a number or null")
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            raise ApiError(f"{name} must be a number or null") from None
    else:
        raise ApiError(f"{name} must be a number or null")
    if not math.isfinite(number):
        raise ApiError(f"{name} must be a finite number")
    return number


def _clock_text(value, field_name: str) -> str:
    """Strip a trailing Z and fractional seconds. Reject numeric offsets.

    The file has no time zone. Task 2 stores that clock time as-is, and a
    trailing Z does not mean the household was in UTC. Offsets such as
    +02:00 are rejected so a value is never shifted by accident.
    """
    if not isinstance(value, str) or not value.strip():
        raise ApiError(f"{field_name} must be a date-time string such as 2006-12-16T17:24:00")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    # Check the offset before dropping fractional seconds, otherwise
    # "2006-12-16T17:24:00.000+02:00" would lose the "+02:00" at the dot.
    if "+" in text or text.count("-") > 2:
        raise ApiError(
            f"{field_name} must be local time without a numeric offset, "
            "for example 2006-12-16T17:24:00"
        )
    if "." in text:
        text = text.split(".", 1)[0]
    return text


def parse_timestamp(value, field_name: str = "measured_at") -> datetime:
    """Parse a local clock time. A trailing Z is ignored, not converted."""
    text = _clock_text(value, field_name)
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.strptime(text, _DATE_FORMAT)
    except ValueError:
        raise ApiError(
            f"{field_name} must look like 2006-12-16T17:24:00 or 2006-12-16"
        ) from None


def parse_reading_body(data, *, partial: bool) -> dict:
    """Return a cleaned body. ``partial`` is for PUT, where every field is optional."""
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object")
    unknown = sorted(set(data) - set(WRITABLE_FIELDS))
    if unknown:
        raise ApiError("Unknown fields: " + ", ".join(unknown))
    if not partial and "measured_at" not in data:
        raise ApiError("measured_at is required")
    if partial and not data:
        raise ApiError("Provide at least one field to update")

    cleaned = {}
    if "measured_at" in data:
        cleaned["measured_at"] = parse_timestamp(data["measured_at"])
    if "source_id" in data:
        cleaned["source_id"] = data["source_id"]
    for column in MEASUREMENT_COLUMNS:
        if column in data:
            cleaned[column] = parse_measurement(column, data[column])
    return cleaned


def parse_limit(raw, *, default: int, maximum: int = 20000) -> int:
    if raw is None or str(raw).strip() == "":
        return default
    try:
        limit = int(str(raw).strip())
    except ValueError:
        raise ApiError("limit must be a whole number") from None
    if limit < 1 or limit > maximum:
        raise ApiError(f"limit must be between 1 and {maximum}")
    return limit


def _parse_bound(value: str, field_name: str):
    """Return ``(datetime, date_only)``."""
    text = _clock_text(value, field_name)
    try:
        return datetime.strptime(text, _DATE_FORMAT), True
    except ValueError:
        pass
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt), False
        except ValueError:
            continue
    raise ApiError(
        f"{field_name} must look like 2007-01-01 or 2007-01-01T00:10:00"
    )


def range_bounds(start_text: str, end_text: str):
    """Return a half-open window ``[start, end)``.

    A date with no time covers that whole calendar day, so
    ``start_date=2007-01-01&end_date=2007-01-01`` includes every minute of
    1 January. A full date-time is used as written, and the end is exclusive,
    matching ``sql/queries.sql`` (``measured_at >= start AND measured_at < end``).
    """
    start, _start_is_date = _parse_bound(start_text, "start_date")
    end, end_is_date = _parse_bound(end_text, "end_date")
    if end_is_date:
        end = end + timedelta(days=1)
    if start >= end:
        raise ApiError("start_date must be earlier than end_date")
    return start, end
