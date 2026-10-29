"""Connection settings, read from environment variables (and a local .env file)."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_PATH = PROJECT_ROOT / "dataset" / "household_power_consumption.txt"

# Reads PROJECT_ROOT/.env if it exists. Variables already set in the
# shell are not overwritten.
load_dotenv(PROJECT_ROOT / ".env")


def get_mysql_config() -> dict:
    """Return the arguments for mysql.connector.connect()."""
    return {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "database": os.getenv("MYSQL_DATABASE", "energy_consumption"),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
    }


def get_dataset_path() -> Path:
    """Dataset location: DATASET_PATH if set, otherwise dataset/household_power_consumption.txt."""
    return Path(os.getenv("DATASET_PATH", DEFAULT_DATASET_PATH))


def get_mongo_config() -> dict:
    """Return the MongoDB connection string and database name."""
    return {
        "uri": os.getenv("MONGODB_URI", "mongodb://localhost:27017/"),
        "database": os.getenv("MONGODB_DATABASE", "energy_consumption"),
    }
