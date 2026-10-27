"""Opt-in storage check against real MongoDB, using a separate temporary database."""

import os
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from src.core.storage import DatabaseStorageGuard, StorageLimitExceeded, StorageSettings


@pytest.mark.skipif(
    os.getenv("COLLECTOR_RUN_MONGO_TESTS") != "1",
    reason="Set COLLECTOR_RUN_MONGO_TESTS=1 to check an isolated temporary MongoDB database",
)
@pytest.mark.asyncio
async def test_real_mongo_storage_measurement_blocking_and_larger_budget() -> None:
    from src.depends import uri

    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    name = f"collector_storage_test_{uuid4().hex}"
    database = client[name]
    try:
        await database.probe.create_index("key")
        await database.probe.insert_one({"key": 1, "payload": "storage probe" * 100})
        measured = await database.command("dbStats", scale=1)
        assert measured["totalSize"] > 0
        assert measured["indexSize"] > 0

        full = DatabaseStorageGuard(database, StorageSettings(max_bytes=int(measured["totalSize"])))
        await full.refresh()
        with pytest.raises(StorageLimitExceeded):
            async with full.reserve(1000):
                await database.probe.insert_one({"key": 2})
        assert await database.probe.count_documents({}) == 1

        larger = DatabaseStorageGuard(
            database, StorageSettings(max_bytes=int(measured["totalSize"]) + 10_000_000),
        )
        await larger.start()
        try:
            async with larger.reserve(1000):
                await database.probe.insert_one({"key": 2})
            assert await database.probe.count_documents({}) == 2
            assert larger.snapshot().accepting_writes
        finally:
            await larger.stop()
    finally:
        try:
            await client.drop_database(name)
        finally:
            client.close()
