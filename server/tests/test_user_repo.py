from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError, OperationFailure

from src.core.modules.database.errors import (
    RepoAlreadyExistsError, RepoEmptyDataError, RepoNotFoundError,
    RepoProtectedAdminError, RepoUserManagementUnavailableError,
)
from src.core.modules.database.user import ADMIN_GUARD_ID, MongoUserRepo


ADMIN = ObjectId("60d5ec49f1a4a21f6c8b4567")
READER = ObjectId("60d5ec49f1a4a21f6c8b4568")


def setup():
    database = Mock()
    database.users = AsyncMock()
    database.collector_settings = AsyncMock()
    return MongoUserRepo(database), database


@pytest.mark.asyncio
async def test_get_all_users():
    repo, database = setup()
    database.users.find = Mock(return_value=SimpleNamespace(to_list=AsyncMock(return_value=[{"_id": ADMIN}])) )
    assert await repo.get_all_users() == [{"_id": str(ADMIN)}]


@pytest.mark.asyncio
async def test_get_user_and_email():
    repo, database = setup()
    database.users.find_one.return_value = {"_id": ADMIN, "email": "admin@example.com"}
    assert (await repo.get_user(str(ADMIN)))["_id"] == str(ADMIN)
    assert (await repo.get_user_by_email("admin@example.com"))["email"] == "admin@example.com"


@pytest.mark.asyncio
async def test_missing_user_and_empty_email():
    repo, database = setup()
    database.users.find_one.return_value = None
    with pytest.raises(RepoNotFoundError):
        await repo.get_user(str(ADMIN))
    with pytest.raises(RepoNotFoundError):
        await repo.get_user_by_email("missing@example.com")
    with pytest.raises(RepoEmptyDataError):
        await repo.get_user_by_email("")


@pytest.mark.asyncio
async def test_insert_uses_unique_index_without_racy_precheck_and_does_not_modify_input():
    repo, database = setup()
    database.users.insert_one.return_value = SimpleNamespace(inserted_id=READER)
    fields = {"email": "reader@example.com"}
    assert await repo.add_user(fields) == {"_id": str(READER), **fields}
    assert fields == {"email": "reader@example.com"}
    database.users.find_one.assert_not_awaited()
    database.users.create_index.assert_awaited_once_with([("email", 1)], unique=True, maxTimeMS=10_000)
    await repo.add_user(fields)
    database.users.create_index.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_insert_maps_driver_error_to_conflict():
    repo, database = setup()
    database.users.insert_one.side_effect = DuplicateKeyError("private driver details")
    with pytest.raises(RepoAlreadyExistsError, match="email"):
        await repo.add_user({"email": "reader@example.com"})


@pytest.mark.asyncio
async def test_index_failure_leaves_legacy_accounts_intact_and_does_not_mark_index_ready():
    repo, database = setup()
    database.users.create_index.side_effect = DuplicateKeyError("legacy duplicates")
    for _ in range(2):
        with pytest.raises(RepoUserManagementUnavailableError):
            await repo.add_user({"email": "new@example.com"})
    assert database.users.create_index.await_count == 2
    database.users.insert_one.assert_not_awaited()
    database.users.delete_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_returns_the_atomic_write_result():
    repo, database = setup()
    database.users.find_one_and_update.return_value = {"_id": READER, "email": "changed@example.com"}
    result = await repo.update_user(str(READER), {"email": "changed@example.com"})
    assert result == {"_id": str(READER), "email": "changed@example.com"}
    database.users.find_one.assert_not_awaited()
    database.users.find_one_and_update.assert_awaited_once_with(
        {"_id": READER}, {"$set": {"email": "changed@example.com"}},
        return_document=True, maxTimeMS=10_000,
    )


@pytest.mark.asyncio
async def test_duplicate_update_maps_driver_error_to_conflict():
    repo, database = setup()
    database.users.find_one_and_update.side_effect = DuplicateKeyError("private driver details")
    with pytest.raises(RepoAlreadyExistsError):
        await repo.update_user(str(READER), {"email": "admin@example.com"})


@pytest.mark.asyncio
async def test_empty_or_missing_update():
    repo, database = setup()
    with pytest.raises(RepoEmptyDataError):
        await repo.update_user(str(READER), {})
    database.users.find_one_and_update.return_value = None
    with pytest.raises(RepoNotFoundError):
        await repo.update_user(str(READER), {"name": "New"})


@pytest.mark.asyncio
async def test_protected_admin_cannot_be_removed_or_demoted():
    repo, database = setup()
    database.collector_settings.find_one.return_value = {"_id": ADMIN_GUARD_ID, "user_id": ADMIN}
    database.users.find_one.return_value = {"_id": ADMIN}
    with pytest.raises(RepoProtectedAdminError):
        await repo.delete_user(str(ADMIN))
    with pytest.raises(RepoProtectedAdminError):
        await repo.update_user(str(ADMIN), {"position": "regular", "email": "changed@example.com"})
    database.users.delete_one.assert_not_awaited()
    database.users.find_one_and_update.assert_not_awaited()
    database.users.create_index.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_admin_can_be_deleted_and_missing_delete_is_404():
    repo, database = setup()
    database.collector_settings.find_one.return_value = {"user_id": ADMIN}
    database.users.find_one.return_value = {"_id": ADMIN}
    database.users.delete_one.return_value = SimpleNamespace(deleted_count=1)
    assert (await repo.delete_user(str(READER))).deleted_count == 1
    database.users.delete_one.assert_awaited_with({"_id": READER})
    database.users.delete_one.return_value = SimpleNamespace(deleted_count=0)
    with pytest.raises(RepoNotFoundError):
        await repo.delete_user(str(READER))


@pytest.mark.asyncio
async def test_initialization_uses_the_shared_winner_not_its_own_candidate():
    repo, database = setup()
    database.collector_settings.find_one.return_value = None
    database.users.find_one.side_effect = [{"_id": READER}, {"_id": ADMIN}]
    database.collector_settings.find_one_and_update.return_value = {"user_id": ADMIN}
    with pytest.raises(RepoProtectedAdminError):
        await repo.delete_user(str(ADMIN))
    database.collector_settings.find_one_and_update.assert_awaited_once_with(
        {"_id": ADMIN_GUARD_ID}, {"$setOnInsert": {"user_id": READER}},
        upsert=True, return_document=True, maxTimeMS=10_000,
    )
    database.users.delete_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_upsert_duplicate_reads_the_winner():
    repo, database = setup()
    database.collector_settings.find_one.side_effect = [None, {"user_id": ADMIN}]
    database.users.find_one.side_effect = [{"_id": READER}, {"_id": ADMIN}]
    database.collector_settings.find_one_and_update.side_effect = DuplicateKeyError("concurrent upsert")
    with pytest.raises(RepoProtectedAdminError):
        await repo.delete_user(str(ADMIN))


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", [{"user_id": "not-an-object-id"}, {"user_id": ADMIN}])
async def test_corrupt_guard_is_not_reassigned_and_no_user_is_changed(guard):
    repo, database = setup()
    database.collector_settings.find_one.return_value = guard
    database.users.find_one.return_value = None
    with pytest.raises(RepoUserManagementUnavailableError):
        await repo.delete_user(str(READER))
    database.collector_settings.find_one_and_update.assert_not_awaited()
    database.users.delete_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_admin_or_failed_guard_write_prevents_destructive_operation():
    repo, database = setup()
    database.collector_settings.find_one.return_value = None
    database.users.find_one.return_value = None
    with pytest.raises(RepoUserManagementUnavailableError):
        await repo.delete_user(str(READER))
    database.users.find_one.return_value = {"_id": ADMIN}
    database.collector_settings.find_one_and_update.side_effect = OperationFailure("unavailable")
    with pytest.raises(OperationFailure):
        await repo.delete_user(str(READER))
    database.users.delete_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_password_replacement_keeps_compare_and_swap():
    repo, database = setup()
    database.users.update_one.return_value = SimpleNamespace(modified_count=1)
    assert await repo.replace_password(str(ADMIN), "old", "new")
    database.users.update_one.assert_awaited_once_with(
        {"_id": ADMIN, "password": "old"}, {"$set": {"password": "new"}},
    )
