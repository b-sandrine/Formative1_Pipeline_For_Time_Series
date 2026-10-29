"""Tests that need no database: configuration and dataset parsing."""
from datetime import datetime

import pytest

from src.database import config
from src.database.dataset_reader import (
    EXPECTED_HEADER, MEASUREMENT_COLUMNS, parse_line, read_dataset,
)

HEADER = ";".join(EXPECTED_HEADER)
VALID_LINE = "16/12/2006;17:24:00;4.216;0.418;234.840;18.400;0.000;1.000;17.000"
VALID_LINE_2 = "16/12/2006;17:25:00;5.360;0.436;233.630;23.000;0.000;1.000;16.000"
MISSING_LINE = "21/12/2006;11:23:00;?;?;?;?;?;?;"  # same shape as the real file


def write_dataset(path, data_lines):
    """Write a small dataset file with Windows line endings, like the real one."""
    path.write_bytes((HEADER + "\r\n" + "".join(line + "\r\n" for line in data_lines)).encode())
    return path


# ---------------------------------------------------------------- configuration
ENV_NAMES = ["MYSQL_HOST", "MYSQL_PORT", "MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD",
             "MONGODB_URI", "MONGODB_DATABASE", "DATASET_PATH"]


@pytest.fixture
def clean_env(monkeypatch):
    """Remove the settings so a local .env file cannot change the result."""
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_mysql_config_defaults(clean_env):
    assert config.get_mysql_config() == {
        "host": "localhost", "port": 3306, "database": "energy_consumption",
        "user": "root", "password": "",
    }


def test_mysql_config_reads_environment(clean_env):
    clean_env.setenv("MYSQL_HOST", "db.example")
    clean_env.setenv("MYSQL_PORT", "3307")
    clean_env.setenv("MYSQL_DATABASE", "other")
    clean_env.setenv("MYSQL_USER", "someone")
    clean_env.setenv("MYSQL_PASSWORD", "pw")
    assert config.get_mysql_config() == {
        "host": "db.example", "port": 3307, "database": "other",
        "user": "someone", "password": "pw",
    }


def test_mongo_config_defaults_and_override(clean_env):
    assert config.get_mongo_config() == {
        "uri": "mongodb://localhost:27017/", "database": "energy_consumption"}
    clean_env.setenv("MONGODB_URI", "mongodb://other:1234/")
    clean_env.setenv("MONGODB_DATABASE", "mine")
    assert config.get_mongo_config() == {"uri": "mongodb://other:1234/", "database": "mine"}


def test_dataset_path_default_and_override(clean_env):
    assert config.get_dataset_path() == config.DEFAULT_DATASET_PATH
    clean_env.setenv("DATASET_PATH", "/tmp/somewhere.txt")
    assert str(config.get_dataset_path()) == "/tmp/somewhere.txt"


# ---------------------------------------------------------------------- parsing
def test_parse_valid_line():
    record, error = parse_line(VALID_LINE)
    assert error is None
    assert record["measured_at"] == datetime(2006, 12, 16, 17, 24, 0)  # DD/MM/YYYY
    assert record["global_active_power"] == 4.216
    assert record["voltage"] == 234.84
    assert record["sub_metering_3"] == 17.0
    assert set(record) == {"measured_at", *MEASUREMENT_COLUMNS}


def test_parse_line_with_windows_line_ending():
    record, error = parse_line(VALID_LINE + "\r\n")
    assert error is None
    assert record["sub_metering_3"] == 17.0


def test_missing_values_become_none_not_zero():
    record, error = parse_line(MISSING_LINE)
    assert error is None
    assert record["measured_at"] == datetime(2006, 12, 21, 11, 23, 0)
    for column in MEASUREMENT_COLUMNS:
        assert record[column] is None  # includes the empty last field


def test_only_the_missing_field_is_none():
    record, error = parse_line("16/12/2006;17:24:00;?;0.418;234.840;18.400;0.000;1.000;17.000")
    assert error is None
    assert record["global_active_power"] is None
    assert record["global_reactive_power"] == 0.418


def test_real_zero_is_kept_as_zero():
    record, _ = parse_line(VALID_LINE)
    assert record["sub_metering_1"] == 0.0 and record["sub_metering_1"] is not None


@pytest.mark.parametrize("line", [
    "32/13/2006;11:24:00;1;1;1;1;1;1;1",     # impossible date
    "16/12/2006;25:00:00;1;1;1;1;1;1;1",     # impossible time
    "2006-12-16;17:24:00;1;1;1;1;1;1;1",     # wrong date format
    "16/12/2006;17:26:00;abc;1;1;1;1;1;1",   # not a number
    "16/12/2006;17:26:00;nan;1;1;1;1;1;1",   # not finite
    "16/12/2006;17:26:00;inf;1;1;1;1;1;1",   # not finite
    "16/12/2006;17:27:00;1.0;0.1",           # too few fields
    VALID_LINE + ";9",                       # too many fields
    "",                                      # empty line
])
def test_invalid_lines_are_rejected_with_a_reason(line):
    record, error = parse_line(line)
    assert record is None
    assert error  # a non-empty reason


# ---------------------------------------------------------------- reading files
def test_read_dataset_yields_records_and_errors(tmp_path):
    path = write_dataset(tmp_path / "data.txt", [VALID_LINE, MISSING_LINE, "bad;line", VALID_LINE_2])
    results = list(read_dataset(path))
    assert [line_number for line_number, _, _ in results] == [1, 2, 3, 4]
    assert [error is None for _, _, error in results] == [True, True, False, True]
    assert results[1][1]["voltage"] is None


def test_read_dataset_max_rows(tmp_path):
    path = write_dataset(tmp_path / "data.txt", [VALID_LINE, VALID_LINE_2, MISSING_LINE])
    assert len(list(read_dataset(path, max_rows=2))) == 2


def test_read_dataset_rejects_unexpected_header(tmp_path):
    path = tmp_path / "wrong.txt"
    path.write_text("a;b;c\n1;2;3\n")
    with pytest.raises(ValueError):
        list(read_dataset(path))


def test_real_dataset_header_matches_if_present():
    path = config.get_dataset_path()
    if not path.exists():
        pytest.skip("dataset file not available")
    first = next(read_dataset(path, max_rows=1))
    assert first[2] is None  # the first real line parses without error
