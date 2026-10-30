"""Integer simulation clock and stable delivery queue; no wall-clock scheduling."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Any, Literal

EventKind = Literal["scalar", "encoder", "rgb"]
_KIND_RANK = {"scalar": 0, "encoder": 1, "rgb": 2}


def _positive_dt(dt_s: float) -> None:
    if (
        isinstance(dt_s, bool)
        or not isinstance(dt_s, (int, float))
        or not math.isfinite(dt_s)
        or dt_s <= 0
    ):
        raise ValueError("clock timestep must be finite and positive")


def _integer_tick(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("clock tick must be a nonnegative integer")


def ticks(seconds: float, dt_s: float, *, rounding: str = "exact") -> int:
    """Durations round up; deadlines round down. Configured periods must be exact."""
    _positive_dt(dt_s)
    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not math.isfinite(seconds)
        or seconds < 0
    ):
        raise ValueError("duration must be finite and nonnegative")
    if rounding not in ("exact", "up", "down"):
        raise ValueError("unknown tick rounding convention")
    value = seconds / dt_s
    nearest = round(value)
    if math.isclose(value, nearest, rel_tol=0, abs_tol=1e-9):
        return nearest
    if rounding == "up":
        return math.ceil(value)
    if rounding == "down":
        return math.floor(value)
    raise ValueError("duration is not on the simulation grid")


@dataclass
class Scheduler:
    dt_s: float
    tick: int = 0
    _serial: int = 0
    _queue: list[tuple[int, int, int, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        _positive_dt(self.dt_s)
        _integer_tick(self.tick)

    @property
    def time_s(self) -> float:
        return self.tick * self.dt_s

    def enqueue(
        self, delivery_tick: int, immutable_sample: Any, *, event_kind: EventKind = "scalar"
    ) -> None:
        """Order by delivery tick, scalar/encoder/RGB kind, then insertion serial.

        The trusted caller supplies a frozen captured value. Zero-latency events
        may be enqueued at the current tick; events in the past are invalid.
        """
        _integer_tick(delivery_tick)
        if event_kind not in _KIND_RANK:
            raise ValueError("unknown delivery event kind")
        if delivery_tick < self.tick:
            raise ValueError("cannot schedule delivery in the past")
        self._serial += 1
        heapq.heappush(
            self._queue, (delivery_tick, _KIND_RANK[event_kind], self._serial, immutable_sample)
        )

    def deliver(self) -> tuple[Any, ...]:
        ready = []
        while self._queue and self._queue[0][0] <= self.tick:
            ready.append(heapq.heappop(self._queue)[3])
        return tuple(ready)
