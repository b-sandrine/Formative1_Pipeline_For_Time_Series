"""Task 3 API tests.

These tests do not connect to MySQL or MongoDB. They call the Flask app
with stand-in stores, and they check the SQL and Mongo stores with fakes.
"""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import mysql.connector
import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from src.api.app import create_app
from src.api.errors import DuplicateReadingError
from src.api.mongo_store import MongoReadingStore
from src.api.sql_store import INSERT_READING_SQL, SqlReadingStore
from src.api.validation import parse_timestamp, range_bounds
from src.database.dataset_reader import MEASUREMENT_COLUMNS


SAMPLE = {
    "measurement_id": 1,
    "source_id": 1,
    "measured_at": "2006-12-16T17:24:00",
    "global_active_power": 4.216,
    "global_reactive_power": 0.418,
    "voltage": 234.84,
    "global_intensity": 18.4,
    "sub_metering_1": 0.0,
    "sub_metering_2": 1.0,
    "sub_metering_3": 17.0,
}
MONGO_ID = "656f1c2e8b4e1a0d5c3b2a19"
MONGO_SOURCE = "656f1c2e8b4e1a0d5c3b2a10"


class RecordingStore:
    """Enough of a store for the HTTP tests. Records what the route asked for."""

    def __init__(self, reading=SAMPLE):
        self.reading = reading
        self.closed_after = []
        self.created = None
        self.updated = None
        self.deleted = None
        self.range_args = None
        self.recent_limit = None
        self.raise_on_create = None

    def latest(self):
        return self.reading

    def get(self, measurement_id):
        if self.reading is None or self.reading["measurement_id"] != measurement_id:
            return None
        return self.reading

    def list_recent(self, limit):
        self.recent_limit = limit
        return [] if self.reading is None else [self.reading]

    def list_range(self, start, end, limit):
        self.range_args = (start, end, limit)
        return [] if self.reading is None else [self.reading]

    def create(self, fields):
        if self.raise_on_create is not None:
            raise self.raise_on_create
        self.created = fields
        created = dict(self.reading)
        created["measured_at"] = fields["measured_at"].strftime("%Y-%m-%dT%H:%M:%S")
        return created

    def update(self, measurement_id, fields):
        self.updated = (measurement_id, fields)
        if self.reading is None or self.reading["measurement_id"] != measurement_id:
            return None
        return self.reading

    def delete(self, measurement_id):
        self.deleted = measurement_id
        return self.reading is not None and self.reading["measurement_id"] == measurement_id


def _opener(store, closes):
    def open_store():
        def close():
            closes.append(store)

        return store, close

    return open_store


@pytest.fixture
def stores():
    return RecordingStore(dict(SAMPLE)), RecordingStore({
        **SAMPLE,
        "measurement_id": MONGO_ID,
        "source_id": MONGO_SOURCE,
    })


@pytest.fixture
def client(stores):
    sql_store, mongo_store = stores
    closes = []
    app = create_app(
        open_sql=_opener(sql_store, closes),
        open_mongo=_opener(mongo_store, closes),
    )
    app.testing = True
    test_client = app.test_client()
    test_client.closes = closes
    return test_client


def test_health_does_not_need_a_database():
    app = create_app()
    response = app.test_client().get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_latest_uses_snake_case_measurement_names(client):
    response = client.get("/sql/readings/latest")
    assert response.status_code == 200
    body = response.get_json()
    assert list(body) == [
        "measurement_id", "source_id", "measured_at", *MEASUREMENT_COLUMNS,
    ]
    assert body["global_active_power"] == 4.216
    assert body["voltage"] == 234.84
    assert "globalactive_power" not in body


def test_mongo_latest_matches_the_sql_field_names(client):
    response = client.get("/mongo/readings/latest")
    assert response.status_code == 200
    body = response.get_json()
    assert body["measurement_id"] == MONGO_ID
    assert body["global_active_power"] == 4.216
    assert body["sub_metering_3"] == 17.0


def test_latest_is_404_when_the_table_is_empty(client, stores):
    stores[0].reading = None
    response = client.get("/sql/readings/latest")
    assert response.status_code == 404
    assert response.get_json()["error"] == "No readings found"


def test_date_range_includes_the_whole_end_day(client, stores):
    response = client.get("/sql/readings?start_date=2007-01-01&end_date=2007-01-01")
    assert response.status_code == 200
    start, end, limit = stores[0].range_args
    assert start == datetime(2007, 1, 1)
    assert end == datetime(2007, 1, 2)
    assert limit == 5000
    body = response.get_json()
    assert body["count"] == 1
    assert body["readings"][0]["measured_at"] == "2006-12-16T17:24:00"


def test_datetime_range_keeps_the_end_exclusive(client, stores):
    response = client.get(
        "/mongo/readings?start_date=2007-01-01T00:00:00&end_date=2007-01-01T00:10:00"
    )
    assert response.status_code == 200
    start, end, _limit = stores[1].range_args
    assert (start, end) == (datetime(2007, 1, 1, 0, 0), datetime(2007, 1, 1, 0, 10))


def test_range_requires_both_dates(client):
    response = client.get("/sql/readings?start_date=2007-01-01")
    assert response.status_code == 400
    assert "both" in response.get_json()["error"]


def test_list_without_dates_asks_for_recent_rows(client, stores):
    response = client.get("/sql/readings?limit=25")
    assert response.status_code == 200
    assert stores[0].recent_limit == 25
    assert stores[0].range_args is None


def test_post_creates_a_reading(client, stores):
    response = client.post("/sql/readings", json={
        "measured_at": "2006-12-16T17:24:00Z",
        "global_active_power": 4.216,
        "voltage": None,
    })
    assert response.status_code == 201
    assert stores[0].created["measured_at"] == datetime(2006, 12, 16, 17, 24)
    assert stores[0].created["global_active_power"] == 4.216
    assert stores[0].created["voltage"] is None
    assert "sub_metering_1" not in stores[0].created


def test_post_rejects_unknown_or_non_numeric_fields(client):
    unknown = client.post("/sql/readings", json={
        "measured_at": "2006-12-16T17:24:00",
        "globalactive_power": 1,
    })
    assert unknown.status_code == 400
    assert "globalactive_power" in unknown.get_json()["error"]

    missing = client.post("/mongo/readings", json={"voltage": 230})
    assert missing.status_code == 400
    assert "measured_at" in missing.get_json()["error"]

    boolean = client.post("/sql/readings", json={
        "measured_at": "2006-12-16T17:24:00",
        "voltage": True,
    })
    assert boolean.status_code == 400


def test_put_and_delete(client, stores):
    updated = client.put("/sql/readings/1", json={"voltage": 235.1})
    assert updated.status_code == 200
    assert stores[0].updated[0] == 1
    assert stores[0].updated[1]["voltage"] == 235.1

    missing = client.put("/sql/readings/99", json={"voltage": 1})
    assert missing.status_code == 404

    deleted = client.delete("/mongo/readings/" + MONGO_ID)
    assert deleted.status_code == 200
    assert deleted.get_json()["deleted"] is True
    assert stores[1].deleted == MONGO_ID


def test_get_one_and_missing(client):
    assert client.get("/sql/readings/1").status_code == 200
    missing = client.get("/sql/readings/99")
    assert missing.status_code == 404
    assert missing.get_json()["error"] == "Reading not found"


def test_duplicate_is_a_conflict(client, stores):
    stores[0].raise_on_create = DuplicateReadingError()
    response = client.post("/sql/readings", json={"measured_at": "2006-12-16T17:24:00"})
    assert response.status_code == 409


def test_database_down_is_503_and_hides_nothing_extra():
    def down():
        raise RuntimeError("Could not connect to MySQL at localhost:3306")

    app = create_app(open_sql=down, open_mongo=down)
    response = app.test_client().get("/sql/readings/latest")
    assert response.status_code == 503
    assert "Could not connect" in response.get_json()["error"]


def test_store_is_closed_after_success_and_after_a_bad_request(client):
    assert client.get("/sql/readings/latest").status_code == 200
    assert client.post("/sql/readings", json={}).status_code == 400
    assert len(client.closes) == 2


def test_unknown_path_and_wrong_method_are_json(client):
    missing = client.get("/does-not-exist")
    assert missing.status_code == 404
    assert missing.get_json()["error"] == "Not found"
    wrong = client.post("/sql/readings/latest")
    assert wrong.status_code == 405
    assert wrong.get_json()["error"] == "Method not allowed"


def test_trailing_z_is_the_same_clock_time():
    assert parse_timestamp("2006-12-16T17:24:00.000Z") == datetime(2006, 12, 16, 17, 24)


def test_numeric_offset_is_rejected():
    with pytest.raises(Exception) as caught:
        parse_timestamp("2006-12-16T17:24:00+02:00")
    assert "offset" in str(caught.value)


def test_range_rejects_a_backwards_window():
    with pytest.raises(Exception) as caught:
        range_bounds("2007-01-02T00:00:00", "2007-01-01T00:00:00")
    assert "earlier" in str(caught.value)


# ---------------------------------------------------------------- store fakes
class ScriptedConnection:
    def __init__(self, steps):
        self.steps = list(steps)
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, dictionary=True):
        return ScriptedCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class ScriptedCursor:
    def __init__(self, connection):
        self.connection = connection
        self.step = {}
        self.lastrowid = 0
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.connection.executed.append((" ".join(sql.split()), params))
        self.step = self.connection.steps.pop(0)
        if "error" in self.step:
            raise self.step["error"]
        self.lastrowid = self.step.get("lastrowid", 0)
        self.rowcount = self.step.get("rowcount", 0)

    def fetchall(self):
        return self.step.get("fetchall", [])

    def close(self):
        pass


SQL_ROW = {
    "measurement_id": 9,
    "source_id": 1,
    "measured_at": datetime(2006, 12, 16, 17, 24),
    "global_active_power": Decimal("4.216"),
    "global_reactive_power": Decimal("0.418"),
    "voltage": Decimal("234.840"),
    "global_intensity": Decimal("18.400"),
    "sub_metering_1": Decimal("0.000"),
    "sub_metering_2": Decimal("1.000"),
    "sub_metering_3": Decimal("17.000"),
}


def test_insert_sql_is_parameterized():
    assert INSERT_READING_SQL.count("%s") == 9
    assert "4.216" not in INSERT_READING_SQL
    # The importer skips duplicates quietly. The API must report them instead.
    assert "ON DUPLICATE KEY" not in INSERT_READING_SQL


def test_sql_latest_serializes_decimals_and_timestamps():
    connection = ScriptedConnection([{"fetchall": [SQL_ROW]}])
    reading = SqlReadingStore(connection).latest()
    sql, params = connection.executed[0]
    assert "ORDER BY measured_at DESC" in sql
    assert "LIMIT 1" in sql
    assert params is None or params == ()
    assert reading["global_active_power"] == 4.216
    assert reading["measured_at"] == "2006-12-16T17:24:00"
    assert isinstance(reading["voltage"], float)


def test_sql_range_passes_datetimes_as_parameters():
    connection = ScriptedConnection([{"fetchall": []}])
    start, end = datetime(2007, 1, 1), datetime(2007, 1, 1, 0, 10)
    assert SqlReadingStore(connection).list_range(start, end, 10) == []
    sql, params = connection.executed[0]
    assert "measured_at >= %s AND measured_at < %s" in sql
    assert params == (start, end, 10)
    assert "2007-01-01" not in sql


def test_sql_create_uses_the_first_source_and_commits():
    connection = ScriptedConnection([
        {"fetchall": [{"source_id": 4}]},
        {"lastrowid": 9, "rowcount": 1},
        {"fetchall": [SQL_ROW]},
    ])
    reading = SqlReadingStore(connection).create({
        "measured_at": datetime(2006, 12, 16, 17, 24),
        "global_active_power": 4.216,
    })
    assert connection.commits == 1
    assert connection.rollbacks == 0
    _select_source, insert, _select_new = connection.executed
    assert insert[1][0] == 4
    assert insert[1][2] == 4.216
    assert insert[1][3] is None  # omitted measurements are stored as NULL
    assert reading["measurement_id"] == 9


def test_sql_update_only_changes_fields_present_in_the_body():
    connection = ScriptedConnection([
        {"fetchall": [SQL_ROW]},
        {"rowcount": 1},
        {"fetchall": [SQL_ROW]},
    ])
    SqlReadingStore(connection).update(9, {"voltage": 230.0})
    sql, params = connection.executed[1]
    assert sql == "UPDATE energy_measurements SET voltage = %s WHERE measurement_id = %s"
    assert list(params) == [230.0, 9]


def test_sql_duplicate_rolls_back_and_does_not_commit():
    connection = ScriptedConnection([
        {"fetchall": [{"source_id": 1}]},
        {"error": mysql.connector.Error(msg="Duplicate entry", errno=1062)},
    ])
    with pytest.raises(DuplicateReadingError):
        SqlReadingStore(connection).create({
            "measured_at": datetime(2006, 12, 16, 17, 24),
        })
    assert (connection.commits, connection.rollbacks) == (0, 1)


class FakeCursor:
    def __init__(self, collection, query):
        self.collection = collection
        self.query = query

    def sort(self, spec):
        self.collection.sorts.append(spec)
        return self

    def limit(self, count):
        self.collection.limits.append(count)
        return self

    def __iter__(self):
        return iter(self.collection.docs)


class FakeReadings:
    def __init__(self):
        self.docs = []
        self.queries = []
        self.sorts = []
        self.limits = []
        self.duplicate = False

    def find_one(self, query=None, *args, **kwargs):
        self.queries.append((query, kwargs.get("sort")))
        if query and "_id" in query:
            return next((doc for doc in self.docs if doc["_id"] == query["_id"]), None)
        return self.docs[-1] if self.docs else None

    def find(self, query):
        self.queries.append(query)
        return FakeCursor(self, query)

    def insert_one(self, document):
        if self.duplicate:
            raise DuplicateKeyError("duplicate key")
        document = dict(document)
        document["_id"] = ObjectId(MONGO_ID)
        self.docs.append(document)
        return SimpleNamespace(inserted_id=document["_id"])

    def update_one(self, query, update):
        for doc in self.docs:
            if doc["_id"] == query["_id"]:
                for key, value in update["$set"].items():
                    if key.startswith("measurements."):
                        doc["measurements"][key.split(".", 1)[1]] = value
                    else:
                        doc[key] = value
        return SimpleNamespace(matched_count=1)

    def delete_one(self, query):
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if doc["_id"] != query["_id"]]
        return SimpleNamespace(deleted_count=before - len(self.docs))


class FakeSources:
    def __init__(self, source_id):
        self.source_id = source_id

    def find_one(self, query=None, projection=None, sort=None):
        if query and query.get("_id") not in (None, self.source_id):
            return None
        return {"_id": self.source_id}


def _mongo_store():
    source_id = ObjectId(MONGO_SOURCE)
    database = SimpleNamespace(
        energy_readings=FakeReadings(),
        dataset_sources=FakeSources(source_id),
    )
    return MongoReadingStore(database), database


def test_mongo_create_stores_the_task2_document_shape_and_returns_flat_json():
    store, database = _mongo_store()
    reading = store.create({
        "measured_at": datetime(2006, 12, 16, 17, 24),
        "global_active_power": 4.216,
    })
    document = database.energy_readings.docs[0]
    assert document["source_id"] == ObjectId(MONGO_SOURCE)
    assert document["timestamp"] == datetime(2006, 12, 16, 17, 24)
    assert document["measurements"]["global_active_power"] == 4.216
    assert document["measurements"]["voltage"] is None
    assert reading["measurement_id"] == MONGO_ID
    assert reading["global_active_power"] == 4.216
    assert "measurements" not in reading


def test_mongo_range_uses_a_half_open_timestamp_filter():
    store, database = _mongo_store()
    start, end = datetime(2007, 1, 1), datetime(2007, 1, 2)
    assert store.list_range(start, end, 5) == []
    assert database.energy_readings.queries[-1] == {
        "timestamp": {"$gte": start, "$lt": end},
    }
    assert database.energy_readings.limits == [5]


def test_mongo_duplicate_and_bad_id():
    store, database = _mongo_store()
    database.energy_readings.duplicate = True
    with pytest.raises(DuplicateReadingError):
        store.create({"measured_at": datetime(2006, 12, 16, 17, 24)})
    with pytest.raises(Exception) as caught:
        store.get("not-an-id")
    assert caught.value.status == 400
