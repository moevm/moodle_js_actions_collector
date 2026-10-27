"""A process-local admission budget for MongoDB writes, not a filesystem quota."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol


LOGGER = logging.getLogger(__name__)
CHECK_TIMEOUT_SECONDS = 2.0
MIN_WRITE_BUDGET = 4096
SIZE_UNITS = {
    "B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4,
    "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4,
}


class StorageDatabase(Protocol):
    async def command(self, command: str, **kwargs: Any) -> Mapping[str, Any]: ...


def parse_storage_size(value: str) -> int:
    """Accept bytes or explicit decimal/binary units, without float rounding."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]*)\s*", value)
    if match is None or (unit := match[2].upper() or "B") not in SIZE_UNITS:
        raise ValueError("COLLECTOR_DB_MAX_SIZE must be a positive size, e.g. 100GB or 100GiB")
    size = Decimal(match[1]) * SIZE_UNITS[unit]
    if size != size.to_integral_value() or not 0 < size <= 2**63 - 1:
        raise ValueError("COLLECTOR_DB_MAX_SIZE must be a positive whole number of bytes below 2^63")
    return int(size)


@dataclass(frozen=True, slots=True)
class StorageSettings:
    max_bytes: int = 100_000_000_000
    check_interval_seconds: float = 5.0

    def __post_init__(self) -> None:
        if isinstance(self.max_bytes, bool) or not isinstance(self.max_bytes, int) or self.max_bytes <= 0:
            raise ValueError("COLLECTOR_DB_MAX_SIZE must be positive")
        if not math.isfinite(self.check_interval_seconds) or self.check_interval_seconds <= 0:
            raise ValueError("COLLECTOR_DB_CHECK_INTERVAL_SECONDS must be positive and finite")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> StorageSettings:
        values = os.environ if environ is None else environ
        try:
            interval = float(values.get("COLLECTOR_DB_CHECK_INTERVAL_SECONDS", "5"))
        except ValueError as error:
            raise ValueError("COLLECTOR_DB_CHECK_INTERVAL_SECONDS must be a number") from error
        return cls(
            max_bytes=parse_storage_size(values.get("COLLECTOR_DB_MAX_SIZE", "100GB")),
            check_interval_seconds=interval,
        )


class StorageWriteRejected(Exception):
    status_code = 503
    code = "storage_check_unavailable"

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class StorageLimitExceeded(StorageWriteRejected):
    status_code = 507
    code = "storage_limit_reached"


@dataclass(frozen=True, slots=True)
class StorageSnapshot:
    limit_bytes: int
    allocated_bytes: int | None
    estimated_bytes: int | None
    accepting_writes: bool
    reason: str | None
    checked_at: datetime | None
    check_interval_seconds: float


class DatabaseStorageGuard:
    def __init__(self, database: StorageDatabase, settings: StorageSettings) -> None:
        self.database = database
        self.settings = settings
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._allocated_bytes: int | None = None
        self._checked_at: datetime | None = None
        self._checked_monotonic: float | None = None
        self._check_failed = False
        self._admitted_bytes = 0
        self._sampled_admitted_bytes = 0
        self._in_flight_bytes = 0

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Storage monitor is already running")
        await self.refresh()
        self._task = asyncio.create_task(self._monitor(), name="collector-storage-monitor")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _monitor(self) -> None:
        while True:
            await asyncio.sleep(self.settings.check_interval_seconds)
            await self.refresh()

    async def refresh(self) -> None:
        # A sample may run concurrently with inserts. Preserve the budget of
        # writes that were in flight at its start, and all newly admitted writes.
        async with self._lock:
            sampled_admitted = self._admitted_bytes - self._in_flight_bytes
        try:
            async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
                stats = await self.database.command("dbStats", scale=1, maxTimeMS=1500)
            allocated = stats["totalSize"]
            if isinstance(allocated, bool) or not isinstance(allocated, (int, float)):
                raise ValueError("dbStats.totalSize is not numeric")
            if not math.isfinite(allocated) or allocated < 0 or int(allocated) != allocated:
                raise ValueError("dbStats.totalSize is not a non-negative byte count")
        except Exception:
            if not self._check_failed:
                LOGGER.warning("Cannot check MongoDB storage; new writes are paused", exc_info=True)
            self._check_failed = True
            return

        async with self._lock:
            self._allocated_bytes = int(allocated)
            self._sampled_admitted_bytes = sampled_admitted
            self._checked_at = datetime.now(timezone.utc)
            self._checked_monotonic = time.monotonic()
            self._check_failed = False

    def snapshot(self) -> StorageSnapshot:
        estimated = None if self._allocated_bytes is None else (
            self._allocated_bytes + self._admitted_bytes - self._sampled_admitted_bytes
        )
        stale_after = 2 * self.settings.check_interval_seconds + CHECK_TIMEOUT_SECONDS
        if self._check_failed or self._checked_monotonic is None:
            reason = "storage_check_unavailable"
        elif time.monotonic() - self._checked_monotonic > stale_after:
            reason = "storage_check_stale"
        elif estimated is not None and estimated + MIN_WRITE_BUDGET > self.settings.max_bytes:
            reason = "storage_limit_reached"
        else:
            reason = None
        return StorageSnapshot(
            limit_bytes=self.settings.max_bytes,
            allocated_bytes=self._allocated_bytes,
            estimated_bytes=estimated,
            accepting_writes=reason is None,
            reason=reason,
            checked_at=self._checked_at,
            check_interval_seconds=self.settings.check_interval_seconds,
        )

    @asynccontextmanager
    async def reserve(self, payload_bytes: int) -> AsyncIterator[None]:
        # JSON size is only an estimate of BSON/index growth. Reserve additional
        # budget between real disk samples rather than admit an unlimited burst.
        budget = max(MIN_WRITE_BUDGET, 2 * payload_bytes)
        retry_after = max(1, math.ceil(self.settings.check_interval_seconds))
        async with self._lock:
            state = self.snapshot()
            if state.reason in {"storage_check_unavailable", "storage_check_stale"}:
                raise StorageWriteRejected("Storage usage is unavailable; new writes are paused", retry_after)
            if state.estimated_bytes is None or state.estimated_bytes + budget > state.limit_bytes:
                raise StorageLimitExceeded("Collector storage limit reached; new writes are paused", retry_after)
            self._admitted_bytes += budget
            self._in_flight_bytes += budget
        try:
            yield
        finally:
            async with self._lock:
                self._in_flight_bytes -= budget
            # Keep even failed admissions charged until the next measurement:
            # an interrupted response does not prove that MongoDB did not write.
