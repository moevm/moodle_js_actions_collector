import copy
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from bson import ObjectId

from src.core.modules.database.statistics import MongoPageRepo, MongoStatisticRepo
from src.core.modules.service.statistics import StatisticsService
from src.core.storage import DatabaseStorageGuard, StorageSettings


PAGE = {
    "page": "https://moodle.example/mod/page/view.php?id=7", "title": "Reading",
    "browser": "Mozilla/5.0", "window": {"width": 1200, "height": 800},
}
SESSION = {
    "student_id": 7, "student": "Test Student", "email": "student@example.com",
    "course": "Test course", "tabID": "test-tab", "url": PAGE["page"],
    "session_id": "60d5ec49f1a4a21f6c8b4567",
    "actions": [{
        "timestamp": "2026-10-23T10:00:00Z", "element_type": "button", "element_name": "save",
        "action_type": "interactions", "event_type": "mousedown", "element_html": "<button>",
    }],
}
USER = {
    "name": "Test", "surname": "Student", "lastname": "Example",
    "email": "student@example.com", "password": "test-password",
}


class Collection:
    def __init__(self) -> None:
        self.records: dict[ObjectId, dict] = {}

    async def insert_one(self, data: dict) -> SimpleNamespace:
        record_id = ObjectId()
        self.records[record_id] = {"_id": record_id, **copy.deepcopy(data)}
        return SimpleNamespace(inserted_id=record_id)

    async def find_one(self, query: dict, projection: dict | None = None) -> dict | None:
        record = next((r for r in self.records.values() if all(r[k] == v for k, v in query.items())), None)
        return copy.deepcopy(record)

    async def delete_one(self, query: dict) -> SimpleNamespace:
        deleted = self.records.pop(query["_id"], None)
        return SimpleNamespace(deleted_count=int(deleted is not None))


class Database:
    def __init__(self) -> None:
        self.allocated = 0
        self.statistics, self.sessions = Collection(), Collection()
        self.unavailable = False
        self.checks = 0

    async def command(self, command: str, **kwargs: object) -> dict:
        self.checks += 1
        if self.unavailable:
            raise ConnectionError("Storage check unavailable")
        return {"totalSize": self.allocated}


@pytest_asyncio.fixture
async def api(monkeypatch: pytest.MonkeyPatch):
    # Import the production app, but route database operations to an isolated
    # in-memory test double. No existing MongoDB or Moodle installation is used.
    monkeypatch.setenv("MONGODB_DATABASE", "collector-storage-tests")
    import main
    from src.api.endpoints import statistics
    from src.depends import get_storage_guard, require_current_user, get_access_tokens
    from src.models.user import User

    db = Database()
    guard = DatabaseStorageGuard(db, StorageSettings(max_bytes=10_000_000))
    monkeypatch.setattr(main, "get_storage_guard", lambda: guard)
    main.app.dependency_overrides[get_storage_guard] = lambda: guard
    main.app.dependency_overrides[require_current_user] = lambda: User(
        _id="60d5ec49f1a4a21f6c8b4567", name="Test", surname="Admin", lastname="Test",
        email="admin@example.com", position="admin",
    )
    monkeypatch.setattr(statistics, "service", StatisticsService(MongoStatisticRepo(db), MongoPageRepo(db)))
    try:
        async with main.app.router.lifespan_context(main.app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=main.app), base_url="http://test",
                headers={"Authorization": f"Bearer {get_access_tokens().settings.ingestion_key}"},
            ) as client:
                yield client, db, guard
    finally:
        main.app.dependency_overrides.pop(get_storage_guard, None)
        main.app.dependency_overrides.pop(require_current_user, None)


@pytest.mark.asyncio
async def test_normal_ingestion_preserves_page_and_event_contracts(api) -> None:
    client, db, guard = api
    page = await client.post("/api/statistics/page", json=PAGE)
    assert page.status_code == 201, page.text
    record_id = page.json()
    assert ObjectId.is_valid(record_id)
    batch = await client.post("/api/statistics/", json={**SESSION, "session_id": record_id})
    assert batch.status_code == 201, batch.text
    assert batch.json()["session_id"] == record_id
    assert len(db.sessions.records) == len(db.statistics.records) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "url", "payload"), [
    ("POST", "/api/statistics/page", PAGE),
    ("POST", "/api/statistics/", SESSION),
    ("POST", "/api/user/", USER),
    ("PUT", "/api/user/60d5ec49f1a4a21f6c8b4567", {**USER, "position": "regular"}),
])
async def test_full_database_rejects_all_api_insert_update_routes(api, method, url, payload) -> None:
    client, db, guard = api
    db.allocated = guard.settings.max_bytes
    await guard.refresh()
    response = await client.request(method, url, json=payload)
    assert response.status_code == 507, response.text
    assert response.json()["code"] == "storage_limit_reached"
    assert response.headers["retry-after"] == "5"
    assert not db.statistics.records
    assert not db.sessions.records


@pytest.mark.asyncio
async def test_storage_status_is_cached_and_full_database_still_allows_read_and_delete(api) -> None:
    client, db, guard = api
    page = await client.post("/api/statistics/page", json=PAGE)
    batch = await client.post("/api/statistics/", json={**SESSION, "session_id": page.json()})
    record_id = batch.json()["id"]
    db.allocated = guard.settings.max_bytes
    await guard.refresh()
    checks = db.checks
    status = await client.get("/api/healthcheck/storage")
    assert db.checks == checks
    assert status.status_code == 200
    assert status.json()["allocated_bytes"] == guard.settings.max_bytes
    assert not status.json()["accepting_writes"]
    assert (await client.get(f"/api/statistics/{record_id}")).status_code == 200
    assert (await client.delete(f"/api/statistics/{record_id}")).status_code == 204


@pytest.mark.asyncio
async def test_failed_storage_check_returns_503_not_false_success(api) -> None:
    client, db, guard = api
    db.unavailable = True
    await guard.refresh()
    response = await client.post("/api/statistics/page", json=PAGE)
    assert response.status_code == 503, response.text
    assert response.json()["code"] == "storage_check_unavailable"
    assert not db.sessions.records


@pytest.mark.asyncio
async def test_ingestion_resumes_after_the_measured_allocation_is_below_limit(api) -> None:
    client, db, guard = api
    db.allocated = guard.settings.max_bytes
    await guard.refresh()
    assert (await client.post("/api/statistics/page", json=PAGE)).status_code == 507
    db.allocated = 0
    await guard.refresh()
    assert (await client.post("/api/statistics/page", json=PAGE)).status_code == 201


@pytest.mark.asyncio
async def test_increasing_configured_budget_preserves_data_and_resumes_ingestion(api) -> None:
    import main
    from src.depends import get_storage_guard

    client, db, guard = api
    original = await client.post("/api/statistics/page", json=PAGE)
    assert original.status_code == 201
    original_id = ObjectId(original.json())
    db.allocated = guard.settings.max_bytes
    await guard.refresh()
    assert (await client.post("/api/statistics/page", json=PAGE)).status_code == 507

    replacement = DatabaseStorageGuard(db, StorageSettings.from_env({"COLLECTOR_DB_MAX_SIZE": "20MB"}))
    await replacement.refresh()
    main.app.dependency_overrides[get_storage_guard] = lambda: replacement
    assert (await client.post("/api/statistics/page", json=PAGE)).status_code == 201
    assert original_id in db.sessions.records
