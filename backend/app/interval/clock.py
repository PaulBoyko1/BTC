from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .types import Horizon


@dataclass(frozen=True)
class FixedWindow:
    start_timestamp: int
    expiry_timestamp: int


def floor_fixed_interval(timestamp: int, horizon: Horizon) -> int:
    seconds = horizon.minutes * 60
    return timestamp - (timestamp % seconds)


def current_fixed_window(timestamp: int, horizon: Horizon) -> FixedWindow:
    start = floor_fixed_interval(timestamp, horizon)
    return FixedWindow(start_timestamp=start, expiry_timestamp=start + horizon.minutes * 60)


def next_fixed_expiry(timestamp: int, horizon: Horizon) -> int:
    return current_fixed_window(timestamp, horizon).expiry_timestamp


def utc_iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def is_fixed_boundary(timestamp: int, horizon: Horizon) -> bool:
    return timestamp % (horizon.minutes * 60) == 0
