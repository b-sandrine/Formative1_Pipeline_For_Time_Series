"""MongoDB tests.

Unit tests use fake objects. Live tests use a throwaway database with a
random name (energy_test_xxxxxxxx), never touch your real data, and drop it
at the end. They are skipped if MongoDB cannot be reached.
"""
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from pymongo import MongoClient
from pymongo.errors import BulkWriteError, ServerSelectionTimeoutError

from src.database import mongo_db
from src.database.config import PROJECT_ROOT, get_mongo_config
from src.database.dataset_reader import MEASUREMENT_COLUMNS, parse_line
from src.database.repositories import get_or_create_mongo_source, insert_mongo_readings
from tests.test_database import MISSING_LINE, VALID_LINE, VALID_LINE_2, write_dataset


# ------------------------------------------------------------------ unit tests
def database_with(insert_many):
    return SimpleNamespace(energy_readings=SimpleNamespace(insert_many=insert_many))


def test_connection_error_is_readable_and_hides_credentials(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://someone:secret123@localhost:1/")

    class FailingClient:
        def __init__(self, uri, **_):
            self.admin = SimpleNamespace(command=self.fail)

        def fail(self, *_):
            raise ServerSelectionTimeoutError("no server")

        def close(self):
            pass

    monkeypatch.setattr(mongo_db, "MongoClient", FailingClient)
    with pytest.raises(RuntimeError) as caught:
        mongo_db.get_database()
    assert "Could not connect to MongoDB" in str(caught.value)
    assert "secret123" not in str(caught.value)


def test_documents_have_expected_shape_and_keep_none():
    captured = []

    def insert_many(documents, ordered):
        captured.extend(documents)
        return SimpleNamespace(inserted_ids=list(range(len(documents))))

    records = [parse_line(VALID_LINE)[0], parse_line(MISSING_LINE)[0]]
    assert insert_mongo_readings(database_with(insert_many), "source-1", records) == 2

    assert captured[0]["source_id"] == "source-1"
    assert captured[0]["timestamp"] == datetime(2006, 12, 16, 17, 24)
    assert set(captured[0]["measurements"]) == set(MEASUREMENT_COLUMNS)
    assert all(value is None for value in captured[1]["measurements"].values())  # not 0


def test_duplicate_key_errors_are_counted_as_skipped():
    def insert_many(documents, ordered):
        raise BulkWriteError({"writeErrors": [{"code": 11000, "index": 1}], "nInserted": 1})

    records = [parse_line(VALID_LINE)[0], parse_line(VALID_LINE_2)[0]]
    assert insert_mongo_readings(database_with(insert_many), "s", records) == 1


def test_other_write_errors_are_not_hidden():
    def insert_many(documents, ordered):
        raise BulkWriteError({"writeErrors": [{"code": 121, "index": 0}], "nInserted": 0})

    with pytest.raises(BulkWriteError):
        insert_mongo_readings(database_with(insert_many), "s", [parse_line(VALID_LINE)[0]])


# ----------------------------------------------------------------- live tests
@pytest.fixture
def mongo_test_db():
    """Yield (database, name) for a throwaway database that is dropped afterwards."""
    client = MongoClient(get_mongo_config()["uri"], serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except Exception as error:
        client.close()
        pytest.skip(f"MongoDB not reachable: {type(error).__name__}")

    name = f"energy_test_{uuid.uuid4().hex[:8]}"
    assert name.startswith("energy_test_")  # we only ever drop our own database
    database = client[name]
    mongo_db.create_indexes(database)
    try:
        yield database, name
    finally:
        client.drop_database(name)
        client.close()


def test_live_indexes_are_created_and_unique(mongo_test_db):
    database, _ = mongo_test_db
    readings = database.energy_readings.index_information()
    assert readings["source_id_1_timestamp_1"]["unique"] is True
    assert "timestamp_1" in readings
    assert database.dataset_sources.index_information()["name_1_original_filename_1"]["unique"] is True


def test_live_source_is_created_once(mongo_test_db):
    database, _ = mongo_test_db
    first = get_or_create_mongo_source(database, "a.txt")
    assert get_or_create_mongo_source(database, "a.txt") == first
    assert database.dataset_sources.count_documents({}) == 1


def test_live_dates_nulls_and_duplicates(mongo_test_db):
    database, _ = mongo_test_db
    source_id = get_or_create_mongo_source(database, "a.txt")
    valid, missing = parse_line(VALID_LINE)[0], parse_line(MISSING_LINE)[0]

    assert insert_mongo_readings(database, source_id, [valid, missing]) == 2
    changed = dict(valid, global_active_power=9.999)  # same minute, different value
    assert insert_mongo_readings(database, source_id, [changed, missing]) == 0

    documents = list(database.energy_readings.find().sort("timestamp", 1))
    assert len(documents) == 2
    assert documents[0]["timestamp"] == datetime(2006, 12, 16, 17, 24)  # BSON Date
    assert documents[0]["measurements"]["global_active_power"] == 4.216  # original kept
    assert documents[1]["measurements"]["global_active_power"] is None
    assert database.command("aggregate", "energy_readings", pipeline=[
        {"$group": {"_id": {"$type": "$timestamp"}}}], cursor={})["cursor"]["firstBatch"] == [{"_id": "date"}]


def test_live_import_script_is_safe_to_rerun(mongo_test_db, tmp_path):
    _, name = mongo_test_db
    dataset = write_dataset(tmp_path / "small.txt", [VALID_LINE, VALID_LINE_2, MISSING_LINE, "bad;line"])
    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "import_mongodb.py"), "--path", str(dataset)]
    environment = {**os.environ, "MONGODB_DATABASE": name}

    def run():
        result = subprocess.run(command, cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        return {key: int(value.replace(",", "")) for key, value in
                re.findall(r"^(Rows [a-z ]+?\(?[a-z]*\)?):\s+([\d,]+)", result.stdout, re.M)}

    first, second = run(), run()
    assert first["Rows inserted (new)"] == 3 and first["Rows rejected (invalid)"] == 1
    assert second["Rows inserted (new)"] == 0 and second["Rows skipped (existing)"] == 3
