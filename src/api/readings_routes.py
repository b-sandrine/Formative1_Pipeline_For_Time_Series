"""Reading routes shared by /sql and /mongo.

The URL paths are the same under both prefixes. Only the store changes.
``/readings/latest`` is registered on its own so it is not treated as an id.
"""
from flask import Blueprint, jsonify, request

from src.api.errors import ApiError
from src.api.validation import parse_limit, parse_reading_body, range_bounds

# No date filter: a short page of the newest rows, so a bare GET cannot
# dump the whole multi-million-row table.
RECENT_DEFAULT_LIMIT = 100
# A date range defaults high enough for one day (1440 minutes) and a few
# more days. Callers can raise it with ?limit=, up to parse_limit's maximum.
RANGE_DEFAULT_LIMIT = 5000


def call_store(open_store, action):
    """Run ``action(store)`` and always close the database."""
    try:
        store, close = open_store()
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 503
    try:
        return action(store)
    except ApiError as error:
        return jsonify({"error": error.message}), error.status
    finally:
        close()


def create_readings_blueprint(name: str, open_store, id_converter: str):
    """Build the CRUD and time-series routes for one database.

    ``id_converter`` is ``int`` for MySQL and ``string`` for MongoDB ObjectIds.
    """
    blueprint = Blueprint(name, __name__)
    item_rule = f"/readings/<{id_converter}:measurement_id>"

    def latest():
        def action(store):
            reading = store.latest()
            if reading is None:
                raise ApiError("No readings found", 404)
            return jsonify(reading)

        return call_store(open_store, action)

    def list_readings():
        def action(store):
            start_text = _query_text("start_date")
            end_text = _query_text("end_date")
            if (start_text is None) != (end_text is None):
                raise ApiError("Provide both start_date and end_date, or neither")
            if start_text is None:
                limit = parse_limit(request.args.get("limit"), default=RECENT_DEFAULT_LIMIT)
                readings = store.list_recent(limit)
            else:
                limit = parse_limit(request.args.get("limit"), default=RANGE_DEFAULT_LIMIT)
                start, end = range_bounds(start_text, end_text)
                readings = store.list_range(start, end, limit)
            return jsonify({
                "count": len(readings),
                "limit": limit,
                "may_have_more": len(readings) == limit,
                "readings": readings,
            })

        return call_store(open_store, action)

    def read_one(measurement_id):
        def action(store):
            reading = store.get(measurement_id)
            if reading is None:
                raise ApiError("Reading not found", 404)
            return jsonify(reading)

        return call_store(open_store, action)

    def create_reading():
        def action(store):
            fields = parse_reading_body(request.get_json(silent=True), partial=False)
            return jsonify(store.create(fields)), 201

        return call_store(open_store, action)

    def update_reading(measurement_id):
        def action(store):
            fields = parse_reading_body(request.get_json(silent=True), partial=True)
            reading = store.update(measurement_id, fields)
            if reading is None:
                raise ApiError("Reading not found", 404)
            return jsonify(reading)

        return call_store(open_store, action)

    def delete_reading(measurement_id):
        def action(store):
            if not store.delete(measurement_id):
                raise ApiError("Reading not found", 404)
            return jsonify({"deleted": True, "measurement_id": measurement_id})

        return call_store(open_store, action)

    blueprint.add_url_rule("/readings/latest", view_func=latest, methods=["GET"])
    blueprint.add_url_rule("/readings", view_func=list_readings, methods=["GET"])
    blueprint.add_url_rule(item_rule, view_func=read_one, methods=["GET"])
    blueprint.add_url_rule("/readings", view_func=create_reading, methods=["POST"])
    blueprint.add_url_rule(item_rule, view_func=update_reading, methods=["PUT"])
    blueprint.add_url_rule(item_rule, view_func=delete_reading, methods=["DELETE"])
    return blueprint


def _query_text(name: str):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None
