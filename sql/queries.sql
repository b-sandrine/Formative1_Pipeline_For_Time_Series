-- Task 2: example queries on the energy_consumption database.
--
-- Run from the repository root:
--   mysql -u <user> -p --table < sql/queries.sql
--
-- Date ranges use a half-open window: start INCLUSIVE, end EXCLUSIVE
-- (measured_at >= start AND measured_at < end). This avoids double
-- counting a boundary minute and is used the same way in the MongoDB queries.

USE energy_consumption;

-- Query 1: the 10 most recent measurements.
SELECT measured_at, global_active_power, global_reactive_power, voltage,
       global_intensity, sub_metering_1, sub_metering_2, sub_metering_3
FROM energy_measurements
ORDER BY measured_at DESC
LIMIT 10;

-- Query 2: measurements in a date range (2007-01-01 00:00 up to, but not
-- including, 2007-01-01 00:10).
SELECT measured_at, global_active_power, voltage, global_intensity
FROM energy_measurements
WHERE measured_at >= '2007-01-01 00:00:00'
  AND measured_at <  '2007-01-01 00:10:00'
ORDER BY measured_at;

-- Query 3: average global active power per month.
-- AVG() ignores NULL, so missing readings do not count as zero.
SELECT DATE_FORMAT(measured_at, '%Y-%m')   AS month,
       COUNT(global_active_power)          AS valid_readings,
       ROUND(AVG(global_active_power), 3)  AS avg_active_power_kw
FROM energy_measurements
GROUP BY DATE_FORMAT(measured_at, '%Y-%m')
ORDER BY month;

-- Query 4: measurements per source (joins the two tables).
SELECT s.source_id, s.name, s.original_filename,
       COUNT(m.measurement_id) AS measurements,
       MIN(m.measured_at)      AS first_reading,
       MAX(m.measured_at)      AS last_reading
FROM dataset_sources s
LEFT JOIN energy_measurements m ON m.source_id = s.source_id
GROUP BY s.source_id, s.name, s.original_filename;

-- Query 5: data quality - minutes with missing data, per year.
-- A row counts as missing when global_active_power is NULL
-- (in this dataset all measurement columns are missing together).
SELECT YEAR(measured_at)                                  AS year,
       COUNT(*)                                           AS total_minutes,
       SUM(global_active_power IS NULL)                   AS missing_minutes,
       ROUND(100 * AVG(global_active_power IS NULL), 2)   AS missing_percent
FROM energy_measurements
GROUP BY YEAR(measured_at)
ORDER BY year;
