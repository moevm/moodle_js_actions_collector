from collections.abc import AsyncGenerator
from typing import Any

from starlette.concurrency import run_in_threadpool

from bson.objectid import ObjectId
from src.core.modules.database.errors import RepoNotFoundError
from src.models.filter import SessionFilter, StatisticsFilter


READ_MAX_TIME_MS = 10_000
EXPORT_BATCH_SIZE = 20


PAGE_METADATA_FIELDS = ("page", "browser", "title", "window")
PAGE_METADATA_PROJECTION = {field: 1 for field in PAGE_METADATA_FIELDS}


class MongoStatisticRepo:
    def __init__(self, client):
        self.client = client

    async def get_all_sessions(self, filters: SessionFilter) -> list:
        stats = []
        query, pages = filters.query()
        start = (pages['page'] - 1) * pages['pageSize']
        total_rows = await self.client.statistics.count_documents(query, maxTimeMS=READ_MAX_TIME_MS)
        cursor = (self.client.statistics.find(query).sort({"_id": -1})
                  .skip(start).limit(pages['pageSize']).max_time_ms(READ_MAX_TIME_MS))
        try:
            records = await cursor.to_list(length=pages['pageSize'])
        finally:
            await cursor.close()
        for session in records:
            session["_id"] = str(session["_id"])
            session["session_id"] = str(session["session_id"])
            session['actions'] = filter_actions(filters, session['actions'])
            stats.append(session)
        return [stats, total_rows]

    async def iter_sessions(self, filters: StatisticsFilter) -> AsyncGenerator[dict[str, Any], None]:
        cursor = (self.client.statistics.find(filters.mongo_query()).sort({"_id": -1})
                  .batch_size(EXPORT_BATCH_SIZE).max_time_ms(READ_MAX_TIME_MS))
        try:
            async for session in cursor:
                session["_id"] = str(session["_id"])
                session["session_id"] = str(session["session_id"])
                session['actions'] = await run_in_threadpool(filter_actions, filters, session['actions'])
                yield session
        finally:
            await cursor.close()

    async def get_session(self, record_id: str) -> dict:
        stat = await self.client.statistics.find_one({"_id": ObjectId(record_id)})
        if stat:
            stat["_id"] = str(stat["_id"])
            stat["session_id"] = str(stat["session_id"])
            return stat
        raise RepoNotFoundError(f'record {record_id} not found')

    async def add_session(self, session_data: dict) -> dict:
        stat = await self.client.statistics.insert_one(session_data)
        new_stat = await self.client.statistics.find_one({"_id": stat.inserted_id})
        new_stat["_id"] = str(new_stat["_id"])
        new_stat['session_id'] = str(new_stat['session_id'])
        return new_stat

    async def delete_session(self, record_id: str):
        stat = await self.client.statistics.find_one({"_id": ObjectId(record_id)})
        if stat:
            return await self.client.statistics.delete_one({"_id": ObjectId(record_id)})
        raise RepoNotFoundError(f'record {record_id} not found')


def filter_actions(query: StatisticsFilter, payload: list) -> list:
    if not query or not any((query.action_type, query.event_type, query.element_type,
                             query.element_name, query.begin_timestamp, query.end_timestamp)):
        return payload
    data = payload
    if query.action_type:
        data = filter(lambda item: query.action_type.lower() in str(item['action_type']).lower(), data)
    if query.event_type:
        data = filter(lambda item: query.event_type.lower() in str(item['event_type']).lower(), data)
    if query.element_type:
        data = filter(lambda item: query.element_type.lower() in str(item['element_type']).lower(), data)
    if query.element_name:
        data = filter(lambda item: query.element_name.lower() in str(item['element_name']).lower(), data)
    if query.begin_timestamp:
        data = filter(lambda item: query.begin_timestamp <= item['timestamp'], data)
    if query.end_timestamp:
        data = filter(lambda item: query.end_timestamp >= item['timestamp'], data)
    return list(data)


class MongoPageRepo:
    def __init__(self, client):
        self.client = client

    async def create_record(self, page_data: dict) -> dict:
        # Keep legacy page_html out of storage even for internal callers.
        metadata = {field: page_data[field] for field in PAGE_METADATA_FIELDS}
        page = await self.client.sessions.insert_one(metadata)
        new_page = await self.client.sessions.find_one(
            {"_id": page.inserted_id}, PAGE_METADATA_PROJECTION
        )
        new_page["_id"] = str(new_page["_id"])
        return new_page

    async def iter_records(self) -> AsyncGenerator[dict[str, Any], None]:
        # Project in MongoDB so historical HTML is neither loaded nor exported.
        cursor = (self.client.sessions.find({}, PAGE_METADATA_PROJECTION)
                  .batch_size(EXPORT_BATCH_SIZE).max_time_ms(READ_MAX_TIME_MS))
        try:
            async for page in cursor:
                page["_id"] = str(page["_id"])
                yield page
        finally:
            await cursor.close()
