"""Read and clean the household power consumption file.

Shared by the MySQL and MongoDB importers so both databases receive
exactly the same values.
"""
import math
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Tuple

EXPECTED_HEADER = [
    "Date", "Time", "Global_active_power", "Global_reactive_power",
    "Voltage", "Global_intensity", "Sub_metering_1", "Sub_metering_2", "Sub_metering_3",
]
# Column names used in the databases, in the same order as the file columns 3-9.
MEASUREMENT_COLUMNS = [
    "global_active_power", "global_reactive_power", "voltage", "global_intensity",
    "sub_metering_1", "sub_metering_2", "sub_metering_3",
]
MISSING_VALUES = {"?", ""}


def parse_line(line: str) -> Tuple[Optional[dict], Optional[str]]:
    """Convert one text line into a record.

    Returns (record, None) if the line is valid, or (None, reason) if it is not.
    The record has "measured_at" (a naive datetime, local time) and the seven
    measurement columns, which are floats or None when the file says "?".
    """
    fields = line.rstrip("\r\n").split(";")
    if len(fields) != len(EXPECTED_HEADER):
        return None, f"expected {len(EXPECTED_HEADER)} fields, found {len(fields)}"

    try:
        measured_at = datetime.strptime(f"{fields[0]} {fields[1]}", "%d/%m/%Y %H:%M:%S")
    except ValueError:
        return None, f"invalid date/time '{fields[0]} {fields[1]}'"

    record = {"measured_at": measured_at}
    for column, text in zip(MEASUREMENT_COLUMNS, fields[2:]):
        text = text.strip()
        if text in MISSING_VALUES:
            record[column] = None  # missing stays missing, never 0
            continue
        try:
            number = float(text)
        except ValueError:
            return None, f"{column} is not a number: '{text}'"
        if not math.isfinite(number):
            return None, f"{column} is not a finite number: '{text}'"
        record[column] = number
    return record, None


def read_dataset(path: Path, max_rows: Optional[int] = None) -> Iterator[Tuple[int, Optional[dict], Optional[str]]]:
    """Yield (line_number, record, error) for each data line, one at a time.

    The file is streamed, so memory use stays small. Exactly one of
    record and error is None. line_number counts data lines (the header is not counted).
    """
    with open(path, encoding="utf-8", newline="") as file:
        header = file.readline().rstrip("\r\n").split(";")
        if header != EXPECTED_HEADER:
            raise ValueError(f"Unexpected header in {path}: {header}")
        for line_number, line in enumerate(file, start=1):
            if max_rows is not None and line_number > max_rows:
                break
            record, error = parse_line(line)
            yield line_number, record, error
