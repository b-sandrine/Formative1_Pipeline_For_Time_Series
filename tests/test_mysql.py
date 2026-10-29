"""MySQL tests.

Unit tests use fake objects. Live tests create a throwaway database with a
random name (energy_test_xxxxxxxx), never touch your real data, and drop the
throwaway database at the end. They are skipped if MySQL cannot be reached.
"""
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime

import mysql.connector
import pytest

from src.database import mysql_db
from src.database.config import PROJECT_ROOT, get_mysql_config
from src.database.dataset_reader import parse_line
from src.database.repositories import (
    INSERT_MEASUREMENT_SQL, get_or_create_source, insert_measurements,
)
from tests.test_database import MISSING_LINE, VALID_LINE, VALID_LINE_2, write_dataset


# ------------------------------------------------------------------ unit tests
class FakeCursor:
    def __init__(self, rowcount=0, fail=False):
        self.rowcount, self.fail, self.calls = rowcount, fail, []

    def executemany(self, sql, rows):
        if self.fail:
            raise RuntimeError("insert failed")
        self.calls.append((sql, rows))

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self._cursor, self.commits, self.rollbacks = cursor, 0, 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_connection_error_is_readable_and_hides_password(monkeypatch):
    monkeypatch.setenv("MYSQL_PASSWORD", "secret123")

    def failing_connect(**_):
        raise mysql.connector.Error(msg="Access denied", errno=1045)

    monkeypatch.setattr(mysql_db.mysql.connector, "connect", failing_connect)
    with pytest.raises(RuntimeError) as caught:
        mysql_db.get_connection()
    assert "Could not connect to MySQL" in str(caught.value)
    assert "secret123" not in str(caught.value)


def test_insert_sql_is_parameterized():
    assert INSERT_MEASUREMENT_SQL.count("%s") == 9  # source, time, 7 measurements
    assert "ON DUPLICATE KEY" in INSERT_MEASUREMENT_SQL


def test_insert_measurements_commits_and_returns_new_row_count():
    cursor = FakeCursor(rowcount=2)
    connection = FakeConnection(cursor)
    records = [parse_line(VALID_LINE)[0], parse_line(MISSING_LINE)[0]]
    assert insert_measurements(connection, 7, records) == 2
    rows = cursor.calls[0][1]
    assert rows[0][0] == 7 and rows[0][1] == datetime(2006, 12, 16, 17, 24)
    assert rows[1][2:] == (None,) * 7  # missing stays None, not 0
    assert (connection.commits, connection.rollbacks) == (1, 0)


def test_insert_measurements_rolls_back_on_error():
    connection = FakeConnection(FakeCursor(fail=True))
    with pytest.raises(RuntimeError):
        insert_measurements(connection, 1, [parse_line(VALID_LINE)[0]])
    assert (connection.commits, connection.rollbacks) == (0, 1)


# ----------------------------------------------------------------- live tests
def split_statements(sql_text):
    """Remove -- comments and split a SQL file into single statements."""
    without_comments = re.sub(r"--[^\n]*", "", sql_text)
    return [part.strip() for part in without_comments.split(";") if part.strip()]


@pytest.fixture
def mysql_test_db():
    """Create a throwaway database from sql/schema.sql; yield (connection, name)."""
    settings = get_mysql_config()
    name = f"energy_test_{uuid.uuid4().hex[:8]}"
    server_settings = {k: v for k, v in settings.items() if k != "database"}
    try:
        server = mysql.connector.connect(**server_settings)
    except mysql.connector.Error as error:
        pytest.skip(f"MySQL not reachable: {error.msg}")

    assert name.startswith("energy_test_")  # we only ever drop our own database
    try:
        cursor = server.cursor()
        schema = (PROJECT_ROOT / "sql" / "schema.sql").read_text()
        for statement in split_statements(schema.replace("energy_consumption", name)):
            cursor.execute(statement)
        connection = mysql.connector.connect(**{**settings, "database": name}, autocommit=False)
        yield connection, name
        connection.close()
    finally:
        server.cursor().execute(f"DROP DATABASE IF EXISTS {name}")
        server.close()


def fetch_all(connection, sql, params=()):
    cursor = connection.cursor()
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    cursor.close()
    return rows


def test_live_schema_creates_the_four_tables(mysql_test_db):
    connection, _ = mysql_test_db
    tables = {row[0] for row in fetch_all(connection, "SHOW TABLES")}
    assert tables == {"dataset_sources", "energy_measurements", "forecast_runs", "forecast_predictions"}


def test_live_foreign_key_rejects_unknown_source(mysql_test_db):
    connection, _ = mysql_test_db
    with pytest.raises(mysql.connector.IntegrityError):
        insert_measurements(connection, 999, [parse_line(VALID_LINE)[0]])


def test_live_get_or_create_source_is_idempotent(mysql_test_db):
    connection, _ = mysql_test_db
    first = get_or_create_source(connection, "a.txt")
    assert get_or_create_source(connection, "a.txt") == first
    assert get_or_create_source(connection, "b.txt") != first
    assert fetch_all(connection, "SELECT COUNT(*) FROM dataset_sources")[0][0] == 2


def test_live_nulls_stored_and_duplicates_skipped(mysql_test_db):
    connection, _ = mysql_test_db
    source_id = get_or_create_source(connection, "a.txt")
    valid, missing = parse_line(VALID_LINE)[0], parse_line(MISSING_LINE)[0]

    assert insert_measurements(connection, source_id, [valid, missing]) == 2

    changed = dict(valid, global_active_power=9.999)  # same minute, different value
    assert insert_measurements(connection, source_id, [changed, missing]) == 0

    rows = fetch_all(connection, "SELECT measured_at, global_active_power FROM energy_measurements ORDER BY measured_at")
    assert len(rows) == 2
    assert float(rows[0][1]) == 4.216  # the original value was kept
    assert rows[1][1] is None          # NULL, not 0


def test_live_import_script_is_safe_to_rerun(mysql_test_db, tmp_path):
    _, name = mysql_test_db
    dataset = write_dataset(tmp_path / "small.txt", [VALID_LINE, VALID_LINE_2, MISSING_LINE, "bad;line"])
    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "import_mysql.py"), "--path", str(dataset)]
    environment = {**os.environ, "MYSQL_DATABASE": name}

    def run():
        result = subprocess.run(command, cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        return {key: int(value.replace(",", "")) for key, value in
                re.findall(r"^(Rows [a-z ]+?\(?[a-z]*\)?):\s+([\d,]+)", result.stdout, re.M)}

    first, second = run(), run()
    assert first["Rows inserted (new)"] == 3 and first["Rows rejected (invalid)"] == 1
    assert second["Rows inserted (new)"] == 0 and second["Rows skipped (existing)"] == 3
