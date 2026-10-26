import logging
from starlette.concurrency import run_in_threadpool

from src.core.modules.database.errors import RepoNotFoundError, RepoEmptyDataError
from src.core.modules.service.errors import UserNotFoundError, UserEmptyDataError
from src.core.passwords import hash_password, is_hashed_password, verify_password
from src.core.storage import DatabaseStorageGuard, StorageWriteRejected


class AuthService:
    def __init__(self, repo, storage_guard: DatabaseStorageGuard | None = None):
        self.repo = repo
        self.storage_guard = storage_guard

    async def sign_in(self, email, password):
        try:
            user = await self.repo.get_user_by_email(email)
            if not await run_in_threadpool(verify_password, password, user["password"]):
                return None
            if (self.storage_guard is not None and "_id" in user
                    and not is_hashed_password(user["password"])):
                replacement = await run_in_threadpool(hash_password, password)
                try:
                    async with self.storage_guard.reserve(len(replacement)):
                        changed = await self.repo.replace_password(user["_id"], user["password"], replacement)
                except StorageWriteRejected:
                    # Reading the UI must remain possible when the database is full.
                    return user
                if changed:
                    user["password"] = replacement
                else:
                    user = await self.repo.get_user(user["_id"])
                    if not await run_in_threadpool(verify_password, password, user["password"]):
                        return None
            return user
        except Exception as e:
            if isinstance(e, RepoNotFoundError):
                logging.error(f'error authorizing user: {str(e)}')
                raise UserNotFoundError(f'error authorizing user: {str(e)}') from e
            elif isinstance(e, RepoEmptyDataError):
                logging.error(f'error authorizing user: {str(e)}')
                raise UserEmptyDataError(f'error authorizing user: {str(e)}') from e
            else:
                raise
