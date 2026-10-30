"""Errors the API turns into JSON responses."""


class ApiError(Exception):
    """A problem we can explain to the caller (bad input, missing row, and so on)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class DuplicateReadingError(ApiError):
    """The database already has a reading for this source at this minute."""

    def __init__(self):
        super().__init__(
            "A reading already exists for this source at that time",
            409,
        )


class DatabaseError(ApiError):
    """The database rejected the request for a reason other than a duplicate."""

    def __init__(self, message: str):
        super().__init__(message or "The database request failed", 500)
