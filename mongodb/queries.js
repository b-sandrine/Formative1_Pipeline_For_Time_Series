// Task 2: example MongoDB queries on the energy_consumption database.
//
// Run from the repository root:
//   mongosh --quiet energy_consumption --file mongodb/queries.js
//
// Date ranges are half-open, like the MySQL queries: start INCLUSIVE,
// end EXCLUSIVE ($gte start, $lt end). Timestamps are the local times from
// the file stored as UTC Dates (see collection_design.md), so the dates below
// are written with "Z" but mean the same clock time as the MySQL queries.

// Print rows as "col | col | col" so the output can be compared with MySQL.
function printTable(title, rows) {
  print("\n=== " + title + " ===");
  if (rows.length === 0) { print("(no rows)"); return; }
  print(Object.keys(rows[0]).join(" | "));
  rows.forEach(row => print(Object.values(row).join(" | ")));
}

// "2006-12-16T17:24:00.000Z" -> "2006-12-16 17:24:00"
function formatTime(date) {
  return date.toISOString().slice(0, 19).replace("T", " ");
}

// Show numbers with 3 decimals like the MySQL DECIMAL(8,3) columns; null stays NULL.
function fixed3(value) {
  return value === null ? "NULL" : value.toFixed(3);
}

// Query 1: the 10 most recent measurements.
printTable("Query 1: latest 10 measurements",
  db.energy_readings.find().sort({ timestamp: -1 }).limit(10).toArray().map(d => ({
    measured_at: formatTime(d.timestamp),
    global_active_power: fixed3(d.measurements.global_active_power),
    global_reactive_power: fixed3(d.measurements.global_reactive_power),
    voltage: fixed3(d.measurements.voltage),
    global_intensity: fixed3(d.measurements.global_intensity),
    sub_metering_1: fixed3(d.measurements.sub_metering_1),
    sub_metering_2: fixed3(d.measurements.sub_metering_2),
    sub_metering_3: fixed3(d.measurements.sub_metering_3),
  })));

// Query 2: measurements from 2007-01-01 00:00 (inclusive) to 00:10 (exclusive).
printTable("Query 2: date range 2007-01-01 00:00:00 <= t < 00:10:00",
  db.energy_readings.find({
    timestamp: { $gte: new Date("2007-01-01T00:00:00Z"), $lt: new Date("2007-01-01T00:10:00Z") },
  }).sort({ timestamp: 1 }).toArray().map(d => ({
    measured_at: formatTime(d.timestamp),
    global_active_power: fixed3(d.measurements.global_active_power),
    voltage: fixed3(d.measurements.voltage),
    global_intensity: fixed3(d.measurements.global_intensity),
  })));

// Query 3: average global active power per month.
// $avg ignores null, so missing readings are not counted as zero.
// valid_readings counts only the readings that have a value.
printTable("Query 3: average global active power per month",
  db.energy_readings.aggregate([
    { $group: {
        _id: { $dateToString: { format: "%Y-%m", date: "$timestamp" } },
        valid_readings: { $sum: { $cond: [{ $ne: ["$measurements.global_active_power", null] }, 1, 0] } },
        avg_active_power_kw: { $avg: "$measurements.global_active_power" },
    } },
    { $sort: { _id: 1 } },
  ]).toArray().map(d => ({
    month: d._id,
    valid_readings: d.valid_readings,
    avg_active_power_kw: fixed3(d.avg_active_power_kw),
  })));

// Query 4: readings per source ($lookup joins the source document).
printTable("Query 4: measurements per source",
  db.energy_readings.aggregate([
    { $group: { _id: "$source_id", measurements: { $sum: 1 },
                first_reading: { $min: "$timestamp" }, last_reading: { $max: "$timestamp" } } },
    { $lookup: { from: "dataset_sources", localField: "_id", foreignField: "_id", as: "source" } },
    { $unwind: "$source" },
  ]).toArray().map(d => ({
    name: d.source.name,
    original_filename: d.source.original_filename,
    measurements: d.measurements,
    first_reading: formatTime(d.first_reading),
    last_reading: formatTime(d.last_reading),
  })));

// Query 5: data quality - minutes with missing data, per year.
// A reading counts as missing when global_active_power is null (all seven
// values are missing together in this dataset).
printTable("Query 5: missing data per year",
  db.energy_readings.aggregate([
    { $group: {
        _id: { $year: "$timestamp" },
        total_minutes: { $sum: 1 },
        missing_minutes: { $sum: { $cond: [{ $eq: ["$measurements.global_active_power", null] }, 1, 0] } },
    } },
    { $sort: { _id: 1 } },
  ]).toArray().map(d => ({
    year: d._id,
    total_minutes: d.total_minutes,
    missing_minutes: d.missing_minutes,
    missing_percent: (100 * d.missing_minutes / d.total_minutes).toFixed(2),
  })));
