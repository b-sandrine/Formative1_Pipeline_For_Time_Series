"""MongoDB connection helper and index definitions."""
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

from src.database.config import get_mongo_config


def get_database():
    """Connect to MongoDB and return the database object.

    Raises RuntimeError with a readable message if the server is not reachable.
    The connection string is not included in the message (it may hold a password).
    """
    settings = get_mongo_config()
    client = MongoClient(settings["uri"], serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")  # fails fast if the server is down
    except PyMongoError as error:
        client.close()
        raise RuntimeError(
            f"Could not connect to MongoDB (database '{settings['database']}'): "
            f"{type(error).__name__}. Check that MongoDB is running and that "
            "MONGODB_URI in .env is correct."
        ) from error
    return client[settings["database"]]


def create_indexes(database) -> None:
    """Create the indexes described in mongodb/collection_design.md.

    create_index does nothing if the same index already exists, so this is
    safe to call every time. The unique indexes are what stop duplicate
    documents when an importer is rerun.
    """
    database.dataset_sources.create_index(
        [("name", ASCENDING), ("original_filename", ASCENDING)], unique=True)
    database.energy_readings.create_index(
        [("source_id", ASCENDING), ("timestamp", ASCENDING)], unique=True)
    database.energy_readings.create_index([("timestamp", ASCENDING)])
    database.forecast_results.create_index(
        [("source_id", ASCENDING), ("run_at", DESCENDING)])
