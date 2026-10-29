# MySQL design

Database name: `energy_consumption`. Schema file: [schema.sql](schema.sql). ERD source: [erd.mmd](erd.mmd).

## Tables and relationships

| Table | Purpose |
|---|---|
| `dataset_sources` | One row per imported file (name, URL, filename, time-zone note, import time). |
| `energy_measurements` | One row per one-minute reading. Belongs to one source. |
| `forecast_runs` | One row per forecasting experiment (model name, target, RMSE, MAE). Belongs to one source. |
| `forecast_predictions` | One row per predicted value. Belongs to one run. |

```
dataset_sources 1 ──< energy_measurements
dataset_sources 1 ──< forecast_runs 1 ──< forecast_predictions
```

All relationships are one-to-many. A source has many measurements and many
runs, and a run has many predictions.

## Design decisions

- **Missing values are `NULL`, not 0.** The file has 25,979 rows where every
  measurement is `?`. We keep the row (so the time gap is visible) and store
  `NULL`. A 0 would look like a real reading and lower the averages.
- **`DECIMAL(8,3)`** keeps the three decimals in the file exactly. `FLOAT`
  would introduce rounding errors.
- **Timestamps are `DATETIME` with no time zone.** The file gives local time
  and does not say which zone. The same naive value is stored in MongoDB, so
  both databases agree. The note is stored in `dataset_sources.timezone_note`.
- **`UNIQUE (source_id, measured_at)`** allows one reading per minute per source.
  Rerunning the importer cannot create duplicates, and the index also speeds up
  date-range queries.
- **Foreign keys** use the default `RESTRICT` between sources and their
  measurements or runs, so a source with data cannot be deleted by accident.
  Predictions use `ON DELETE CASCADE` because they only make sense with their run.
- `forecast_runs` and `forecast_predictions` are empty until Task 4 produces real
  results. No fake metrics or predictions are inserted. That is why there is
  no `seed.sql`.

## Create the schema

From the repository root:

```bash
mysql -u <user> -p < sql/schema.sql
```

The script only uses `CREATE ... IF NOT EXISTS`. It never drops or deletes anything.

## Render the ERD

`erd.png` has not been generated yet because the Mermaid CLI is not installed
here. Any one of these produces it:

- Paste [erd.mmd](erd.mmd) into <https://mermaid.live> and export the PNG.
- Or run: `npx -p @mermaid-js/mermaid-cli mmdc -i sql/erd.mmd -o sql/erd.png`
  (this downloads a headless Chromium).
