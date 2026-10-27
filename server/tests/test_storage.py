import asyncio

import pytest

from src.core import storage
from src.core.storage import (
    DatabaseStorageGuard, StorageLimitExceeded, StorageSettings,
    StorageWriteRejected, parse_storage_size,
)


class Database:
    def __init__(self, allocated: int = 0) -> None:
        self.allocated = allocated
        self.error: Exception | None = None
        self.started: asyncio.Event | None = None
        self.release: asyncio.Event | None = None
        self.calls = 0

    async def command(self, command: str, **kwargs: object) -> dict:
        assert command == "dbStats"
        assert kwargs["scale"] == 1
        self.calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return {"totalSize": self.allocated}


@pytest.mark.parametrize(("value", "expected"), [
    ("100GB", 100_000_000_000), ("100GiB", 100 * 1024**3),
    ("1.5MB", 1_500_000), (" 2 mib ", 2 * 1024**2),
    ("2048", 2048), ("1B", 1),
])
def test_size_units(value: str, expected: int) -> None:
    assert parse_storage_size(value) == expected


@pytest.mark.parametrize("value", ["", "0", "-1GB", "NaN", "inf", "1G", "1.1B", "1e6", "999999999TB"])
def test_invalid_size_fails_instead_of_disabling_limit(value: str) -> None:
    with pytest.raises(ValueError, match="COLLECTOR_DB_MAX_SIZE"):
        parse_storage_size(value)


def test_defaults_and_environment_override() -> None:
    assert StorageSettings.from_env({}).max_bytes == 100_000_000_000
    settings = StorageSettings.from_env({
        "COLLECTOR_DB_MAX_SIZE": "256MiB", "COLLECTOR_DB_CHECK_INTERVAL_SECONDS": "2.5",
    })
    assert settings.max_bytes == 256 * 1024**2
    assert settings.check_interval_seconds == 2.5


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
def test_invalid_interval_fails(value: str) -> None:
    with pytest.raises(ValueError, match="COLLECTOR_DB_CHECK_INTERVAL_SECONDS"):
        StorageSettings.from_env({"COLLECTOR_DB_CHECK_INTERVAL_SECONDS": value})


@pytest.mark.asyncio
async def test_no_admission_before_first_measurement() -> None:
    guard = DatabaseStorageGuard(Database(), StorageSettings())
    with pytest.raises(StorageWriteRejected) as rejected:
        async with guard.reserve(100):
            pytest.fail("Unmeasured storage must not accept writes")
    assert rejected.value.status_code == 503


@pytest.mark.asyncio
async def test_limit_blocks_writes_and_recovers_after_disk_usage_drops() -> None:
    db = Database(10_000)
    guard = DatabaseStorageGuard(db, StorageSettings(max_bytes=10_000))
    await guard.refresh()
    with pytest.raises(StorageLimitExceeded) as rejected:
        async with guard.reserve(100):
            pytest.fail("Full storage must not accept writes")
    assert rejected.value.status_code == 507
    assert guard.snapshot().reason == "storage_limit_reached"
    db.allocated = 0
    await guard.refresh()
    async with guard.reserve(100):
        pass
    assert guard.snapshot().accepting_writes


@pytest.mark.asyncio
async def test_concurrent_requests_share_budget_without_per_request_database_checks() -> None:
    db = Database()
    guard = DatabaseStorageGuard(db, StorageSettings(max_bytes=8192))
    await guard.refresh()

    async def write() -> bool:
        try:
            async with guard.reserve(10):
                await asyncio.sleep(0)
            return True
        except StorageLimitExceeded:
            return False

    admitted = await asyncio.gather(*(write() for _ in range(100)))
    assert sum(admitted) == 2
    assert db.calls == 1
    assert guard.snapshot().estimated_bytes == 8192


@pytest.mark.asyncio
async def test_large_request_cannot_exceed_remaining_estimated_budget() -> None:
    db = Database(20_000)
    guard = DatabaseStorageGuard(db, StorageSettings(max_bytes=30_000))
    await guard.refresh()
    with pytest.raises(StorageLimitExceeded):
        async with guard.reserve(6000):
            pytest.fail("A request larger than the remaining budget must be rejected")


@pytest.mark.asyncio
async def test_failed_response_stays_charged_until_next_successful_sample() -> None:
    guard = DatabaseStorageGuard(Database(), StorageSettings(max_bytes=4096))
    await guard.refresh()
    with pytest.raises(RuntimeError):
        async with guard.reserve(10):
            raise RuntimeError("MongoDB may have written before the response failed")
    with pytest.raises(StorageLimitExceeded):
        async with guard.reserve(10):
            pass
    await guard.refresh()
    async with guard.reserve(10):
        pass


@pytest.mark.asyncio
async def test_refresh_preserves_inflight_and_newly_admitted_write_budgets() -> None:
    db = Database()
    guard = DatabaseStorageGuard(db, StorageSettings(max_bytes=100_000))
    await guard.refresh()
    db.started, db.release = asyncio.Event(), asyncio.Event()
    async with guard.reserve(10):
        checking = asyncio.create_task(guard.refresh())
        await db.started.wait()
        async with guard.reserve(10):
            pass
    # Both writes ended while the sample was outstanding. Its result may not
    # include either write, so both reservations must survive that result.
    db.release.set()
    await checking
    assert guard.snapshot().estimated_bytes == 8192
    db.allocated = 6000
    await guard.refresh()
    assert guard.snapshot().estimated_bytes == 6000


@pytest.mark.asyncio
async def test_monitor_error_pauses_writes_until_a_successful_sample() -> None:
    db = Database()
    guard = DatabaseStorageGuard(db, StorageSettings())
    await guard.refresh()
    db.error = ConnectionError("Database unavailable")
    await guard.refresh()
    with pytest.raises(StorageWriteRejected) as rejected:
        async with guard.reserve(1):
            pass
    assert rejected.value.status_code == 503
    db.error = None
    await guard.refresh()
    assert guard.snapshot().accepting_writes


@pytest.mark.asyncio
async def test_stale_sample_pauses_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = DatabaseStorageGuard(Database(), StorageSettings())
    await guard.refresh()
    now = storage.time.monotonic()
    monkeypatch.setattr(storage.time, "monotonic", lambda: now + 100)
    assert guard.snapshot().reason == "storage_check_stale"
    with pytest.raises(StorageWriteRejected):
        async with guard.reserve(1):
            pass


@pytest.mark.asyncio
async def test_storage_check_timeout_does_not_hang_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database()
    db.release = asyncio.Event()
    guard = DatabaseStorageGuard(db, StorageSettings())
    monkeypatch.setattr(storage, "CHECK_TIMEOUT_SECONDS", 0.01)
    await asyncio.wait_for(guard.refresh(), timeout=1)
    assert not guard.snapshot().accepting_writes


@pytest.mark.asyncio
async def test_background_monitor_recovers_and_stops_cleanly() -> None:
    db = Database(10_000)
    guard = DatabaseStorageGuard(db, StorageSettings(max_bytes=10_000, check_interval_seconds=0.001))
    await guard.start()
    try:
        assert not guard.snapshot().accepting_writes
        db.allocated = 0
        db.started = asyncio.Event()
        await asyncio.wait_for(db.started.wait(), timeout=1)
        assert guard.snapshot().accepting_writes
    finally:
        await guard.stop()
    calls = db.calls
    await asyncio.sleep(0.01)
    assert db.calls == calls
