"""Opt-in literal-search contract checks against an isolated real MongoDB."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from src.core.modules.database.statistics import MongoStatisticRepo
from src.models.filter import SessionFilter, StatisticsFilter


@pytest.mark.skipif(os.getenv("COLLECTOR_RUN_MONGO_TESTS") != "1", reason="Opt-in real MongoDB check")
@pytest.mark.asyncio
async def test_real_mongo_literal_search_same_action_and_export_consistency():
    from src.depends import uri

    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    name = f"collector_search_test_{uuid4().hex}"
    database = client[name]
    base = datetime(2026, 10, 27)

    def action(element, event="mousedown", timestamp=base):
        return {"element_name": element, "event_type": event, "timestamp": timestamp,
                "action_type": "conversation", "element_type": "input", "element_html": "<input>"}

    try:
        await database.statistics.insert_many([
            {"student_id": 101, "student": "Иван [Тест]", "email": "student.name+tag@example.org",
             "course": "Курс (A+B)", "session_id": ObjectId(), "actions": [
                 action("answer[0]"), action("a+b", "keydown"), action("(", "copy"), action("a.b"),
             ]},
            {"student_id": 102, "student": "Иван Тест", "email": "studentXname+tag@example.org",
             "course": "Другой курс", "session_id": ObjectId(), "actions": [action("answer0"), action("ab")]},
            {"student_id": 103, "student": "Other", "email": "other@example.org", "course": "Other",
             "session_id": ObjectId(), "actions": [action("other"), action("answer[0]", "keydown")]},
            {"student_id": 104, "student": "Legacy", "email": "legacy@example.org", "course": "Other",
             "session_id": ObjectId(), "actions": [action(["answer[0]"])]},
        ])
        repo = MongoStatisticRepo(database)
        cases = [
            ({"element_name": "answer[0]"}, {101: ["answer[0]"], 103: ["answer[0]"]}),
            ({"element_name": "a+b"}, {101: ["a+b"]}),
            ({"element_name": "("}, {101: ["("]}),
            ({"element_name": "."}, {101: ["a.b"]}),
            ({"event_type": "^mousedown$"}, {}),
            ({"student_email": "student.name+tag@example.org"}, {101: ["answer[0]", "a+b", "(", "a.b"]}),
            ({"student_name": "[ТЕСТ]"}, {101: ["answer[0]", "a+b", "(", "a.b"]}),
            ({"course_title": "(a+b)"}, {101: ["answer[0]", "a+b", "(", "a.b"]}),
            ({"element_name": "answer[0]", "event_type": "mousedown"}, {101: ["answer[0]"]}),
            ({"student_id": 0}, {}),
            ({"student_id": 101, "begin_timestamp": base.replace(tzinfo=timezone.utc)},
             {101: ["answer[0]", "a+b", "(", "a.b"]}),
        ]
        for params, expected in cases:
            rows, total = await repo.get_all_sessions(SessionFilter(**params))
            actual = {row["student_id"]: [a["element_name"] for a in row["actions"]] for row in rows}
            assert actual == expected, params
            assert total == len(expected), params
            exported = [row async for row in repo.iter_sessions(StatisticsFilter(**params))]
            assert exported == rows, params
        # MongoDB stores milliseconds. Both matching and projection must use
        # the same encoded precision, rather than a later Python microsecond test.
        rows, total = await repo.get_all_sessions(SessionFilter(student_id=101,
            begin_timestamp=base.replace(microsecond=900), end_timestamp=base.replace(microsecond=999)))
        assert total == 1
        assert len(rows[0]["actions"]) == 4
    finally:
        try:
            await client.drop_database(name)
        finally:
            client.close()
