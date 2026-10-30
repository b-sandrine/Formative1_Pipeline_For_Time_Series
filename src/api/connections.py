"""Open one store for the current request, and a function that closes it."""
from src.api.mongo_store import MongoReadingStore
from src.api.sql_store import SqlReadingStore
from src.database.mongo_db import create_indexes, get_database
from src.database.mysql_db import get_connection


def open_sql_store():
    """Return ``(store, close)``. ``close`` is safe to call once at the end."""
    connection = get_connection()
    return SqlReadingStore(connection), connection.close


def open_mongo_store():
    """Return ``(store, close)``.

    Indexes are created if they are missing. ``create_indexes`` does nothing
    when they already exist, and the unique index is what makes a duplicate
    POST return 409 instead of inserting a second document.
    """
    database = get_database()
    try:
        create_indexes(database)
    except Exception as error:
        database.client.close()
        raise RuntimeError(
            f"Could not prepare MongoDB indexes: {type(error).__name__}. "
            "Check that MongoDB is running."
        ) from error
    return MongoReadingStore(database), database.client.close
