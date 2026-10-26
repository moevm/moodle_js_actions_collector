import os
from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import quote_plus

import motor.motor_asyncio as aio_motor
from dotenv import load_dotenv
from fastapi import Depends, Request

from src.core.modules.database.statistics import MongoStatisticRepo, MongoPageRepo
from src.core.modules.database.user import MongoUserRepo
from src.core.modules.service.authorization import AuthService
from src.core.modules.service.statistics import StatisticsService
from src.core.modules.service.user import UserService
from src.core.storage import DatabaseStorageGuard, StorageSettings


load_dotenv()

user = os.getenv('MONGODB_ROOT_USER')
password = os.getenv('MONGODB_ROOT_PASSWORD')
dbname = os.getenv('MONGODB_DATABASE')

uri = os.getenv('MONGODB_URI') or (
    f'mongodb://{quote_plus(user or "")}:{quote_plus(password or "")}@mongodb:27017/?authSource=admin'
)
client = aio_motor.AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000, tz_aware=False)
db = client[dbname]
storage_guard = DatabaseStorageGuard(db, StorageSettings.from_env())
STORAGE_WRITE_RESPONSES = {
    503: {"description": "Storage monitoring is unavailable or stale; new writes are paused"},
    507: {"description": "The database storage budget is exhausted; new writes are paused"},
}
user_service = UserService(MongoUserRepo(db))
statistics_service = StatisticsService(MongoStatisticRepo(db), MongoPageRepo(db))
auth_service = AuthService(MongoUserRepo(db))


def get_user_service() -> UserService:
    return user_service


def get_statistics_service() -> StatisticsService:
    return statistics_service


def get_auth_service() -> AuthService:
    return auth_service


def get_storage_guard() -> DatabaseStorageGuard:
    return storage_guard


async def require_storage_capacity(
    request: Request,
    guard: Annotated[DatabaseStorageGuard, Depends(get_storage_guard)],
) -> AsyncIterator[None]:
    # FastAPI caches the request body; this does not make another database call.
    async with guard.reserve(len(await request.body())):
        yield
