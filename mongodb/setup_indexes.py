"""Create the MongoDB indexes described in mongodb/collection_design.md.

Run from the repository root:
    python mongodb/setup_indexes.py

Safe to run any number of times: existing indexes are left as they are.
(scripts/import_mongodb.py also does this before importing.)
"""
import sys
from pathlib import Path

# Lets "from src..." work when this file is run as a script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.mongo_db import create_indexes, get_database


def main():
    try:
        database = get_database()
    except RuntimeError as error:
        sys.exit(f"ERROR: {error}")

    create_indexes(database)

    print(f"Indexes in database '{database.name}':")
    for collection_name in ("dataset_sources", "energy_readings", "forecast_results"):
        for index in database[collection_name].list_indexes():
            unique = " (unique)" if index.get("unique") else ""
            print(f"  {collection_name}: {index['name']}{unique}")


if __name__ == "__main__":
    main()
