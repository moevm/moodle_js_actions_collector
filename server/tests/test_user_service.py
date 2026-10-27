from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.modules.database.errors import (
    RepoAlreadyExistsError, RepoEmptyDataError, RepoNotFoundError,
    RepoProtectedAdminError, RepoUserManagementUnavailableError,
)
from src.core.modules.service.errors import (
    ProtectedAdminError, UserAlreadyExistsError, UserEmptyDataError,
    UserManagementUnavailableError, UserNotFoundError,
)
from src.core.modules.service.user import UserService
from src.core.passwords import verify_password
from src.models.user import UpdateUser


ID = "60d5ec49f1a4a21f6c8b4567"
FIELDS = {"name": "Test", "surname": "User", "lastname": "Example", "email": "test@example.com", "position": "admin"}


@pytest.mark.asyncio
async def test_read_users_and_map_missing_user():
    repo = AsyncMock()
    repo.get_user.return_value = {"_id": ID}
    repo.get_all_users.return_value = [{"_id": ID}]
    service = UserService(repo)
    assert await service.get_user(ID) == {"_id": ID}
    assert await service.get_all_users() == [{"_id": ID}]
    repo.get_user.side_effect = RepoNotFoundError()
    with pytest.raises(UserNotFoundError):
        await service.get_user(ID)


@pytest.mark.asyncio
async def test_create_forces_regular_hashes_password_and_preserves_input():
    repo = AsyncMock()
    repo.add_user.side_effect = lambda fields: {"_id": ID, **fields}
    fields = {**FIELDS, "password": "example-password"}
    user = await UserService(repo).create_user(fields)
    assert user["position"] == "regular"
    assert verify_password("example-password", user["password"])
    assert fields == {**FIELDS, "password": "example-password"}


@pytest.mark.asyncio
async def test_update_hashes_password_only_when_provided():
    repo = AsyncMock()
    service = UserService(repo)
    await service.update_user(ID, UpdateUser(**FIELDS, password="changed-password"))
    args = repo.update_user.call_args.args
    assert args[0] == ID
    assert verify_password("changed-password", args[1]["password"])
    await service.update_user(ID, UpdateUser(**FIELDS))
    assert "password" not in repo.update_user.call_args.args[1]


@pytest.mark.asyncio
async def test_delete_returns_repository_result():
    repo = AsyncMock()
    repo.delete_user.return_value = SimpleNamespace(deleted_count=1)
    assert (await UserService(repo).delete_user(ID)).deleted_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("repo_error", "service_error"), [
    (RepoAlreadyExistsError, UserAlreadyExistsError),
    (RepoEmptyDataError, UserEmptyDataError),
    (RepoNotFoundError, UserNotFoundError),
    (RepoProtectedAdminError, ProtectedAdminError),
    (RepoUserManagementUnavailableError, UserManagementUnavailableError),
])
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
async def test_mutations_translate_repository_errors(repo_error, service_error, operation):
    repo = AsyncMock()
    method = {"create": "add_user", "update": "update_user", "delete": "delete_user"}[operation]
    getattr(repo, method).side_effect = repo_error("Expected failure")
    service = UserService(repo)
    with pytest.raises(service_error, match="Expected failure"):
        if operation == "create":
            await service.create_user({**FIELDS, "password": "example-password"})
        elif operation == "update":
            await service.update_user(ID, UpdateUser(**FIELDS))
        else:
            await service.delete_user(ID)
