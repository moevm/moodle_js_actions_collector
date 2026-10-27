"""Opt-in checks in disposable databases; never modify real collector accounts."""

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from src.core.modules.database.errors import (
    RepoAlreadyExistsError, RepoNotFoundError, RepoProtectedAdminError,
    RepoUserManagementUnavailableError,
)
from src.core.modules.database.user import ADMIN_GUARD_ID, MongoUserRepo


pytestmark = [pytest.mark.skipif(
    os.getenv("COLLECTOR_RUN_MONGO_TESTS") != "1", reason="Opt-in real MongoDB check",
), pytest.mark.asyncio]
ADMIN = ObjectId("60d5ec49f1a4a21f6c8b4567")
OTHER = ObjectId("60d5ec49f1a4a21f6c8b4568")


@pytest_asyncio.fixture
async def user_database():
    from src.depends import uri

    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    name = f"collector_users_test_{uuid4().hex}"
    try:
        yield client[name]
    finally:
        try:
            await client.drop_database(name)
        finally:
            client.close()


def fields(email, role="regular"):
    return {"name": "Test", "surname": "User", "lastname": "Example", "email": email,
            "position": role, "password": "test-placeholder"}


async def test_real_mongo_concurrent_creates_and_conflicting_update(user_database):
    database = user_database
    await database.users.insert_one({"_id": ADMIN, **fields("admin@example.com", "admin")})
    # Independent repositories model separate workers; no shared Python lock.
    outcomes = await asyncio.gather(*[
        MongoUserRepo(database).add_user(fields("same@example.com")) for _ in range(8)
    ], return_exceptions=True)
    users = [value for value in outcomes if isinstance(value, dict)]
    assert len(users) == 1, outcomes
    assert sum(isinstance(value, RepoAlreadyExistsError) for value in outcomes) == 7, outcomes
    assert await database.users.count_documents({"email": "same@example.com"}) == 1
    indexes = await database.users.index_information()
    assert indexes["email_1"]["unique"] is True
    repo = MongoUserRepo(database)
    target = users[0]["_id"]
    before = await repo.get_user(target)
    with pytest.raises(RepoAlreadyExistsError):
        await repo.update_user(target, {"email": "admin@example.com", "position": "admin"})
    assert await repo.get_user(target) == before
    unchanged = await repo.update_user(target, {"email": "same@example.com"})
    assert unchanged["email"] == "same@example.com"
    changed = await repo.update_user(target, {"email": "changed@example.com"})
    assert changed["email"] == "changed@example.com"


async def test_real_mongo_concurrent_admin_removal_keeps_permanent_anchor(user_database):
    database = user_database
    ids = [ADMIN, OTHER, ObjectId("60d5ec49f1a4a21f6c8b4569")]
    await database.users.insert_many([
        {"_id": object_id, **fields(f"admin{index}@example.com", "admin")}
        for index, object_id in enumerate(ids)
    ])

    async def attempt(object_id, delete):
        repo = MongoUserRepo(database)
        try:
            if delete:
                await repo.delete_user(str(object_id))
            else:
                await repo.update_user(str(object_id), {"position": "regular"})
        except (RepoProtectedAdminError, RepoNotFoundError) as error:
            result = error
        else:
            result = None
        assert await database.users.count_documents({"position": "admin"}) >= 1
        return result

    results = await asyncio.gather(*[
        attempt(object_id, delete) for _ in range(4) for object_id in ids for delete in (True, False)
    ])
    assert sum(isinstance(value, RepoProtectedAdminError) for value in results) == 8
    guard = await database.collector_settings.find_one({"_id": ADMIN_GUARD_ID})
    assert guard["user_id"] == ADMIN
    assert await database.collector_settings.count_documents({}) == 1
    assert (await database.users.find_one({"_id": ADMIN}))["position"] == "admin"

    # A newly promoted, older ObjectId must not change the existing anchor.
    earlier_id = ObjectId("000000000000000000000001")
    await database.users.insert_one({"_id": earlier_id, **fields("earlier@example.com")})
    repo = MongoUserRepo(database)
    await repo.update_user(str(earlier_id), {"position": "admin"})
    await repo.update_user(str(earlier_id), {"position": "regular"})
    await repo.update_user(str(earlier_id), {"position": "admin"})
    await MongoUserRepo(database).delete_user(str(earlier_id))
    with pytest.raises(RepoProtectedAdminError):
        await MongoUserRepo(database).update_user(str(ADMIN), {"position": "regular"})
    updated = await repo.update_user(str(ADMIN), {"name": "Changed", "email": "changed-admin@example.com", "password": "changed", "position": "admin"})
    assert updated["name"] == "Changed"
    assert updated["password"] == "changed"


async def test_real_mongo_broken_guard_does_not_delete_or_choose_another_admin(user_database):
    database = user_database
    await database.users.insert_one({"_id": OTHER, **fields("other@example.com", "admin")})
    await database.collector_settings.insert_one({"_id": ADMIN_GUARD_ID, "user_id": ADMIN})
    with pytest.raises(RepoUserManagementUnavailableError):
        await MongoUserRepo(database).delete_user(str(OTHER))
    assert await database.users.count_documents({}) == 1
    assert (await database.collector_settings.find_one({"_id": ADMIN_GUARD_ID}))["user_id"] == ADMIN


async def test_real_mongo_legacy_duplicates_are_preserved_and_new_writes_refused(user_database):
    database = user_database
    await database.users.insert_many([
        fields("duplicate@example.com", "admin"), fields("duplicate@example.com"),
    ])
    repo = MongoUserRepo(database)
    with pytest.raises(RepoUserManagementUnavailableError):
        await repo.add_user(fields("new@example.com"))
    assert await database.users.count_documents({}) == 2
    assert len(await repo.get_all_users()) == 2
    assert await database.users.count_documents({"email": "new@example.com"}) == 0
