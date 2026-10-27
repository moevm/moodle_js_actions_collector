"""Opt-in authentication/password migration checks in an isolated MongoDB database."""

import os
import secrets
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from src.core.modules.database.user import MongoUserRepo
from src.core.modules.service.authorization import AuthService
from src.core.modules.service.errors import UserNotFoundError
from src.core.passwords import hash_password, is_hashed_password
from src.core.security import AccessTokens, SecuritySettings
from src.core.storage import DatabaseStorageGuard, StorageSettings


@pytest.mark.skipif(os.getenv("COLLECTOR_RUN_MONGO_TESTS") != "1", reason="Opt-in real MongoDB check")
@pytest.mark.asyncio
async def test_real_mongo_legacy_login_hash_upgrade_and_token_revocation() -> None:
    from src.depends import uri

    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    name = f"collector_security_test_{uuid4().hex}"
    database = client[name]
    guard = DatabaseStorageGuard(database, StorageSettings(max_bytes=100_000_000))
    try:
        await database.users.insert_one({
            "name": "Test", "surname": "Admin", "lastname": "Example", "email": "probe@example.com",
            "position": "admin", "password": "legacy-password",
        })
        await guard.start()
        repo = MongoUserRepo(database)
        auth = AuthService(repo, guard)
        tokens = AccessTokens(SecuritySettings(secrets.token_urlsafe(32), secrets.token_urlsafe(32)))
        user = await auth.sign_in("probe@example.com", "legacy-password")
        assert user is not None
        saved = await repo.get_user(user["_id"])
        assert is_hashed_password(saved["password"])
        assert await auth.sign_in("probe@example.com", "wrong-password") is None
        with pytest.raises(UserNotFoundError):
            await auth.sign_in("missing@example.com", "wrong-password")
        claims = tokens.decode(tokens.issue(user))
        assert tokens.matches_user(claims, saved)
        await repo.update_user(user["_id"], {"password": hash_password("changed-password")})
        assert not tokens.matches_user(claims, await repo.get_user(user["_id"]))
        assert await auth.sign_in("probe@example.com", "legacy-password") is None
        assert await auth.sign_in("probe@example.com", "changed-password") is not None
    finally:
        await guard.stop()
        try:
            await client.drop_database(name)
        finally:
            client.close()
