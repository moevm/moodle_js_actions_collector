"""Opt-in BSON boundary checks in a disposable MongoDB database."""

import os
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.encoders import jsonable_encoder
from motor.motor_asyncio import AsyncIOMotorClient

from src.core.modules.database.statistics import MongoPageRepo, MongoStatisticRepo
from src.core.modules.service.errors import SessionNotFoundError
from src.core.modules.service.statistics import StatisticsService
from src.models.constraints import BSON_INT64_MAX
from src.models.filter import MAX_PAGE, MAX_PAGE_SIZE, SessionFilter
from src.models.session_data import CreateSessionData


@pytest.mark.skipif(os.getenv("COLLECTOR_RUN_MONGO_TESTS") != "1", reason="Opt-in real MongoDB check")
@pytest.mark.asyncio
async def test_real_mongo_numeric_bounds_utc_defaults_and_missing_records():
    from src.depends import uri

    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    name = f"collector_validation_test_{uuid4().hex}"
    database = client[name]
    repo = MongoStatisticRepo(database)
    service = StatisticsService(repo, MongoPageRepo(database))
    try:
        page = await service.create_page({"page": "https://moodle.example/", "title": "Validation",
            "browser": "test", "window": {"width": 1, "height": 1}})
        event = {"element_type": "button", "element_name": "save", "action_type": "interactions",
                 "event_type": "mousedown", "element_html": "<button>"}
        body = CreateSessionData(student_id=BSON_INT64_MAX, session_id=page["_id"], student="Test",
            email="test@example.com", course="Test", tabID="test-tab", url="https://moodle.example/",
            actions=[{**event, "timestamp": "2026-10-27T10:00:00+03:00"}, event])
        saved = await service.create_session(jsonable_encoder(body))
        assert saved["student_id"] == BSON_INT64_MAX
        assert saved["actions"][0]["timestamp"] == datetime(2026, 10, 27, 7)
        assert isinstance(saved["actions"][1]["timestamp"], datetime)
        rows, total = await repo.get_all_sessions(SessionFilter(student_id=BSON_INT64_MAX))
        assert total == len(rows) == 1
        rows, total = await repo.get_all_sessions(SessionFilter(page=MAX_PAGE, pageSize=MAX_PAGE_SIZE))
        assert total == 1 and rows == []
        for operation in (service.get_session, service.delete_session):
            with pytest.raises(SessionNotFoundError):
                await operation("f" * 24)
        await service.delete_session(saved["_id"])
        with pytest.raises(SessionNotFoundError):
            await service.delete_session(saved["_id"])
    finally:
        try:
            await client.drop_database(name)
        finally:
            client.close()
