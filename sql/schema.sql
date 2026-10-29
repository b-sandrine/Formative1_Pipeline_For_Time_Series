-- Task 2: MySQL schema for the household electric power consumption dataset.
--
-- Safe to run more than once: it only creates things that do not exist yet
-- and never drops or deletes anything.
--
-- Run from the repository root:
--   mysql -u <user> -p < sql/schema.sql

CREATE DATABASE IF NOT EXISTS energy_consumption
    CHARACTER SET utf8mb4;
USE energy_consumption;

-- Table 1: one row per imported dataset file.
CREATE TABLE IF NOT EXISTS dataset_sources (
    source_id         INT AUTO_INCREMENT PRIMARY KEY,
    name              VARCHAR(100) NOT NULL,
    description       TEXT NULL,
    source_url        VARCHAR(255) NULL,
    original_filename VARCHAR(255) NOT NULL,
    timezone_note     VARCHAR(100) NULL,      -- how to read the timestamps
    imported_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- The importer looks a source up by these two columns, so rerunning it
    -- reuses the existing row instead of creating a second one.
    CONSTRAINT uq_source_name_file UNIQUE (name, original_filename)
);

-- Table 2: one row per one-minute measurement.
-- Measurement columns are NULL when the original file had "?" (missing).
-- We keep the row and store NULL rather than 0, because 0 would look like
-- a real "no consumption" reading and would pull averages down.
-- DECIMAL(8,3) keeps the three decimals used in the original file.
CREATE TABLE IF NOT EXISTS energy_measurements (
    measurement_id        BIGINT AUTO_INCREMENT PRIMARY KEY,
    source_id             INT NOT NULL,
    measured_at           DATETIME NOT NULL,   -- local time, no time zone
    global_active_power   DECIMAL(8,3) NULL,   -- kilowatts
    global_reactive_power DECIMAL(8,3) NULL,   -- kilowatts
    voltage               DECIMAL(8,3) NULL,   -- volts
    global_intensity      DECIMAL(8,3) NULL,   -- amperes
    sub_metering_1        DECIMAL(8,3) NULL,   -- watt-hours (kitchen)
    sub_metering_2        DECIMAL(8,3) NULL,   -- watt-hours (laundry room)
    sub_metering_3        DECIMAL(8,3) NULL,   -- watt-hours (water heater, air conditioner)
    CONSTRAINT fk_measurement_source
        FOREIGN KEY (source_id) REFERENCES dataset_sources (source_id),
    -- One reading per minute per source. This also stops duplicates when
    -- the importer is rerun, and speeds up date-range queries on one source.
    CONSTRAINT uq_measurement_source_time UNIQUE (source_id, measured_at),
    -- For date queries that do not filter by source.
    INDEX idx_measurement_time (measured_at)
);

-- Table 3: one row per forecasting experiment.
-- Metrics are NULL until a real run fills them in.
CREATE TABLE IF NOT EXISTS forecast_runs (
    run_id        INT AUTO_INCREMENT PRIMARY KEY,
    source_id     INT NOT NULL,
    model_name    VARCHAR(100) NOT NULL,
    target_column VARCHAR(50)  NOT NULL,      -- e.g. global_active_power
    run_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    rmse          DOUBLE NULL,
    mae           DOUBLE NULL,
    parameters    JSON NULL,                  -- model settings, free-form
    notes         TEXT NULL,
    CONSTRAINT fk_run_source
        FOREIGN KEY (source_id) REFERENCES dataset_sources (source_id),
    INDEX idx_run_source (source_id)
);

-- Table 4 (optional): the predictions produced by one run.
-- Deleting a run deletes its predictions too (ON DELETE CASCADE),
-- because predictions are meaningless without their run.
CREATE TABLE IF NOT EXISTS forecast_predictions (
    prediction_id   BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id          INT NOT NULL,
    predicted_for   DATETIME NOT NULL,        -- the time being predicted
    predicted_value DECIMAL(10,4) NOT NULL,   -- value of the run's target_column
    CONSTRAINT fk_prediction_run
        FOREIGN KEY (run_id) REFERENCES forecast_runs (run_id)
        ON DELETE CASCADE,
    CONSTRAINT uq_prediction_run_time UNIQUE (run_id, predicted_for)
);
