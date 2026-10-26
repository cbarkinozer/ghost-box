"""Shared local date-range semantics for mail providers."""

from datetime import timedelta
from .errors import AccountError


def time_bounds(first, last):
    """Include the entire displayed end minute; return exclusive UTC epoch bounds."""
    if first > last:
        raise AccountError('From must be on or before To.')
    return int(first.timestamp()), int((last + timedelta(minutes=1)).timestamp())
