"""Flask application for Task 3.

Run from the repository root:
    python scripts/run_api.py
"""
from flask import Flask, jsonify

from src.api.connections import open_mongo_store, open_sql_store
from src.api.readings_routes import create_readings_blueprint

_ROUTE_HELP = {
    "sql": {
        "latest": "GET /sql/readings/latest",
        "date_range": "GET /sql/readings?start_date=2007-01-01&end_date=2007-01-01",
        "list_recent": "GET /sql/readings",
        "read_one": "GET /sql/readings/<measurement_id>",
        "create": "POST /sql/readings",
        "update": "PUT /sql/readings/<measurement_id>",
        "delete": "DELETE /sql/readings/<measurement_id>",
    },
    "mongo": {
        "latest": "GET /mongo/readings/latest",
        "date_range": "GET /mongo/readings?start_date=2007-01-01&end_date=2007-01-01",
        "list_recent": "GET /mongo/readings",
        "read_one": "GET /mongo/readings/<measurement_id>",
        "create": "POST /mongo/readings",
        "update": "PUT /mongo/readings/<measurement_id>",
        "delete": "DELETE /mongo/readings/<measurement_id>",
    },
}


def create_app(open_sql=None, open_mongo=None) -> Flask:
    """Build the app. Tests pass fake openers; the real ones talk to the databases."""
    app = Flask(__name__)
    app.json.sort_keys = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(
        create_readings_blueprint("sql", open_sql or open_sql_store, "int"),
        url_prefix="/sql",
    )
    app.register_blueprint(
        create_readings_blueprint("mongo", open_mongo or open_mongo_store, "string"),
        url_prefix="/mongo",
    )

    @app.get("/")
    def index():
        return jsonify({
            "service": "energy-consumption-api",
            "health": "GET /health",
            "routes": _ROUTE_HELP,
        })

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(_error):
        return jsonify({"error": "Method not allowed"}), 405

    return app
