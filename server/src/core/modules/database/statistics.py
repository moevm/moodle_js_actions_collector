from collections.abc import AsyncGenerator
from typing import Any

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
        pipeline = [{"$match": query}, {"$sort": {"_id": -1}},
                    {"$skip": start}, {"$limit": pages['pageSize']}]
        if projection := filters.action_projection():
            pipeline.append(projection)
        cursor = self.client.statistics.aggregate(pipeline, maxTimeMS=READ_MAX_TIME_MS,
                                                  batchSize=pages['pageSize'])
        try:
            records = await cursor.to_list(length=pages['pageSize'])
        finally:
            await cursor.close()
        for session in records:
            session["_id"] = str(session["_id"])
            session["session_id"] = str(session["session_id"])
            stats.append(session)
        return [stats, total_rows]

    async def iter_sessions(self, filters: StatisticsFilter) -> AsyncGenerator[dict[str, Any], None]:
        pipeline = [{"$match": filters.mongo_query()}, {"$sort": {"_id": -1}}]
        if projection := filters.action_projection():
            pipeline.append(projection)
        cursor = self.client.statistics.aggregate(pipeline, maxTimeMS=READ_MAX_TIME_MS,
                                                  batchSize=EXPORT_BATCH_SIZE)
        try:
            async for session in cursor:
                session["_id"] = str(session["_id"])
                session["session_id"] = str(session["session_id"])
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
