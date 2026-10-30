"""HTTP client for the Task 3 API, which serves the same readings from MySQL and MongoDB."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx

ENVELOPE_KEYS = ("readings", "data", "records", "items", "results")
SOURCES = ("sql", "mongo")
# The Task 3 API rejects limits above 20,000 (src/api/validation.py).
PAGE_SIZE = 20_000


class APIError(RuntimeError):
    pass


class ReadingsClient:
    """Reads power readings through the API routes defined in docs/INTEGRATION_CONTRACT.md.

    `http` lets tests inject a client that calls the Flask app directly instead of a real server.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:5000",
        source: str = "sql",
        http: httpx.Client | None = None,
        timeout: float = 30.0,
        latest_path: str = "/{source}/readings/latest",
        range_path: str = "/{source}/readings",
    ):
        if source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
        self.base_url = base_url.rstrip("/")
        self.source = source
        self._owns_http = http is None
        self.http = http or httpx.Client(base_url=self.base_url, timeout=timeout)
        self.latest_path = latest_path.format(source=source)
        self.range_path = range_path.format(source=source)

    def close(self) -> None:
        if self._owns_http:
            self.http.close()

    def __enter__(self) -> ReadingsClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def latest(self) -> list[dict]:
        records = _unwrap(self._get(self.latest_path))
        if not records:
            raise APIError(f"{self.latest_path} returned no record; is the {self.source} database empty?")
        return records

    def by_range(self, start: datetime, end: datetime, page_size: int = PAGE_SIZE) -> list[dict]:
        """All readings in the range, fetched in pages because the API caps `limit`."""
        records: list[dict] = []
        seen: set[str] = set()
        while True:
            params = {
                "start_date": start.isoformat(timespec="seconds"),
                "end_date": end.isoformat(timespec="seconds"),
                "limit": page_size,
            }
            page = _unwrap(self._get(self.range_path, params))
            new = [r for r in page if _record_key(r) not in seen]
            seen.update(map(_record_key, new))
            records.extend(new)
            if len(page) < page_size:
                return records
            # Restart at the last timestamp, not after it, since other readings may share it;
            # if the page ended where it started, step past it so paging always moves forward.
            last = _record_time(page[-1])
            start = last if last > start else last + timedelta(seconds=1)

    def _get(self, path: str, params: dict | None = None):
        try:
            response = self.http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise APIError(f"Could not reach the API at {self.base_url}{path} ({exc}). Is it running?") from exc
        if response.status_code >= 400:
            raise APIError(f"GET {path} failed with {response.status_code}: {response.text[:300]}")
        try:
            return response.json()
        except ValueError as exc:
            raise APIError(f"GET {path} did not return JSON: {response.text[:300]}") from exc


def _record_time(record: dict) -> datetime:
    from src.prediction.preprocessing import records_to_frame

    return records_to_frame([record], target=None)["timestamp"].iloc[0].to_pydatetime()


def _record_key(record: dict) -> str:
    return json.dumps(record, sort_keys=True, default=str)


def _unwrap(body) -> list[dict]:
    """Accepts a bare list, a single record, or a list wrapped in a common envelope key."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ENVELOPE_KEYS:
            if key in body:
                inner = body[key]
                return inner if isinstance(inner, list) else [inner]
        return [body]
    raise APIError(f"Unexpected response shape: {type(body).__name__}")
