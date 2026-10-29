"""Import the household power dataset into MySQL.

Run from the repository root, after running sql/schema.sql:
    python scripts/import_mysql.py
    python scripts/import_mysql.py --max-rows 1000      # small test import

Rerunning is safe: rows whose (source, timestamp) already exist are skipped.
Nothing is ever deleted.
"""
import argparse
import sys
import time
from pathlib import Path

# Lets "from src..." work when this file is run as a script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.config import get_dataset_path
from src.database.dataset_reader import MEASUREMENT_COLUMNS, read_dataset
from src.database.mysql_db import get_connection
from src.database.repositories import get_or_create_source, insert_measurements

MAX_REJECTS_SHOWN = 10


def parse_arguments():
    parser = argparse.ArgumentParser(description="Import the dataset into MySQL.")
    parser.add_argument("--path", type=Path, default=None, help="dataset file (default: DATASET_PATH or dataset/household_power_consumption.txt)")
    parser.add_argument("--max-rows", type=int, default=None, help="only import the first N data lines (for testing)")
    parser.add_argument("--batch-size", type=int, default=5000, help="rows per insert (default 5000)")
    return parser.parse_args()


def main():
    args = parse_arguments()
    dataset_path = args.path or get_dataset_path()
    if not dataset_path.exists():
        sys.exit(f"Dataset not found: {dataset_path}")

    try:
        connection = get_connection()
    except RuntimeError as error:
        sys.exit(f"ERROR: {error}")

    processed = inserted = rejected = 0
    rows_with_missing = missing_values = 0
    rejects = []
    batch = []
    started = time.time()

    try:
        source_id = get_or_create_source(connection, dataset_path.name)
        print(f"Dataset: {dataset_path}")
        print(f"Source id: {source_id}")

        for line_number, record, error in read_dataset(dataset_path, args.max_rows):
            processed += 1
            if error is not None:
                rejected += 1
                if len(rejects) < MAX_REJECTS_SHOWN:
                    rejects.append((line_number, error))
                continue

            missing_in_row = sum(1 for column in MEASUREMENT_COLUMNS if record[column] is None)
            if missing_in_row:
                rows_with_missing += 1
                missing_values += missing_in_row

            batch.append(record)
            if len(batch) >= args.batch_size:
                inserted += insert_measurements(connection, source_id, batch)
                batch = []
                print(f"  processed {processed:,} rows", end="\r")

        if batch:
            inserted += insert_measurements(connection, source_id, batch)
    except Exception as error:
        connection.rollback()
        print(f"\nERROR after {processed:,} rows: {error}")
        print("Batches already committed stay in the database; rerun to continue (duplicates are skipped).")
        sys.exit(1)
    finally:
        connection.close()

    valid = processed - rejected
    print(f"\nRows processed:           {processed:,}")
    print(f"Rows inserted (new):      {inserted:,}")
    print(f"Rows skipped (existing):  {valid - inserted:,}")
    print(f"Rows rejected (invalid):  {rejected:,}")
    print(f"Rows with missing values: {rows_with_missing:,} (stored with NULL)")
    print(f"Missing values total:     {missing_values:,}")
    print(f"Time taken:               {time.time() - started:.1f} s")
    for line_number, reason in rejects:
        print(f"  rejected data line {line_number}: {reason}")
    if rejected > len(rejects):
        print(f"  ... and {rejected - len(rejects):,} more rejected rows")


if __name__ == "__main__":
    main()
