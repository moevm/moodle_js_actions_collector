"""Opt-in checks of actual Motor cursors and streaming against an isolated DB."""

import json
import os
from uuid import uuid4

import pytest
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from src.api.exports import ExportGate, json_export
from src.core.modules.database.statistics import MongoPageRepo, MongoStatisticRepo
from src.core.modules.service.statistics import StatisticsService
from src.models.filter import SessionFilter, StatisticsFilter


async def response_body(response) -> bytes:
    chunks = []

    async def send(message):
        if message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    async def receive():
        import asyncio
        await asyncio.Event().wait()

    await response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)
    return b"".join(chunks)


@pytest.mark.skipif(os.getenv("COLLECTOR_RUN_MONGO_TESTS") != "1", reason="Opt-in real MongoDB check")
@pytest.mark.asyncio
async def test_real_mongo_pagination_and_full_stream_without_legacy_html() -> None:
    from src.depends import uri

    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    name = f"collector_export_test_{uuid4().hex}"
    database = client[name]
    try:
        page_id = ObjectId()
        await database.sessions.insert_one({
            "_id": page_id, "page": "https://moodle.example/export-test", "title": "Export",
            "browser": "test", "window": {"width": 1, "height": 1}, "page_html": "private legacy HTML",
        })
        await database.statistics.insert_many([
            {"student_id": 42, "session_id": page_id, "actions": [], "index": index}
            for index in range(103)
        ])
        await database.statistics.insert_one({"student_id": 43, "session_id": page_id, "actions": []})
        repo = MongoStatisticRepo(database)
        first, total = await repo.get_all_sessions(SessionFilter(student_id=42, page=1, pageSize=100))
        second, _ = await repo.get_all_sessions(SessionFilter(student_id=42, page=2, pageSize=100))
        assert total == 103
        assert len(first) == 100
        assert len(second) == 3
        service = StatisticsService(repo, MongoPageRepo(database))
        gate = ExportGate()
        response = await json_export(service.iter_sessions(StatisticsFilter(student_id=42)),
                                     filename="data.json", with_total=True, gate=gate)
        rows, exported = json.loads(await response_body(response))
        assert exported == len(rows) == 103
        assert {row["index"] for row in rows} == set(range(103))
        assert all(row["session_id"] == str(page_id) for row in rows)
        response = await json_export(service.iter_pages(), filename="sessions.json", gate=gate)
        pages = json.loads(await response_body(response))
        assert len(pages) == 1
        assert "page_html" not in pages[0]
        assert gate.active == 0
    finally:
        try:
            await client.drop_database(name)
        finally:
            client.close()
