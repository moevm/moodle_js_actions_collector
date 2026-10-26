import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from bson import ObjectId

from src.core.modules.database.errors import RepoNotFoundError
from src.core.modules.service.authorization import AuthService
from src.core.modules.service.user import UserService
from src.core.passwords import is_hashed_password, verify_password
from src.core.security import AccessTokens, SecuritySettings
from src.core.storage import DatabaseStorageGuard, StorageSettings


ADMIN = "60d5ec49f1a4a21f6c8b4567"
READER = "60d5ec49f1a4a21f6c8b4568"
PAGE = {"page": "https://moodle.example/", "title": "Test", "browser": "test", "window": {"width": 1, "height": 1}}
SESSION = {
    "student_id": 7, "student": "Student", "email": "student@example.com", "course": "Course",
    "tabID": "tab-test", "url": PAGE["page"], "session_id": ADMIN, "actions": [],
}
CREATE_USER = {"name": "New", "surname": "User", "lastname": "Test", "email": "new@example.com", "password": "new-password"}
PRIVATE_REQUESTS = [
    ("GET", "/api/statistics/", None), ("GET", f"/api/statistics/{ADMIN}", None),
    ("DELETE", f"/api/statistics/{ADMIN}", None),
    ("GET", "/api/download/statistics", None), ("GET", "/api/download/sessions", None),
    ("GET", "/api/user/", None), ("GET", f"/api/user/{ADMIN}", None),
    ("POST", "/api/user/", CREATE_USER),
    ("PUT", f"/api/user/{ADMIN}", {**CREATE_USER, "position": "admin"}),
    ("DELETE", f"/api/user/{ADMIN}", None), ("GET", "/api/healthcheck/storage", None),
]


class Users:
    def __init__(self) -> None:
        self.records = {
            key: {"_id": key, "name": "Test", "surname": "User", "lastname": "Example",
                  "email": f"{role}@example.com", "password": f"{role}-password", "position": role}
            for key, role in [(ADMIN, "admin"), (READER, "regular")]
        }

    async def get_user(self, user_id: str) -> dict:
        if user_id not in self.records:
            raise RepoNotFoundError("User not found")
        return copy.deepcopy(self.records[user_id])

    async def get_user_by_email(self, email: str) -> dict:
        for user in self.records.values():
            if user["email"] == email:
                return copy.deepcopy(user)
        raise RepoNotFoundError("User not found")

    async def get_all_users(self) -> list:
        return copy.deepcopy(list(self.records.values()))

    async def replace_password(self, user_id: str, expected: str, replacement: str) -> bool:
        if self.records[user_id]["password"] != expected:
            return False
        self.records[user_id]["password"] = replacement
        return True

    async def add_user(self, data: dict) -> dict:
        user_id = str(ObjectId())
        self.records[user_id] = {"_id": user_id, **copy.deepcopy(data)}
        return copy.deepcopy(self.records[user_id])

    async def update_user(self, user_id: str, data: dict) -> dict:
        self.records[user_id].update(data)
        return copy.deepcopy(self.records[user_id])

    async def delete_user(self, user_id: str) -> SimpleNamespace:
        return SimpleNamespace(deleted_count=int(self.records.pop(user_id, None) is not None))


class Database:
    allocated = 0

    async def command(self, command: str, **kwargs: object) -> dict:
        return {"ok": 1} if command == "ping" else {"totalSize": self.allocated}


@pytest_asyncio.fixture
async def secured_api(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("MONGODB_DATABASE", "security-isolated-tests")
    import main
    from src.api.endpoints import statistics, user, healthcheck
    from src.depends import get_access_tokens, get_auth_service, get_user_service, get_storage_guard

    users, db = Users(), Database()
    guard = DatabaseStorageGuard(db, StorageSettings(max_bytes=1_000_000))
    tokens = AccessTokens(SecuritySettings("signing-" + "a" * 40, "ingestion-" + "b" * 40))
    auth, user_service = AuthService(users, guard), UserService(users)
    stats = SimpleNamespace(
        get_all_sessions=AsyncMock(return_value=[[], 0]), get_pages=AsyncMock(return_value=[]),
        get_session=AsyncMock(return_value={"_id": ADMIN, **SESSION}),
        create_page=AsyncMock(return_value={"_id": ADMIN}),
        create_session=AsyncMock(side_effect=lambda value: {"_id": ADMIN, **value}),
        delete_session=AsyncMock(return_value=SimpleNamespace(deleted_count=1)),
    )
    previous = dict(main.app.dependency_overrides)
    main.app.dependency_overrides.update({
        get_access_tokens: lambda: tokens, get_auth_service: lambda: auth,
        get_user_service: lambda: user_service, get_storage_guard: lambda: guard,
    })
    monkeypatch.setattr(main, "get_storage_guard", lambda: guard)
    monkeypatch.setattr(statistics, "service", stats)
    monkeypatch.setattr(user, "service", user_service)
    monkeypatch.setattr(healthcheck, "db", db)
    monkeypatch.chdir(tmp_path)
    try:
        async with main.app.router.lifespan_context(main.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                yield SimpleNamespace(client=client, users=users, tokens=tokens, stats=stats, guard=guard, db=db)
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(previous)


def bearer(value: str) -> dict:
    return {"Authorization": f"Bearer {value}"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "data"), PRIVATE_REQUESTS)
async def test_anonymous_requests_are_rejected_before_storage_or_handlers(secured_api, method, path, data) -> None:
    state = secured_api
    response = await state.client.request(method, path, json=data)
    assert response.status_code == 401, response.text
    assert response.headers["www-authenticate"] == "Bearer"
    assert state.guard.snapshot().estimated_bytes == 0
    state.stats.create_session.assert_not_called()
    state.stats.delete_session.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "data"), PRIVATE_REQUESTS)
async def test_ingestion_key_cannot_read_export_or_manage(secured_api, method, path, data) -> None:
    state = secured_api
    response = await state.client.request(method, path, json=data, headers=bearer(state.tokens.settings.ingestion_key))
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_ingestion_requires_its_own_key_and_preserves_successful_contract(secured_api) -> None:
    state = secured_api
    for token in ["wrong", state.tokens.issue(state.users.records[ADMIN])]:
        response = await state.client.post("/api/statistics/page", json=PAGE, headers=bearer(token))
        assert response.status_code == 401
    assert state.guard.snapshot().estimated_bytes == 0
    headers = bearer(state.tokens.settings.ingestion_key)
    assert (await state.client.post("/api/statistics/page", json=PAGE, headers=headers)).status_code == 201
    assert (await state.client.post("/api/statistics/", json=SESSION, headers=headers)).status_code == 201


@pytest.mark.asyncio
async def test_login_issues_a_session_hides_password_and_upgrades_legacy_storage(secured_api) -> None:
    state = secured_api
    response = await state.client.post("/api/auth/sign-in", json={"email": "admin@example.com", "password": "admin-password"})
    assert response.status_code == 200, response.text
    session = response.json()
    assert "password" not in session
    assert session["expires_in"] == 43200
    assert response.headers["cache-control"] == "no-store"
    assert is_hashed_password(state.users.records[ADMIN]["password"])
    headers = bearer(session["access_token"])
    assert (await state.client.get("/api/statistics/", headers=headers)).status_code == 200
    users = await state.client.get("/api/user/", headers=headers)
    assert users.status_code == 200
    assert all("password" not in row for row in users.json())


@pytest.mark.asyncio
async def test_unknown_user_and_wrong_password_have_the_same_public_result(secured_api) -> None:
    client = secured_api.client
    unknown = await client.post("/api/auth/sign-in", json={"email": "missing@example.com", "password": "wrong"})
    wrong = await client.post("/api/auth/sign-in", json={"email": "admin@example.com", "password": "wrong"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


@pytest.mark.asyncio
async def test_regular_user_can_read_but_not_change_data(secured_api) -> None:
    state = secured_api
    headers = bearer(state.tokens.issue(state.users.records[READER]))
    for path in ["/api/statistics/", "/api/download/sessions", "/api/download/statistics"]:
        response = await state.client.get(path, headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
    assert (await state.client.get("/api/user/", headers=headers)).status_code == 403
    assert (await state.client.get("/api/healthcheck/storage", headers=headers)).status_code == 403
    assert (await state.client.delete(f"/api/statistics/{ADMIN}", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_role_changes_and_deletion_apply_to_existing_tokens(secured_api) -> None:
    state = secured_api
    headers = bearer(state.tokens.issue(state.users.records[ADMIN]))
    assert (await state.client.get("/api/healthcheck/storage", headers=headers)).status_code == 200
    state.users.records[ADMIN]["position"] = "regular"
    assert (await state.client.get("/api/healthcheck/storage", headers=headers)).status_code == 403
    del state.users.records[ADMIN]
    assert (await state.client.get("/api/statistics/", headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_password_change_invalidates_old_tokens_and_never_returns_password(secured_api) -> None:
    state = secured_api
    headers = bearer(state.tokens.issue(state.users.records[ADMIN]))
    data = {**state.users.records[ADMIN], "password": "changed-password"}
    response = await state.client.put(f"/api/user/{ADMIN}", json=data, headers=headers)
    assert response.status_code == 200, response.text
    assert "password" not in response.json()
    assert verify_password("changed-password", state.users.records[ADMIN]["password"])
    assert (await state.client.get("/api/statistics/", headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_new_accounts_store_a_hash_and_cannot_request_admin_role(secured_api) -> None:
    state = secured_api
    headers = bearer(state.tokens.issue(state.users.records[ADMIN]))
    response = await state.client.post("/api/user/", json={**CREATE_USER, "position": "admin"}, headers=headers)
    assert response.status_code == 201, response.text
    user = response.json()
    assert user["position"] == "regular"
    assert "password" not in user
    stored = state.users.records[user["id"]]["password"]
    assert is_hashed_password(stored)
    assert verify_password(CREATE_USER["password"], stored)


@pytest.mark.asyncio
async def test_login_and_reading_work_when_storage_budget_is_full(secured_api) -> None:
    state = secured_api
    state.db.allocated = state.guard.settings.max_bytes
    await state.guard.refresh()
    response = await state.client.post("/api/auth/sign-in", json={"email": "admin@example.com", "password": "admin-password"})
    assert response.status_code == 200
    assert state.users.records[ADMIN]["password"] == "admin-password"
    headers = bearer(response.json()["access_token"])
    assert (await state.client.get("/api/statistics/", headers=headers)).status_code == 200
    assert (await state.client.post("/api/statistics/page", json=PAGE,
                                   headers=bearer(state.tokens.settings.ingestion_key))).status_code == 507


@pytest.mark.asyncio
async def test_cors_preflight_and_health_ping_do_not_require_user_credentials(secured_api) -> None:
    state = secured_api
    response = await state.client.options("/api/statistics/page", headers={
        "Origin": "http://localhost:18082", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:18082"
    assert (await state.client.get("/api/healthcheck/")).status_code == 200


@pytest.mark.asyncio
async def test_administrator_deletions_return_empty_204_responses(secured_api) -> None:
    state = secured_api
    headers = bearer(state.tokens.issue(state.users.records[ADMIN]))
    for path in [f"/api/statistics/{ADMIN}", f"/api/user/{READER}"]:
        response = await state.client.delete(path, headers=headers)
        assert response.status_code == 204
        assert response.content == b""
