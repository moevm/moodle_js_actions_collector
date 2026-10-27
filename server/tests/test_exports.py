import asyncio
import json
import threading
import time
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import ServerSelectionTimeoutError

from src.api import exports
from src.core.modules.database.statistics import MongoStatisticRepo
from src.models.filter import StatisticsFilter
from tests.test_security_api import ADMIN, bearer, secured_api


async def render(response, send=None, receive=None):
    messages = []

    async def collect(message):
        messages.append(message)
        await asyncio.sleep(0)

    async def wait_for_disconnect():
        await asyncio.Event().wait()

    await response({"type": "http", "asgi": {"spec_version": "2.3"}},
                   receive or wait_for_disconnect, send or collect)
    return b"".join(message.get("body", b"") for message in messages)


@pytest.mark.asyncio
async def test_twenty_parallel_http_exports_keep_each_filters_data(secured_api, monkeypatch, tmp_path):
    state = secured_api
    gate = exports.ExportGate(maximum=20)
    monkeypatch.setattr(exports, "export_gate", gate)

    async def records(filters):
        for index in range(filters.student_id % 3 + 1):
            await asyncio.sleep(0)
            yield {"student_id": filters.student_id, "index": index, "student": 'Имя "test"'}

    state.stats.iter_sessions = records
    headers = bearer(state.tokens.issue(state.users.records[ADMIN]))
    responses = await asyncio.gather(*[
        state.client.get("/api/download/statistics", params={"student_id": marker, "page": 999, "pageSize": 1}, headers=headers)
        for marker in range(1, 21)
    ])
    for marker, response in enumerate(responses, 1):
        assert response.status_code == 200, response.text
        rows, total = response.json()
        assert total == len(rows) == marker % 3 + 1
        assert {row["student_id"] for row in rows} == {marker}
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-accel-buffering"] == "no"
    assert gate.active == 0
    assert not (tmp_path / "data.json").exists()
    assert not (tmp_path / "sessions.json").exists()
    state.stats.get_all_sessions.assert_not_awaited()


@pytest.mark.asyncio
async def test_slow_download_has_backpressure_and_rejects_extra_exports():
    gate = exports.ExportGate()
    consumed = []
    closed = asyncio.Event()
    blocked, release = asyncio.Event(), asyncio.Event()

    async def records():
        try:
            for index in range(1000):
                consumed.append(index)
                yield {"index": index}
        finally:
            closed.set()

    async def send(message):
        if message.get("body", b"").startswith(b'{"index"'):
            blocked.set()
            await release.wait()

    response = await exports.json_export(records(), filename="sessions.json", gate=gate)
    task = asyncio.create_task(render(response, send=send))
    try:
        await asyncio.wait_for(blocked.wait(), 1)
        assert consumed == [0], "A slow client must not make us load the whole cursor"
        with pytest.raises(HTTPException) as error:
            await exports.json_export(records(), filename="sessions.json", gate=gate)
        assert error.value.status_code == 429
        assert error.value.headers["Retry-After"] == "3"
    finally:
        release.set()
        await task
    assert closed.is_set()
    assert gate.active == 0
    assert await render(await exports.json_export(records(), filename="sessions.json", gate=gate))


@pytest.mark.asyncio
@pytest.mark.parametrize("disconnect", [True, False])
async def test_disconnect_or_cancellation_closes_iterator_and_releases_slot(disconnect):
    gate = exports.ExportGate()
    closed, started = asyncio.Event(), asyncio.Event()

    async def records():
        try:
            yield {"index": 0}
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            closed.set()

    async def send(message):
        if message.get("body", b"").startswith(b'{"index"'):
            started.set()
            await asyncio.Event().wait()

    async def receive():
        await started.wait()
        return {"type": "http.disconnect"}

    response = await exports.json_export(records(), filename="data.json", gate=gate)
    task = asyncio.create_task(render(response, send=send, receive=receive if disconnect else None))
    await asyncio.wait_for(started.wait(), 1)
    if disconnect:
        await asyncio.wait_for(task, 1)
    else:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert closed.is_set()
    assert gate.active == 0


@pytest.mark.asyncio
async def test_slow_reader_times_out_and_releases_slot(monkeypatch):
    monkeypatch.setattr(exports, "EXPORT_TIMEOUT_SECONDS", 0.02)
    gate = exports.ExportGate()
    closed = asyncio.Event()

    async def records():
        try:
            yield {"index": 0}
        finally:
            closed.set()

    async def send(message):
        await asyncio.Event().wait()

    response = await exports.json_export(records(), filename="data.json", gate=gate)
    with pytest.raises(TimeoutError):
        await render(response, send=send)
    assert closed.is_set()
    assert gate.active == 0


@pytest.mark.asyncio
async def test_export_database_failure_before_headers_returns_503(secured_api, monkeypatch):
    gate = exports.ExportGate()
    monkeypatch.setattr(exports, "export_gate", gate)

    async def records():
        raise ServerSelectionTimeoutError("internal database address")
        yield

    state = secured_api
    state.stats.iter_pages = records
    headers = bearer(state.tokens.issue(state.users.records[ADMIN]))
    response = await state.client.get("/api/download/sessions", headers=headers)
    assert response.status_code == 503
    assert "internal database address" not in response.text
    assert gate.active == 0


@pytest.mark.asyncio
async def test_failed_cursor_mid_download_releases_resources():
    gate = exports.ExportGate()
    closed = asyncio.Event()

    async def records():
        try:
            yield {"index": 0}
            raise RuntimeError("Cursor failed during download")
        finally:
            closed.set()

    response = await exports.json_export(records(), filename="data.json", gate=gate)
    with pytest.raises(ExceptionGroup):
        await render(response)
    assert closed.is_set()
    assert gate.active == 0


@pytest.mark.asyncio
async def test_initial_cursor_timeout_is_bounded_and_releases_slot(monkeypatch):
    monkeypatch.setattr(exports, "EXPORT_START_TIMEOUT_SECONDS", 0.02)
    gate = exports.ExportGate()
    closed = asyncio.Event()

    async def records():
        try:
            await asyncio.Event().wait()
            yield {}
        finally:
            closed.set()

    with pytest.raises(HTTPException) as error:
        await exports.json_export(records(), filename="data.json", gate=gate)
    assert error.value.status_code == 503
    assert closed.is_set()
    assert gate.active == 0


@pytest.mark.asyncio
async def test_serializer_runs_outside_event_loop(monkeypatch):
    event_loop_thread = threading.get_ident()
    serializer_threads = []
    original = exports.dumps

    def serialize(value, **kwargs):
        serializer_threads.append(threading.get_ident())
        time.sleep(0.03)  # Deterministically model CPU/serialization latency.
        return original(value, **kwargs)

    monkeypatch.setattr(exports, "dumps", serialize)

    async def records():
        for index in range(4):
            yield {"index": index}

    response = await exports.json_export(records(), filename="data.json", gate=exports.ExportGate())
    task = asyncio.create_task(render(response))
    ticks = 0
    while not task.done():
        ticks += 1
        await asyncio.sleep(0.005)
    assert len(json.loads(await task)) == 4
    assert ticks >= 5
    assert all(thread != event_loop_thread for thread in serializer_threads)


@pytest.mark.asyncio
async def test_statistics_cursor_closes_on_early_stop_without_materializing_all_rows():
    cursor = MagicMock()
    for method in ("sort", "batch_size", "max_time_ms"):
        getattr(cursor, method).return_value = cursor
    cursor.__aiter__.return_value = [
        {"_id": ObjectId(), "session_id": ObjectId(), "actions": []},
        {"_id": ObjectId(), "session_id": ObjectId(), "actions": []},
    ]
    cursor.close = AsyncMock()
    database = Mock()
    database.statistics.aggregate.return_value = cursor
    records = MongoStatisticRepo(database).iter_sessions(StatisticsFilter(student_id=42))
    first = await anext(records)
    assert isinstance(first["_id"], str)
    await records.aclose()
    cursor.close.assert_awaited_once()
    cursor.to_list.assert_not_called()
    options = database.statistics.aggregate.call_args.kwargs
    assert options["batchSize"] == 20
    assert options["maxTimeMS"] == 10_000


@pytest.mark.asyncio
@pytest.mark.parametrize("page_size", [-2, -1, 0, 101, 1_000_000_000])
async def test_invalid_page_sizes_are_http_422(secured_api, page_size):
    state = secured_api
    headers = bearer(state.tokens.issue(state.users.records[ADMIN]))
    response = await state.client.get("/api/statistics/", params={"pageSize": page_size}, headers=headers)
    assert response.status_code == 422, response.text
    state.stats.get_all_sessions.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("page_size", [1, 100])
async def test_page_size_boundaries_are_accepted(secured_api, page_size):
    state = secured_api
    headers = bearer(state.tokens.issue(state.users.records[ADMIN]))
    response = await state.client.get("/api/statistics/", params={"pageSize": page_size}, headers=headers)
    assert response.status_code == 200, response.text

