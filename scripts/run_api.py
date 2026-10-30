"""Start the Task 3 API.

Run from the repository root:
    python scripts/run_api.py

Then open http://127.0.0.1:5000/ . The port can be changed with API_PORT in .env.
"""
import os
import sys
from pathlib import Path

# Lets "from src..." work when this file is run as a script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Importing the app also imports src.database.config, which loads .env.
from src.api.app import create_app  # noqa: E402


def main():
    try:
        port = int(os.getenv("API_PORT", "5000"))
    except ValueError:
        sys.exit("API_PORT must be a whole number")
    host = "127.0.0.1"
    print(f"API running at http://{host}:{port}")
    print(f"  latest SQL reading:   http://{host}:{port}/sql/readings/latest")
    print(f"  latest Mongo reading: http://{host}:{port}/mongo/readings/latest")
    print("Press Ctrl+C to stop.")
    # debug=False so the reloader does not start a second process.
    create_app().run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
