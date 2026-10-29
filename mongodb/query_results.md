# MongoDB query results

These are the real results of running [queries.js](queries.js) against the
imported dataset (2,075,259 documents in `energy_readings`).

**Environment:** MongoDB 8.0.34 (Homebrew, macOS), database `energy_consumption`,
loaded with `scripts/import_mongodb.py` from `dataset/household_power_consumption.txt`.
Command: `mongosh --quiet energy_consumption --file mongodb/queries.js`.

**Comparison with MySQL:** the queries use the same business meaning and the
same date bounds as [../sql/queries.sql](../sql/queries.sql) (start inclusive,
end exclusive). I compared the two outputs row by row with a script: Queries 1,
2, 3 and 5 are identical to the MySQL results. Query 4 has the same values;
only the MySQL output also shows the integer `source_id` column.
**Time zone:** timestamps are the local times from the file, stored as UTC
Dates (see [collection_design.md](collection_design.md)), so no conversion is applied.

---

## Query 1: Latest 10 measurements

```js
db.energy_readings.find().sort({ timestamp: -1 }).limit(10)
```

Purpose: the most recent readings, newest first.

```text
measured_at | global_active_power | global_reactive_power | voltage | global_intensity | sub_metering_1 | sub_metering_2 | sub_metering_3
2010-11-26 21:02:00 | 0.932 | 0.000 | 239.550 | 3.800 | 0.000 | 0.000 | 0.000
2010-11-26 21:01:00 | 0.934 | 0.000 | 239.700 | 3.800 | 0.000 | 0.000 | 0.000
2010-11-26 21:00:00 | 0.938 | 0.000 | 239.820 | 3.800 | 0.000 | 0.000 | 0.000
2010-11-26 20:59:00 | 0.944 | 0.000 | 240.000 | 4.000 | 0.000 | 0.000 | 0.000
2010-11-26 20:58:00 | 0.946 | 0.000 | 240.430 | 4.000 | 0.000 | 0.000 | 0.000
2010-11-26 20:57:00 | 0.946 | 0.000 | 240.330 | 4.000 | 0.000 | 0.000 | 0.000
2010-11-26 20:56:00 | 0.942 | 0.000 | 239.410 | 4.000 | 0.000 | 0.000 | 0.000
2010-11-26 20:55:00 | 0.946 | 0.000 | 239.740 | 4.000 | 0.000 | 0.000 | 0.000
2010-11-26 20:54:00 | 0.946 | 0.000 | 239.310 | 4.000 | 0.000 | 0.000 | 0.000
2010-11-26 20:53:00 | 0.944 | 0.000 | 238.720 | 4.000 | 0.000 | 0.000 | 0.000
```

Interpretation: the data ends at 2010-11-26 21:02:00, with active power under 1 kW.

---

## Query 2: Date-range filter

```js
db.energy_readings.find({ timestamp: { $gte: new Date("2007-01-01T00:00:00Z"),
                                        $lt:  new Date("2007-01-01T00:10:00Z") } })
```

Purpose: readings from 2007-01-01 00:00:00 (inclusive) up to 00:10:00 (exclusive).

```text
measured_at | global_active_power | voltage | global_intensity
2007-01-01 00:00:00 | 2.580 | 241.970 | 10.600
2007-01-01 00:01:00 | 2.552 | 241.750 | 10.400
2007-01-01 00:02:00 | 2.550 | 241.640 | 10.400
2007-01-01 00:03:00 | 2.550 | 241.710 | 10.400
2007-01-01 00:04:00 | 2.554 | 241.980 | 10.400
2007-01-01 00:05:00 | 2.550 | 241.830 | 10.400
2007-01-01 00:06:00 | 2.534 | 241.070 | 10.400
2007-01-01 00:07:00 | 2.484 | 241.290 | 10.200
2007-01-01 00:08:00 | 2.468 | 241.230 | 10.200
2007-01-01 00:09:00 | 2.486 | 242.180 | 10.200
```

Interpretation: 10 readings (00:00 to 00:09). The 00:10 reading is excluded
because `$lt` is exclusive.

---

## Query 3: Average global active power per month

```js
db.energy_readings.aggregate([
  { $group: { _id: { $dateToString: { format: "%Y-%m", date: "$timestamp" } },
              valid_readings: { $sum: { $cond: [{ $ne: ["$measurements.global_active_power", null] }, 1, 0] } },
              avg_active_power_kw: { $avg: "$measurements.global_active_power" } } },
  { $sort: { _id: 1 } } ])
```

Purpose: the monthly trend. `$avg` ignores `null`, so missing readings are not
counted as zero. `valid_readings` is the number of readings behind each average.

```text
month | valid_readings | avg_active_power_kw
2006-12 | 21992 | 1.901
2007-01 | 44638 | 1.546
2007-02 | 40318 | 1.401
2007-03 | 44639 | 1.319
2007-04 | 39477 | 0.891
2007-05 | 44640 | 0.986
2007-06 | 43157 | 0.827
2007-07 | 44509 | 0.667
2007-08 | 44618 | 0.764
2007-09 | 43198 | 0.969
2007-10 | 44638 | 1.104
2007-11 | 43198 | 1.294
2007-12 | 44639 | 1.626
2008-01 | 44639 | 1.460
2008-02 | 41757 | 1.181
2008-03 | 44639 | 1.245
2008-04 | 43200 | 1.116
2008-05 | 44638 | 1.024
2008-06 | 43199 | 0.994
2008-07 | 44638 | 0.795
2008-08 | 44638 | 0.276
2008-09 | 43200 | 0.988
2008-10 | 44597 | 1.137
2008-11 | 43191 | 1.387
2008-12 | 44569 | 1.275
2009-01 | 44639 | 1.410
2009-02 | 40256 | 1.248
2009-03 | 44638 | 1.227
2009-04 | 43198 | 1.141
2009-05 | 44636 | 1.013
2009-06 | 39895 | 0.841
2009-07 | 44636 | 0.618
2009-08 | 43749 | 0.665
2009-09 | 43197 | 0.987
2009-10 | 44639 | 1.144
2009-11 | 43199 | 1.275
2009-12 | 44638 | 1.364
2010-01 | 41509 | 1.431
2010-02 | 40318 | 1.376
2010-03 | 42613 | 1.130
2010-04 | 43199 | 1.027
2010-05 | 44639 | 1.095
2010-06 | 43198 | 0.970
2010-07 | 44639 | 0.721
2010-08 | 37414 | 0.591
2010-09 | 37963 | 0.956
2010-10 | 44639 | 1.163
2010-11 | 37263 | 1.197
```

Interpretation: same pattern as MySQL - higher in winter (1.901 kW in 2006-12),
lower in summer (0.667 kW in 2007-07), and an unusually low 0.276 kW in 2008-08
for which the data gives no reason. 2006-12 and 2010-11 are partial months.

---

## Query 4: Measurements per source

Purpose: group readings by `source_id` and use `$lookup` (the MongoDB join) to
get the source name and filename.

```text
name | original_filename | measurements | first_reading | last_reading
Household Electric Power Consumption | household_power_consumption.txt | 2075259 | 2006-12-16 17:24:00 | 2010-11-26 21:02:00
```

Interpretation: one source with 2,075,259 readings, equal to the number of data lines in the file.

---

## Query 5: Missing data per year

Purpose: data quality - readings where the values are `null`.

```text
year | total_minutes | missing_minutes | missing_percent
2006 | 21996 | 4 | 0.02
2007 | 525600 | 3931 | 0.75
2008 | 527040 | 135 | 0.03
2009 | 525600 | 4280 | 0.81
2010 | 475023 | 17629 | 3.71
```

Interpretation: 25,979 readings are missing in total (4 + 3,931 + 135 + 4,280 +
17,629), matching the file and MySQL. 2010 has the most gaps (3.71%).

---

## Index use

I ran `explain("executionStats")` on Queries 1 and 2. Both used an index scan
(`IXSCAN`) on `timestamp_1`, with 10 keys and 10 documents examined, so
neither scanned the whole collection. MongoDB's planner chose `timestamp_1`
rather than the compound `source_id_1_timestamp_1` index because these queries
do not filter by source.

## Limitations

- Results come from one local MongoDB instance and one dataset file.
- Query 5 treats a reading as missing when `global_active_power` is `null`;
  all seven values are missing together in this dataset.
- `forecast_results` is empty because no forecasting model has been run yet,
  so no query on it is included.
- I did not benchmark MongoDB against MySQL, so no speed comparison is claimed.
