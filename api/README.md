# Task 3: CRUD and time-series API

Small Flask service over the MySQL and MongoDB databases from Task 2.
Both databases expose the same routes. A reading from either one uses the
same JSON field names, so Task 4 can call either prefix.

The service does not import the dataset. Load the data first with
`sql/schema.sql`, `scripts/import_mysql.py`, and `scripts/import_mongodb.py`.

## Run

From the repository root, with the virtual environment activated and `.env` filled in:

```text
pip install -r requirements.txt
python scripts/run_api.py
```

The API listens on `http://127.0.0.1:5000`. Set `API_PORT` in `.env` to use another port.
`GET /` lists the routes. `GET /health` only checks that the process is up. It does not open a database.

## Routes

The same paths exist under `/sql` and under `/mongo`.

| Action | Method and path |
|---|---|
| Latest reading | `GET /sql/readings/latest` |
| Readings in a date range | `GET /sql/readings?start_date=2007-01-01&end_date=2007-01-01` |
| Recent readings | `GET /sql/readings` |
| One reading | `GET /sql/readings/<measurement_id>` |
| Create | `POST /sql/readings` |
| Update | `PUT /sql/readings/<measurement_id>` |
| Delete | `DELETE /sql/readings/<measurement_id>` |

MongoDB ids are 24-character hex strings. MySQL ids are integers.
`/readings/latest` is its own route, not an id.

## Field names for Task 4

Use these names. They match the MySQL columns and the MongoDB `measurements` object.

`measured_at`, `global_active_power`, `global_reactive_power`, `voltage`,
`global_intensity`, `sub_metering_1`, `sub_metering_2`, `sub_metering_3`

`global_active_power` keeps the underscores. `globalactive_power` is rejected.

`GET /sql/readings/latest` and `GET /mongo/readings/latest` return one object:

```json
{
  "measurement_id": 1,
  "source_id": 1,
  "measured_at": "2006-12-16T17:24:00",
  "global_active_power": 4.216,
  "global_reactive_power": 0.418,
  "voltage": 234.84,
  "global_intensity": 18.4,
  "sub_metering_1": 0.0,
  "sub_metering_2": 1.0,
  "sub_metering_3": 17.0
}
```

A date-range response wraps the rows:

```json
{
  "count": 1,
  "limit": 5000,
  "may_have_more": false,
  "readings": [ { "...": "same object as above" } ]
}
```

`measured_at` is local clock time with no time zone, the same value stored by Task 2.
A trailing `Z` is accepted and ignored. Do not send an offset such as `+02:00`.
Missing measurements are JSON `null`, not `0`.

## Date range

`start_date` and `end_date` must be sent together.

- `2007-01-01` covers that whole calendar day. The same start and end date returns that one day.
- `2007-01-01T00:00:00` is used as written. The end is exclusive, matching `sql/queries.sql`: `measured_at >= start AND measured_at < end`.

A range is capped at 5000 rows unless you pass `limit` (maximum 20000). A `GET` with no dates returns the 100 newest rows. `may_have_more` is true whenever the response contains exactly `limit` rows; this means more rows may exist, not that the API has confirmed another page. Raise `limit` or narrow the dates to retrieve a smaller range. The table holds about one row per minute from 2006 to 2010, so the cap is deliberate.

## Create, update, delete

`POST /sql/readings` with `Content-Type: application/json`:

```json
{
  "measured_at": "2006-12-16T17:30:00",
  "global_active_power": 3.5,
  "voltage": 240.1
}
```

`measured_at` is required. Measurement fields you leave out are stored as null.
`source_id` is optional: the API uses the first dataset source when you omit it.
MySQL `source_id` is an integer. MongoDB `source_id` is the source document's hex id.

`PUT` changes only the fields you send. `DELETE` returns `{"deleted": true, "measurement_id": ...}`.

Creating a second reading for the same source and minute returns `409`. The importer skips that case; the API reports it.

| Status | Meaning |
|---|---|
| 201 | Created |
| 400 | Bad JSON, unknown field, or a missing `measured_at` |
| 404 | No reading with that id, or no readings at all for `/latest` |
| 409 | That source already has a reading at that minute |
| 503 | MySQL or MongoDB could not be reached |

MongoDB documents are still stored in the Task 2 shape (`timestamp` and a `measurements` subdocument). The API flattens them on the way out and nests them again on the way in.

## PowerShell examples

```powershell
Invoke-RestMethod http://127.0.0.1:5000/sql/readings/latest

Invoke-RestMethod "http://127.0.0.1:5000/sql/readings?start_date=2007-01-01&end_date=2007-01-01"

$body = '{"measured_at":"2006-12-16T17:30:00","global_active_power":3.5,"voltage":240.1}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/sql/readings -ContentType "application/json" -Body $body

Invoke-RestMethod -Method Put -Uri http://127.0.0.1:5000/sql/readings/1 -ContentType "application/json" -Body '{"voltage":235.0}'

Invoke-RestMethod -Method Delete -Uri http://127.0.0.1:5000/sql/readings/1
```

Use `/mongo/...` the same way. On MongoDB, the id in the last two commands is the 24-character hex `measurement_id` from the latest response.

## Code map

| File | Role |
|---|---|
| `src/api/app.py` | Flask app, `/sql` and `/mongo` blueprints |
| `src/api/readings_routes.py` | CRUD, latest, and date-range routes |
| `src/api/sql_store.py` | Parameterized SQL for `energy_measurements` |
| `src/api/mongo_store.py` | Queries for `energy_readings` |
| `src/api/serialization.py` | Shared JSON field names |
| `src/api/validation.py` | Request checks and the date window |
| `scripts/run_api.py` | Starts the server |
| `tests/test_api.py` | Route and store tests, with no live database |

`pytest tests/test_api.py` does not need MySQL or MongoDB to be running.
