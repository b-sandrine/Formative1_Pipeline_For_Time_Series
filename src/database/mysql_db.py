"""MySQL connection helper."""
import mysql.connector

from src.database.config import get_mysql_config


def get_connection():
    """Open a MySQL connection with autocommit off (we commit batches ourselves).

    Raises RuntimeError with a readable message if the connection fails.
    The password is never included in the message.
    """
    settings = get_mysql_config()
    try:
        return mysql.connector.connect(**settings, autocommit=False)
    except mysql.connector.Error as error:
        raise RuntimeError(
            f"Could not connect to MySQL at {settings['host']}:{settings['port']} "
            f"(database '{settings['database']}', user '{settings['user']}'): {error.msg}. "
            "Check that MySQL is running, that sql/schema.sql has been run, "
            "and that the MYSQL_* values in .env are correct."
        ) from error
