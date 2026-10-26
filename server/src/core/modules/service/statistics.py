import logging
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any
from datetime import datetime, timezone

from bson import ObjectId
from src.core.modules.database.errors import RepoNotFoundError
from src.core.modules.service.errors import SessionNotFoundError

from src.models.filter import SessionFilter, StatisticsFilter


class StatisticsService:
    def __init__(self, repo, pages):
        self.repo = repo
        self.pages = pages

    async def get_all_sessions(self, filters: SessionFilter):
        try:
            return await self.repo.get_all_sessions(filters)
        except Exception as e:
            logging.error("Statistics query failed: %s", type(e).__name__)
            raise

    async def get_session(self, session_id):
        try:
            return await self.repo.get_session(session_id)
        except Exception as e:
            if isinstance(e, RepoNotFoundError):
                logging.info("Statistics record not found")
                raise SessionNotFoundError(f"error getting session {session_id}: {str(e)}") from e
            else:
                raise

    async def delete_session(self, session_id):
        try:
            return await self.repo.delete_session(session_id)
        except Exception as e:
            if isinstance(e, RepoNotFoundError):
                logging.info("Statistics record not found for deletion")
                raise SessionNotFoundError(f"error deleting session {session_id}: {str(e)}") from e
            else:
                raise

    async def create_session(self, session_data):
        try:
            session_data['session_id'] = ObjectId(session_data['session_id'])
            for action in session_data["actions"]:
                value = datetime.fromisoformat(action["timestamp"])
                if value.tzinfo is not None:
                    value = value.astimezone(timezone.utc).replace(tzinfo=None)
                action["timestamp"] = value
            return await self.repo.add_session(session_data)
        except Exception as e:
            logging.error("Statistics insert failed: %s", type(e).__name__)
            raise

    async def create_page(self, page_data):
        try:
            return await self.pages.create_record(page_data)
        except Exception as e:
            logging.error("Page metadata insert failed: %s", type(e).__name__)
            raise

    async def iter_sessions(self, filters: StatisticsFilter) -> AsyncGenerator[dict[str, Any], None]:
        async with aclosing(self.repo.iter_sessions(filters)) as records:
            async for record in records:
                yield record

    async def iter_pages(self) -> AsyncGenerator[dict[str, Any], None]:
        async with aclosing(self.pages.iter_records()) as records:
            async for record in records:
                yield record
