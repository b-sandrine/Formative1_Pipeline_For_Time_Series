"""SQL used to save data in MySQL. Every statement is parameterized."""
from src.database.dataset_reader import MEASUREMENT_COLUMNS

SOURCE_NAME = "Household Electric Power Consumption"
SOURCE_URL = "https://www.kaggle.com/datasets/uciml/electric-power-consumption-data-set"
SOURCE_DESCRIPTION = "One-minute household electricity measurements, December 2006 to November 2010."
SOURCE_TIMEZONE_NOTE = "Local time as recorded; the file has no time zone. Stored as-is, not converted."

# "ON DUPLICATE KEY UPDATE measured_at = measured_at" changes nothing.
# If (source_id, measured_at) already exists the row is skipped, and MySQL
# reports it as 0 affected rows.
INSERT_MEASUREMENT_SQL = (
    "INSERT INTO energy_measurements (source_id, measured_at, "
    + ", ".join(MEASUREMENT_COLUMNS)
    + ") VALUES (%s, %s, " + ", ".join(["%s"] * len(MEASUREMENT_COLUMNS)) + ") "
    "ON DUPLICATE KEY UPDATE measured_at = measured_at"
)


def get_or_create_source(connection, original_filename: str) -> int:
    """Return the source_id for this file, creating the row the first time."""
    cursor = connection.cursor()
    cursor.execute(
        "SELECT source_id FROM dataset_sources WHERE name = %s AND original_filename = %s",
        (SOURCE_NAME, original_filename),
    )
    row = cursor.fetchone()
    if row is not None:
        cursor.close()
        return row[0]
    cursor.execute(
        "INSERT INTO dataset_sources (name, description, source_url, original_filename, timezone_note) "
        "VALUES (%s, %s, %s, %s, %s)",
        (SOURCE_NAME, SOURCE_DESCRIPTION, SOURCE_URL, original_filename, SOURCE_TIMEZONE_NOTE),
    )
    connection.commit()
    source_id = cursor.lastrowid
    cursor.close()
    return source_id


def insert_measurements(connection, source_id: int, records: list) -> int:
    """Insert one batch in a single transaction. Returns how many rows were new."""
    rows = [
        (source_id, record["measured_at"], *[record[column] for column in MEASUREMENT_COLUMNS])
        for record in records
    ]
    cursor = connection.cursor()
    try:
        cursor.executemany(INSERT_MEASUREMENT_SQL, rows)
        inserted = cursor.rowcount
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
    return inserted
