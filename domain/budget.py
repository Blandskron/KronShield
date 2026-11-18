"""Process-local counters and admission for one audit job."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from threading import Lock
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field


class BudgetLimits(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", hide_input_in_errors=True)

    max_operations: int = Field(default=30, ge=1, le=10_000)
    max_bytes: int = Field(default=4 * 1024 * 1024, ge=1, le=64 * 1024 * 1024)
    max_response_bytes: int = Field(default=256 * 1024, ge=1, le=64 * 1024 * 1024)
    max_seconds: float = Field(default=120.0, gt=0, le=3600)
    operations_per_second: float = Field(default=1.0, gt=0, le=100)
    burst: int = Field(default=1, ge=1, le=100)
    max_concurrent: int = Field(default=2, ge=1, le=32)


class BudgetReason(str, Enum):
    DEADLINE = "deadline"
    OPERATIONS = "operations"
    BYTES = "bytes"
    RATE = "rate"
    CONCURRENCY = "concurrency"


class BudgetExceeded(Exception):
    def __init__(self, reason: BudgetReason):
        super().__init__(f"execution_budget_{reason.value}")
        self.reason = reason


@dataclass(frozen=True)
class BudgetUsage:
    operations: int
    bytes: int


class ExecutionBudget:
    def __init__(self, limits: BudgetLimits, *, clock: Callable[[], float] = monotonic):
        self._limits = limits
        self._clock = clock
        self._last_refill = clock()
        self._deadline = self._last_refill + limits.max_seconds
        self._tokens = float(limits.burst)
        self._active = 0
        self._operations = 0
        self._bytes = 0
        self._lock = Lock()

    @property
    def limits(self) -> BudgetLimits:
        return self._limits

    def usage(self) -> BudgetUsage:
        with self._lock:
            return BudgetUsage(self._operations, self._bytes)

    def _remaining_at(self, now: float) -> float:
        time_left = self._deadline - now
        if time_left <= 0:
            raise BudgetExceeded(BudgetReason.DEADLINE)
        return time_left

    def remaining_seconds(self) -> float:
        return self._remaining_at(self._clock())

    @contextmanager
    def operation(self) -> Iterator[None]:
        """Admit one user-facing HTTP/TCP operation, including its DNS."""
        with self._lock:
            now = self._clock()
            self._remaining_at(now)
            self._check_attempt()
            self._check_bytes(1)
            if self._active >= self.limits.max_concurrent:
                raise BudgetExceeded(BudgetReason.CONCURRENCY)
            self._tokens = min(
                self.limits.burst, self._tokens + (now - self._last_refill) * self.limits.operations_per_second,
            )
            self._last_refill = now
            if self._tokens < 1:
                raise BudgetExceeded(BudgetReason.RATE)
            self._tokens -= 1
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1

    def _check_attempt(self) -> None:
        if self._operations >= self.limits.max_operations:
            raise BudgetExceeded(BudgetReason.OPERATIONS)

    def charge_attempt(self) -> None:
        """Debit a DNS exchange or target connection before opening it."""
        with self._lock:
            self.remaining_seconds()
            self._check_attempt()
            self._check_bytes(1)
            self._operations += 1

    def _check_bytes(self, amount: int) -> None:
        if type(amount) is not int or amount < 0:
            raise ValueError("Expected a nonnegative byte count")
        if self._bytes + amount > self.limits.max_bytes:
            raise BudgetExceeded(BudgetReason.BYTES)

    def require_bytes(self, amount: int) -> None:
        with self._lock:
            self.remaining_seconds()
            self._check_bytes(amount)

    def charge_write(self, amount: int) -> None:
        with self._lock:
            self.remaining_seconds()
            self._check_bytes(amount)
            self._bytes += amount

    def read(self, maximum: int, receive: Callable[[int], int]) -> int:
        """Reserve before reading and refund bytes known to be unused."""
        if type(maximum) is not int or maximum <= 0:
            raise ValueError("Expected a positive read size")
        with self._lock:
            self.remaining_seconds()
            allowance = min(maximum, self.limits.max_bytes - self._bytes)
            if allowance <= 0:
                raise BudgetExceeded(BudgetReason.BYTES)
            self._bytes += allowance
        count = receive(allowance)
        if type(count) is not int or not 0 <= count <= allowance:
            raise ValueError("Read returned an invalid byte count")
        with self._lock:
            self._bytes -= allowance - count
        return count
