import os
from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import quote_plus

import motor.motor_asyncio as aio_motor
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo.errors import PyMongoError

from src.core.modules.database.statistics import MongoStatisticRepo, MongoPageRepo
from src.core.modules.database.user import MongoUserRepo
from src.core.modules.service.authorization import AuthService
from src.core.modules.service.statistics import StatisticsService
from src.core.modules.service.user import UserService
from src.core.storage import DatabaseStorageGuard, StorageSettings
from src.core.security import AccessTokens, SecuritySettings
from src.core.login_limits import LoginLimiter
from src.core.modules.service.errors import UserNotFoundError
from src.models.user import Role, User


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
access_tokens = AccessTokens(SecuritySettings.from_env())
login_limiter = LoginLimiter()
user_bearer = HTTPBearer(auto_error=False, scheme_name="UserAccessToken")
ingestion_bearer = HTTPBearer(auto_error=False, scheme_name="CollectionKey")
STORAGE_WRITE_RESPONSES = {
    503: {"description": "Storage monitoring is unavailable or stale; new writes are paused"},
    507: {"description": "The database storage budget is exhausted; new writes are paused"},
}
user_service = UserService(MongoUserRepo(db))
statistics_service = StatisticsService(MongoStatisticRepo(db), MongoPageRepo(db))
auth_service = AuthService(MongoUserRepo(db), storage_guard)


def get_user_service() -> UserService:
    return user_service


def get_statistics_service() -> StatisticsService:
    return statistics_service


def get_auth_service() -> AuthService:
    return auth_service


def get_login_limiter() -> LoginLimiter:
    return login_limiter


def get_storage_guard() -> DatabaseStorageGuard:
    return storage_guard


def get_access_tokens() -> AccessTokens:
    return access_tokens


def unauthorized() -> HTTPException:
    return HTTPException(401, "Authentication required or token expired", headers={"WWW-Authenticate": "Bearer"})


async def require_current_user(
    response: Response,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(user_bearer)],
    tokens: Annotated[AccessTokens, Depends(get_access_tokens)],
    users: Annotated[UserService, Depends(get_user_service)],
) -> User:
    if credentials is None:
        raise unauthorized()
    try:
        claims = tokens.decode(credentials.credentials)
        record = await users.get_user(claims.subject)
        if not isinstance(record.get("password"), str) or not tokens.matches_user(claims, record):
            raise unauthorized()
        response.headers["Cache-Control"] = "no-store"
        return User.model_validate(record)
    except (ValueError, UserNotFoundError) as error:
        raise unauthorized() from error
    except PyMongoError as error:
        raise HTTPException(503, "Authentication database is unavailable") from error


async def require_admin(user: Annotated[User, Depends(require_current_user)]) -> User:
    if user.position != Role.admin:
        raise HTTPException(403, "Administrator access required")
    return user


async def require_ingestion_key(
    response: Response,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(ingestion_bearer)],
    tokens: Annotated[AccessTokens, Depends(get_access_tokens)],
) -> None:
    if credentials is None or not tokens.accepts_ingestion_key(credentials.credentials):
        raise unauthorized()
    response.headers["Cache-Control"] = "no-store"


async def require_storage_capacity(
    request: Request,
    guard: Annotated[DatabaseStorageGuard, Depends(get_storage_guard)],
) -> AsyncIterator[None]:
    # FastAPI caches the request body; this does not make another database call.
    async with guard.reserve(len(await request.body())):
        yield
