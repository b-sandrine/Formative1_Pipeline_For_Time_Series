"""MySQL reads and writes for ``energy_measurements``.

Every value is passed as a parameter. Column names in the UPDATE statement
come from a fixed list, never from the request text.
"""
from mysql.connector import Error as MySqlError

from src.api.errors import ApiError, DatabaseError, DuplicateReadingError
from src.api.serialization import reading_from_sql_row
from src.database.dataset_reader import MEASUREMENT_COLUMNS

READING_COLUMNS = ("measurement_id", "source_id", "measured_at", *MEASUREMENT_COLUMNS)

SELECT_READING_SQL = (
    "SELECT " + ", ".join(READING_COLUMNS) + " FROM energy_measurements "
)

INSERT_READING_SQL = (
    "INSERT INTO energy_measurements (source_id, measured_at, "
    + ", ".join(MEASUREMENT_COLUMNS)
    + ") VALUES (" + ", ".join(["%s"] * (2 + len(MEASUREMENT_COLUMNS))) + ")"
)


def _sql_source_id(value) -> int:
    if isinstance(value, bool):
        raise ApiError("source_id must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ApiError("source_id must be an integer")


class SqlReadingStore:
    def __init__(self, connection):
        self.connection = connection

    def latest(self):
        rows = self._fetchall(
            SELECT_READING_SQL + "ORDER BY measured_at DESC, measurement_id DESC LIMIT 1"
        )
        return reading_from_sql_row(rows[0]) if rows else None

    def get(self, measurement_id: int):
        rows = self._fetchall(
            SELECT_READING_SQL + "WHERE measurement_id = %s",
            (measurement_id,),
        )
        return reading_from_sql_row(rows[0]) if rows else None

    def list_recent(self, limit: int):
        rows = self._fetchall(
            SELECT_READING_SQL + "ORDER BY measured_at DESC, measurement_id DESC LIMIT %s",
            (limit,),
        )
        return [reading_from_sql_row(row) for row in rows]

    def list_range(self, start, end, limit: int):
        # Half-open on purpose: the end minute is not included. See range_bounds.
        rows = self._fetchall(
            SELECT_READING_SQL
            + "WHERE measured_at >= %s AND measured_at < %s "
            "ORDER BY measured_at ASC, measurement_id ASC LIMIT %s",
            (start, end, limit),
        )
        return [reading_from_sql_row(row) for row in rows]

    def create(self, fields: dict):
        source_id = self._resolve_source_id(fields.get("source_id"))
        params = [source_id, fields["measured_at"]]
        params.extend(fields.get(column) for column in MEASUREMENT_COLUMNS)
        new_id, _rowcount = self._execute(INSERT_READING_SQL, params)
        self._commit()
        return self.get(new_id)

    def update(self, measurement_id: int, fields: dict):
        if self.get(measurement_id) is None:
            return None
        columns = []
        params = []
        if "measured_at" in fields:
            columns.append("measured_at")
            params.append(fields["measured_at"])
        if "source_id" in fields:
            columns.append("source_id")
            params.append(self._resolve_source_id(fields["source_id"]))
        for column in MEASUREMENT_COLUMNS:
            if column in fields:
                columns.append(column)
                params.append(fields[column])
        sql = (
            "UPDATE energy_measurements SET "
            + ", ".join(f"{column} = %s" for column in columns)
            + " WHERE measurement_id = %s"
        )
        params.append(measurement_id)
        self._execute(sql, params)
        self._commit()
        return self.get(measurement_id)

    def delete(self, measurement_id: int) -> bool:
        _new_id, rowcount = self._execute(
            "DELETE FROM energy_measurements WHERE measurement_id = %s",
            (measurement_id,),
        )
        self._commit()
        return rowcount > 0

    def _resolve_source_id(self, provided):
        if provided is None:
            rows = self._fetchall(
                "SELECT source_id FROM dataset_sources ORDER BY source_id LIMIT 1"
            )
            if not rows:
                raise ApiError(
                    "No dataset source exists. Import the dataset or pass source_id.",
                )
            return rows[0]["source_id"]
        source_id = _sql_source_id(provided)
        rows = self._fetchall(
            "SELECT source_id FROM dataset_sources WHERE source_id = %s",
            (source_id,),
        )
        if not rows:
            raise ApiError(f"source_id {source_id} does not exist")
        return source_id

    def _fetchall(self, sql: str, params=()):
        cursor = self.connection.cursor(dictionary=True)
        try:
            cursor.execute(sql, params)
            return list(cursor.fetchall())
        except MySqlError as error:
            self._translate(error)
        finally:
            cursor.close()

    def _execute(self, sql: str, params):
        cursor = self.connection.cursor(dictionary=True)
        try:
            cursor.execute(sql, params)
            return cursor.lastrowid, cursor.rowcount
        except MySqlError as error:
            self._translate(error)
        finally:
            cursor.close()

    def _commit(self):
        try:
            self.connection.commit()
        except MySqlError as error:
            self._translate(error)

    def _translate(self, error: MySqlError):
        self.connection.rollback()
        # 1062 is a duplicate unique key. 1452 is a foreign key that does not exist.
        if error.errno == 1062:
            raise DuplicateReadingError() from error
        if error.errno == 1452:
            raise ApiError("source_id does not exist") from error
        message = getattr(error, "msg", None) or str(error)
        raise DatabaseError(message) from error
