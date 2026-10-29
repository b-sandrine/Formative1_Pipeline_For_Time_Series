# MySQL query results

These are the real results of running [queries.sql](queries.sql) against the
imported dataset (2,075,259 rows in `energy_measurements`).

**Environment:** MySQL 26.10.0 (Homebrew, macOS), database `energy_consumption`,
loaded with `scripts/import_mysql.py` from `dataset/household_power_consumption.txt`.
Command: `mysql -u root --table < sql/queries.sql`.

**Date ranges** are half-open: start inclusive, end exclusive.
**Time zone:** timestamps are the local times from the file, with no conversion.

---

## Query 1: Latest 10 measurements

Purpose: show the most recent readings (newest first).

```text
+---------------------+---------------------+-----------------------+---------+------------------+----------------+----------------+----------------+
| measured_at         | global_active_power | global_reactive_power | voltage | global_intensity | sub_metering_1 | sub_metering_2 | sub_metering_3 |
+---------------------+---------------------+-----------------------+---------+------------------+----------------+----------------+----------------+
| 2010-11-26 21:02:00 |               0.932 |                 0.000 | 239.550 |            3.800 |          0.000 |          0.000 |          0.000 |
| 2010-11-26 21:01:00 |               0.934 |                 0.000 | 239.700 |            3.800 |          0.000 |          0.000 |          0.000 |
| 2010-11-26 21:00:00 |               0.938 |                 0.000 | 239.820 |            3.800 |          0.000 |          0.000 |          0.000 |
| 2010-11-26 20:59:00 |               0.944 |                 0.000 | 240.000 |            4.000 |          0.000 |          0.000 |          0.000 |
| 2010-11-26 20:58:00 |               0.946 |                 0.000 | 240.430 |            4.000 |          0.000 |          0.000 |          0.000 |
| 2010-11-26 20:57:00 |               0.946 |                 0.000 | 240.330 |            4.000 |          0.000 |          0.000 |          0.000 |
| 2010-11-26 20:56:00 |               0.942 |                 0.000 | 239.410 |            4.000 |          0.000 |          0.000 |          0.000 |
| 2010-11-26 20:55:00 |               0.946 |                 0.000 | 239.740 |            4.000 |          0.000 |          0.000 |          0.000 |
| 2010-11-26 20:54:00 |               0.946 |                 0.000 | 239.310 |            4.000 |          0.000 |          0.000 |          0.000 |
| 2010-11-26 20:53:00 |               0.944 |                 0.000 | 238.720 |            4.000 |          0.000 |          0.000 |          0.000 |
+---------------------+---------------------+-----------------------+---------+------------------+----------------+----------------+----------------+
```

Interpretation: the dataset ends at 2010-11-26 21:02:00. Active power is under
1 kW and all three sub-meters read 0 at the end of the data.

---

## Query 2: Date-range filter

Purpose: readings from 2007-01-01 00:00:00 (inclusive) up to 2007-01-01 00:10:00 (exclusive).

```text
+---------------------+---------------------+---------+------------------+
| measured_at         | global_active_power | voltage | global_intensity |
+---------------------+---------------------+---------+------------------+
| 2007-01-01 00:00:00 |               2.580 | 241.970 |           10.600 |
| 2007-01-01 00:01:00 |               2.552 | 241.750 |           10.400 |
| 2007-01-01 00:02:00 |               2.550 | 241.640 |           10.400 |
| 2007-01-01 00:03:00 |               2.550 | 241.710 |           10.400 |
| 2007-01-01 00:04:00 |               2.554 | 241.980 |           10.400 |
| 2007-01-01 00:05:00 |               2.550 | 241.830 |           10.400 |
| 2007-01-01 00:06:00 |               2.534 | 241.070 |           10.400 |
| 2007-01-01 00:07:00 |               2.484 | 241.290 |           10.200 |
| 2007-01-01 00:08:00 |               2.468 | 241.230 |           10.200 |
| 2007-01-01 00:09:00 |               2.486 | 242.180 |           10.200 |
+---------------------+---------------------+---------+------------------+
```

Interpretation: 10 rows come back, for minutes 00:00 to 00:09. The 00:10 reading
is excluded because the end bound is exclusive.

---

## Query 3: Average global active power per month

Purpose: look at the monthly trend. `AVG()` ignores `NULL`, so missing readings
are not counted as zero; `valid_readings` shows how many readings each average uses.

```text
+---------+----------------+---------------------+
| month   | valid_readings | avg_active_power_kw |
+---------+----------------+---------------------+
| 2006-12 |          21992 |               1.901 |
| 2007-01 |          44638 |               1.546 |
| 2007-02 |          40318 |               1.401 |
| 2007-03 |          44639 |               1.319 |
| 2007-04 |          39477 |               0.891 |
| 2007-05 |          44640 |               0.986 |
| 2007-06 |          43157 |               0.827 |
| 2007-07 |          44509 |               0.667 |
| 2007-08 |          44618 |               0.764 |
| 2007-09 |          43198 |               0.969 |
| 2007-10 |          44638 |               1.104 |
| 2007-11 |          43198 |               1.294 |
| 2007-12 |          44639 |               1.626 |
| 2008-01 |          44639 |               1.460 |
| 2008-02 |          41757 |               1.181 |
| 2008-03 |          44639 |               1.245 |
| 2008-04 |          43200 |               1.116 |
| 2008-05 |          44638 |               1.024 |
| 2008-06 |          43199 |               0.994 |
| 2008-07 |          44638 |               0.795 |
| 2008-08 |          44638 |               0.276 |
| 2008-09 |          43200 |               0.988 |
| 2008-10 |          44597 |               1.137 |
| 2008-11 |          43191 |               1.387 |
| 2008-12 |          44569 |               1.275 |
| 2009-01 |          44639 |               1.410 |
| 2009-02 |          40256 |               1.248 |
| 2009-03 |          44638 |               1.227 |
| 2009-04 |          43198 |               1.141 |
| 2009-05 |          44636 |               1.013 |
| 2009-06 |          39895 |               0.841 |
| 2009-07 |          44636 |               0.618 |
| 2009-08 |          43749 |               0.665 |
| 2009-09 |          43197 |               0.987 |
| 2009-10 |          44639 |               1.144 |
| 2009-11 |          43199 |               1.275 |
| 2009-12 |          44638 |               1.364 |
| 2010-01 |          41509 |               1.431 |
| 2010-02 |          40318 |               1.376 |
| 2010-03 |          42613 |               1.130 |
| 2010-04 |          43199 |               1.027 |
| 2010-05 |          44639 |               1.095 |
| 2010-06 |          43198 |               0.970 |
| 2010-07 |          44639 |               0.721 |
| 2010-08 |          37414 |               0.591 |
| 2010-09 |          37963 |               0.956 |
| 2010-10 |          44639 |               1.163 |
| 2010-11 |          37263 |               1.197 |
+---------+----------------+---------------------+
```

Interpretation: consumption is higher in winter (for example 1.901 kW in
2006-12 and 1.626 kW in 2007-12) and lower in summer (0.667 kW in 2007-07).
2008-08 is unusually low at 0.276 kW. The data does not say why, so we should
not guess a cause. 2006-12 and 2010-11 cover only part of a month, and months
with fewer valid readings (for example 2010-08) are based on fewer minutes.

---

## Query 4: Measurements per source

Purpose: join `dataset_sources` to `energy_measurements` and summarize each source.

```text
+-----------+--------------------------------------+---------------------------------+--------------+---------------------+---------------------+
| source_id | name                                 | original_filename               | measurements | first_reading       | last_reading        |
+-----------+--------------------------------------+---------------------------------+--------------+---------------------+---------------------+
|         1 | Household Electric Power Consumption | household_power_consumption.txt |      2075259 | 2006-12-16 17:24:00 | 2010-11-26 21:02:00 |
+-----------+--------------------------------------+---------------------------------+--------------+---------------------+---------------------+
```

Interpretation: there is one source, with 2,075,259 measurements. This equals
the number of data lines in the file.

---

## Query 5: Missing data per year

Purpose: data quality check - how many minutes have no measurements.

```text
+------+---------------+-----------------+-----------------+
| year | total_minutes | missing_minutes | missing_percent |
+------+---------------+-----------------+-----------------+
| 2006 |         21996 |               4 |            0.02 |
| 2007 |        525600 |            3931 |            0.75 |
| 2008 |        527040 |             135 |            0.03 |
| 2009 |        525600 |            4280 |            0.81 |
| 2010 |        475023 |           17629 |            3.71 |
+------+---------------+-----------------+-----------------+
```

Interpretation: 25,979 minutes are missing in total (4 + 3,931 + 135 + 4,280 +
17,629), which matches the 25,979 lines containing `?` in the file. 2010 has the
most gaps (3.71%). These rows were kept with `NULL` values, so the gaps are
visible in the time series and the averages above are not distorted.

---

## Limitations

- Results come from one local MySQL instance and one dataset file.
- Query 5 treats a row as missing when `global_active_power` is `NULL`. This is
  correct for this file because all measurement columns are missing together
  (181,853 missing values = 25,979 rows x 7 columns).
- The tables `forecast_runs` and `forecast_predictions` are empty, because no
  forecasting model has been run yet, so no query on them is included.
