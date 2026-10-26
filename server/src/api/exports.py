"""Isolated JSON streams with bounded concurrency, lifetime and cleanup."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

import anyio
from bson.json_util import dumps
from fastapi import HTTPException
from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send


LOGGER = logging.getLogger(__name__)
EXPORT_TIMEOUT_SECONDS = 300
EXPORT_START_TIMEOUT_SECONDS = 10


class ExportGate:
    """One event-loop-local gate; current deployment runs one API worker."""

    def __init__(self, maximum: int = 1) -> None:
        self.maximum = maximum
        self.active = 0

    def acquire(self) -> None:
        # No await between checking and incrementing; rejected clients never queue.
        if self.active >= self.maximum:
            raise HTTPException(429, "Another export is running; retry later", headers={"Retry-After": "3"})
        self.active += 1

    def release(self) -> None:
        self.active -= 1


export_gate = ExportGate()


async def close_records(records: AsyncGenerator[dict[str, Any], None]) -> None:
    # StreamingResponse 0.36 does not close a suspended iterator on every
    # disconnect path. Shield async cursor cleanup from its cancelled task group.
    with anyio.move_on_after(3, shield=True):
        await records.aclose()


class JsonExportResponse(StreamingResponse):
    def __init__(
        self, records: AsyncGenerator[dict[str, Any], None], first: dict[str, Any] | None,
        gate: ExportGate, *, filename: str, with_total: bool,
    ) -> None:
        self.records = records
        self.first = first
        self.gate = gate
        self.with_total = with_total
        self.generator = self.chunks()
        super().__init__(self.generator, media_type="application/json", headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        })

    async def chunks(self) -> AsyncGenerator[bytes, None]:
        yield b"[[" if self.with_total else b"["
        record = self.first
        self.first = None
        count = 0
        while record is not None:
            # Only one document is serialized at a time. JSON conversion runs
            # outside the event loop; sending each chunk applies backpressure.
            chunk = await run_in_threadpool(dumps, record, ensure_ascii=False)
            yield (b"," if count else b"") + chunk.encode("utf-8")
            count += 1
            record = await anext(self.records, None)
        yield f"],{count}]".encode("ascii") if self.with_total else b"]"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            async with asyncio.timeout(EXPORT_TIMEOUT_SECONDS):
                await super().__call__(scope, receive, send)
        finally:
            try:
                with anyio.move_on_after(3, shield=True):
                    await self.generator.aclose()
                await close_records(self.records)
            finally:
                self.first = None
                self.gate.release()


async def json_export(
    records: AsyncGenerator[dict[str, Any], None], *, filename: str, with_total: bool = False,
    gate: ExportGate | None = None,
) -> JsonExportResponse:
    gate = export_gate if gate is None else gate
    try:
        gate.acquire()
    except HTTPException:
        await close_records(records)
        raise
    try:
        # Resolve the cursor before sending HTTP 200, so an unavailable database
        # produces a normal error instead of a seemingly successful empty file.
        async with asyncio.timeout(EXPORT_START_TIMEOUT_SECONDS):
            first = await anext(records, None)
        return JsonExportResponse(records, first, gate, filename=filename, with_total=with_total)
    except BaseException as error:
        try:
            await close_records(records)
        finally:
            gate.release()
        if isinstance(error, (PyMongoError, TimeoutError)):
            LOGGER.warning("Export could not start: %s", type(error).__name__)
            raise HTTPException(503, "Export database is unavailable or the query timed out") from error
        raise
