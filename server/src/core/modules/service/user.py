from typing import Any

from starlette.concurrency import run_in_threadpool

from src.core.modules.database.errors import (
    RepoAlreadyExistsError, RepoEmptyDataError, RepoNotFoundError,
    RepoProtectedAdminError, RepoUserManagementUnavailableError,
)
from src.core.modules.service.errors import (
    ProtectedAdminError, UserAlreadyExistsError, UserEmptyDataError,
    UserManagementUnavailableError, UserNotFoundError,
)
from src.core.passwords import hash_password
from src.models.user import Role, UpdateUser


REPO_ERRORS = (
    RepoAlreadyExistsError, RepoEmptyDataError, RepoNotFoundError,
    RepoProtectedAdminError, RepoUserManagementUnavailableError,
)
SERVICE_ERRORS = {
    RepoAlreadyExistsError: UserAlreadyExistsError,
    RepoEmptyDataError: UserEmptyDataError,
    RepoNotFoundError: UserNotFoundError,
    RepoProtectedAdminError: ProtectedAdminError,
    RepoUserManagementUnavailableError: UserManagementUnavailableError,
}


class UserService:
    def __init__(self, repo: Any) -> None:
        self.repo = repo

    async def get_all_users(self) -> list:
        return await self.repo.get_all_users()

    async def get_user(self, user_id: str) -> dict:
        try:
            return await self.repo.get_user(user_id)
        except RepoNotFoundError as error:
            raise UserNotFoundError("User not found") from error

    async def create_user(self, user_data: dict) -> dict:
        fields = {**user_data, "position": Role.regular}
        fields["password"] = await run_in_threadpool(hash_password, fields["password"])
        try:
            return await self.repo.add_user(fields)
        except REPO_ERRORS as error:
            raise SERVICE_ERRORS[type(error)](str(error)) from error

    async def update_user(self, user_id: str, user_data: UpdateUser) -> dict:
        fields = user_data.model_dump(exclude_none=True)
        if "password" in fields:
            fields["password"] = await run_in_threadpool(hash_password, fields["password"])
        try:
            return await self.repo.update_user(user_id, fields)
        except REPO_ERRORS as error:
            raise SERVICE_ERRORS[type(error)](str(error)) from error

    async def delete_user(self, user_id: str) -> Any:
        try:
            return await self.repo.delete_user(user_id)
        except REPO_ERRORS as error:
            raise SERVICE_ERRORS[type(error)](str(error)) from error
