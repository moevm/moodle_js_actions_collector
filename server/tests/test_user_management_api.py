from unittest.mock import AsyncMock, Mock

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError, OperationFailure

from src.core.modules.database.user import MongoUserRepo
from src.core.modules.service.user import UserService
from tests.test_security_api import ADMIN, CREATE_USER, READER, bearer, secured_api


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update"])
async def test_email_driver_collisions_return_409_without_private_details(secured_api, monkeypatch, operation):
    from src.api.endpoints import user

    database = Mock(users=AsyncMock())
    driver_error = DuplicateKeyError("private-db-name email_1 dup key private@example.com")
    database.users.insert_one.side_effect = driver_error
    database.users.find_one_and_update.side_effect = driver_error
    monkeypatch.setattr(user, "service", UserService(MongoUserRepo(database)))
    headers = bearer(secured_api.tokens.issue(secured_api.users.records[ADMIN]))
    if operation == "create":
        response = await secured_api.client.post("/api/user/", headers=headers, json=CREATE_USER)
    else:
        response = await secured_api.client.put(f"/api/user/{READER}", headers=headers,
            json={**CREATE_USER, "position": "admin"})
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "email_conflict"
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["delete", "demote"])
async def test_protected_admin_rejection_preserves_account_and_token(secured_api, monkeypatch, operation):
    from src.api.endpoints import user

    database = Mock(users=AsyncMock(), collector_settings=AsyncMock())
    database.collector_settings.find_one.return_value = {"user_id": ObjectId(ADMIN)}
    database.users.find_one.return_value = {"_id": ObjectId(ADMIN), "position": "admin"}
    monkeypatch.setattr(user, "service", UserService(MongoUserRepo(database)))
    headers = bearer(secured_api.tokens.issue(secured_api.users.records[ADMIN]))
    if operation == "delete":
        response = await secured_api.client.delete(f"/api/user/{ADMIN}", headers=headers)
    else:
        response = await secured_api.client.put(f"/api/user/{ADMIN}", headers=headers,
            json={**CREATE_USER, "position": "regular"})
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "protected_administrator"
    database.users.delete_one.assert_not_awaited()
    database.users.find_one_and_update.assert_not_awaited()
    assert (await secured_api.client.get("/api/statistics/", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_missing_legacy_unique_index_is_not_ignored(secured_api, monkeypatch):
    from src.api.endpoints import user

    database = Mock(users=AsyncMock())
    database.users.create_index.side_effect = DuplicateKeyError("private legacy duplicates")
    monkeypatch.setattr(user, "service", UserService(MongoUserRepo(database)))
    headers = bearer(secured_api.tokens.issue(secured_api.users.records[ADMIN]))
    response = await secured_api.client.post("/api/user/", headers=headers, json=CREATE_USER)
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "user_management_unavailable"
    assert "private" not in response.text
    database.users.insert_one.assert_not_awaited()
    assert (await secured_api.client.get("/api/statistics/", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_database_failure_is_a_safe_503(secured_api, monkeypatch):
    from src.api.endpoints import user

    database = Mock(users=AsyncMock(), collector_settings=AsyncMock())
    database.collector_settings.find_one.side_effect = OperationFailure("private query or address")
    monkeypatch.setattr(user, "service", UserService(MongoUserRepo(database)))
    headers = bearer(secured_api.tokens.issue(secured_api.users.records[ADMIN]))
    response = await secured_api.client.delete(f"/api/user/{READER}", headers=headers)
    assert response.status_code == 503, response.text
    assert "private" not in response.text
    database.users.delete_one.assert_not_awaited()
