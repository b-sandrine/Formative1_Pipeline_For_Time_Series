"""MongoDB reads and writes for the ``energy_readings`` collection.

Documents keep the shape from mongodb/collection_design.md: ``timestamp``
plus a ``measurements`` subdocument. The API flattens that for the response
so it matches the MySQL JSON.
"""
from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError

from src.api.errors import ApiError, DatabaseError, DuplicateReadingError
from src.api.serialization import reading_from_mongo
from src.database.dataset_reader import MEASUREMENT_COLUMNS


def _object_id(value, field_name: str) -> ObjectId:
    if not isinstance(value, str):
        raise ApiError(f"{field_name} must be a 24-character hex string")
    try:
        return ObjectId(value)
    except InvalidId:
        raise ApiError(f"{field_name} must be a 24-character hex string") from None


class MongoReadingStore:
    def __init__(self, database):
        self.database = database

    def latest(self):
        document = self._find_one(
            sort=[("timestamp", DESCENDING), ("_id", DESCENDING)],
        )
        return reading_from_mongo(document) if document else None

    def get(self, measurement_id: str):
        document = self._find_one({"_id": _object_id(measurement_id, "measurement_id")})
        return reading_from_mongo(document) if document else None

    def list_recent(self, limit: int):
        cursor = self._find({}).sort(
            [("timestamp", DESCENDING), ("_id", DESCENDING)]
        ).limit(limit)
        return [reading_from_mongo(document) for document in cursor]

    def list_range(self, start, end, limit: int):
        # Same half-open window as the MySQL query and mongodb/queries.js.
        cursor = self._find(
            {"timestamp": {"$gte": start, "$lt": end}},
        ).sort([("timestamp", ASCENDING), ("_id", ASCENDING)]).limit(limit)
        return [reading_from_mongo(document) for document in cursor]

    def create(self, fields: dict):
        source_id = self._resolve_source_id(fields.get("source_id"))
        # Every reading stores all seven fields. Omitted ones are null,
        # matching the importer and the MySQL columns.
        document = {
            "source_id": source_id,
            "timestamp": fields["measured_at"],
            "measurements": {
                column: fields.get(column) for column in MEASUREMENT_COLUMNS
            },
        }
        try:
            inserted_id = self.database.energy_readings.insert_one(document).inserted_id
        except DuplicateKeyError:
            raise DuplicateReadingError() from None
        except PyMongoError as error:
            raise DatabaseError(str(error)) from error
        return self.get(str(inserted_id))

    def update(self, measurement_id: str, fields: dict):
        if self.get(measurement_id) is None:
            return None
        updates = {}
        if "measured_at" in fields:
            updates["timestamp"] = fields["measured_at"]
        if "source_id" in fields:
            updates["source_id"] = self._resolve_source_id(fields["source_id"])
        for column in MEASUREMENT_COLUMNS:
            if column in fields:
                updates[f"measurements.{column}"] = fields[column]
        try:
            self.database.energy_readings.update_one(
                {"_id": _object_id(measurement_id, "measurement_id")},
                {"$set": updates},
            )
        except DuplicateKeyError:
            raise DuplicateReadingError() from None
        except PyMongoError as error:
            raise DatabaseError(str(error)) from error
        return self.get(measurement_id)

    def delete(self, measurement_id: str) -> bool:
        try:
            result = self.database.energy_readings.delete_one(
                {"_id": _object_id(measurement_id, "measurement_id")}
            )
        except PyMongoError as error:
            raise DatabaseError(str(error)) from error
        return result.deleted_count > 0

    def _resolve_source_id(self, provided):
        try:
            if provided is None:
                document = self.database.dataset_sources.find_one(
                    {}, {"_id": 1}, sort=[("_id", ASCENDING)],
                )
                if document is None:
                    raise ApiError(
                        "No dataset source exists. Import the dataset or pass source_id.",
                    )
                return document["_id"]
            source_id = _object_id(provided, "source_id")
            document = self.database.dataset_sources.find_one(
                {"_id": source_id}, {"_id": 1},
            )
        except PyMongoError as error:
            raise DatabaseError(str(error)) from error
        if document is None:
            raise ApiError("source_id does not exist")
        return source_id

    def _find_one(self, query=None, sort=None):
        try:
            if sort is None:
                return self.database.energy_readings.find_one(query)
            return self.database.energy_readings.find_one(query, sort=sort)
        except PyMongoError as error:
            raise DatabaseError(str(error)) from error

    def _find(self, query):
        try:
            return self.database.energy_readings.find(query)
        except PyMongoError as error:
            raise DatabaseError(str(error)) from error
