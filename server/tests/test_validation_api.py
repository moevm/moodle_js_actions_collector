import copy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote

import httpx
import pytest
from bson import BSON, ObjectId
from pymongo.errors import OperationFailure

from src.core.modules.database.statistics import MongoStatisticRepo
from src.core.modules.database.user import MongoUserRepo
from src.core.modules.service.statistics import StatisticsService
from src.core.modules.service.user import UserService
from src.models.constraints import BSON_INT64_MAX
from src.models.filter import MAX_PAGE, MAX_PAGE_SIZE, SessionFilter
from src.models.session_data import CreateSessionData
from tests.test_security_api import ADMIN, CREATE_USER, PAGE, SESSION, bearer, secured_api
from tests.test_storage_api import api as storage_api


BAD_IDS = ["not-an-object-id", "g" * 24, "0" * 23, "0" * 25, "a" * 23 + "\n", "Ｆ" * 24]
RECORD_ROUTES = [("GET", "statistics"), ("DELETE", "statistics"),
                 ("GET", "user"), ("PUT", "user"), ("DELETE", "user")]
UPDATE = {**CREATE_USER, "position": "regular"}


def admin_headers(state):
    return bearer(state.tokens.issue(state.users.records[ADMIN]))


@pytest.mark.asyncio
@pytest.mark.parametrize("record_id", BAD_IDS)
@pytest.mark.parametrize(("method", "resource"), RECORD_ROUTES)
async def test_bad_path_ids_are_422_before_record_operations(secured_api, monkeypatch, record_id, method, resource):
    from src.api.endpoints import statistics, user

    state = secured_api
    handlers = SimpleNamespace(get_session=AsyncMock(), delete_session=AsyncMock(),
                               get_user=AsyncMock(), update_user=AsyncMock(), delete_user=AsyncMock())
    monkeypatch.setattr(statistics, "service", handlers)
    monkeypatch.setattr(user, "service", handlers)
    before = copy.deepcopy(state.users.records)
    response = await state.client.request(method, f"/api/{resource}/{quote(record_id, safe='')}",
        headers=admin_headers(state), json=UPDATE if method == "PUT" else None)
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"][:1] == ["path"]
    assert state.users.records == before
    for handler in vars(handlers).values():
        handler.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "resource"), RECORD_ROUTES)
@pytest.mark.parametrize("record_id", ["f" * 24, "ABCDEFABCDEFABCDEFABCDEF"])
async def test_valid_unknown_ids_are_404_through_real_services_and_repos(secured_api, monkeypatch, method, resource, record_id):
    from src.api.endpoints import statistics, user

    database = Mock(users=AsyncMock(), statistics=AsyncMock(), collector_settings=AsyncMock())
    database.collector_settings.find_one.return_value = {"user_id": ObjectId(ADMIN)}

    async def find_user(query, **kwargs):
        return {"_id": ObjectId(ADMIN)} if query.get("position") == "admin" else None

    database.users.find_one.side_effect = find_user
    database.users.find_one_and_update.return_value = None
    database.users.delete_one.return_value = SimpleNamespace(deleted_count=0)
    database.statistics.find_one.return_value = None
    database.statistics.delete_one.return_value = SimpleNamespace(deleted_count=0)
    monkeypatch.setattr(user, "service", UserService(MongoUserRepo(database)))
    monkeypatch.setattr(statistics, "service", StatisticsService(MongoStatisticRepo(database), None))
    response = await secured_api.client.request(method, f"/api/{resource}/{record_id}",
        headers=admin_headers(secured_api), json={**UPDATE, "password": None} if method == "PUT" else None)
    assert response.status_code == 404, response.text
    assert response.json()["detail"] in ("Session not found", "User not found")


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [
    {"page": 0}, {"page": -1}, {"page": MAX_PAGE + 1}, {"page": 10**100}, {"page": "1.5"},
    {"pageSize": 0}, {"pageSize": -1}, {"pageSize": MAX_PAGE_SIZE + 1}, {"pageSize": "invalid"},
])
async def test_bad_pagination_is_422_before_database_queries(secured_api, params):
    response = await secured_api.client.get("/api/statistics/", params=params, headers=admin_headers(secured_api))
    assert response.status_code == 422, response.text
    secured_api.stats.get_all_sessions.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [-1, BSON_INT64_MAX + 1, 10**100, "invalid"])
@pytest.mark.parametrize("path", ["/api/statistics/", "/api/download/statistics"])
async def test_student_filter_ids_fit_bson_int64(secured_api, value, path):
    response = await secured_api.client.get(path, params={"student_id": value}, headers=admin_headers(secured_api))
    assert response.status_code == 422, response.text
    secured_api.stats.get_all_sessions.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [
    {"begin_timestamp": "not-a-date"},
    {"begin_timestamp": "0001-01-01T00:00:00+14:00"},
    {"end_timestamp": "9999-12-31T23:59:59-12:00"},
    {"begin_timestamp": "2026-10-28T00:00:00Z", "end_timestamp": "2026-10-27T00:00:00Z"},
])
@pytest.mark.parametrize("path", ["/api/statistics/", "/api/download/statistics"])
async def test_bad_date_ranges_and_utc_overflows_are_422(secured_api, params, path):
    secured_api.stats.iter_sessions = Mock(side_effect=AssertionError("Invalid query reached export"))
    response = await secured_api.client.get(path, params=params, headers=admin_headers(secured_api))
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"][0] == "query"
    secured_api.stats.get_all_sessions.assert_not_awaited()
    secured_api.stats.iter_sessions.assert_not_called()


@pytest.mark.asyncio
async def test_valid_bounds_equal_dates_and_timezone_order_are_preserved(secured_api):
    response = await secured_api.client.get("/api/statistics/", headers=admin_headers(secured_api), params={
        "page": MAX_PAGE, "pageSize": MAX_PAGE_SIZE, "student_id": BSON_INT64_MAX,
        "begin_timestamp": "2026-10-27T10:00:00+03:00", "end_timestamp": "2026-10-27T07:00:00Z",
    })
    assert response.status_code == 200, response.text
    filters = secured_api.stats.get_all_sessions.await_args.args[0]
    assert filters.begin_timestamp == filters.end_timestamp == datetime(2026, 10, 27, 7)
    query, pagination = filters.query()
    offset = (pagination["page"] - 1) * pagination["pageSize"]
    assert 0 <= offset <= BSON_INT64_MAX
    BSON.encode({"skip": offset, "student_id": query["student_id"]})
    assert SessionFilter(student_id=0).mongo_query() == {"student_id": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("record_id", BAD_IDS)
async def test_bad_page_references_in_event_bodies_are_422(secured_api, record_id):
    response = await secured_api.client.post("/api/statistics/", json={**SESSION, "session_id": record_id},
        headers=bearer(secured_api.tokens.settings.ingestion_key))
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", "session_id"]
    secured_api.stats.create_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("student_id", -1), ("student_id", BSON_INT64_MAX + 1),
    ("timestamp", "0001-01-01T00:00:00+14:00"), ("timestamp", "9999-12-31T23:59:59-12:00")])
async def test_bad_ingestion_numbers_and_utc_overflows_are_422(secured_api, field, value):
    body = {**SESSION}
    if field == "timestamp":
        body["actions"] = [{"timestamp": value, "element_type": "button", "element_name": "save",
                            "action_type": "interactions", "event_type": "mousedown", "element_html": "<button>"}]
    else:
        body[field] = value
    response = await secured_api.client.post("/api/statistics/", json=body,
        headers=bearer(secured_api.tokens.settings.ingestion_key))
    assert response.status_code == 422, response.text
    secured_api.stats.create_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/statistics/not-an-object-id", "/api/user/not-an-object-id"])
async def test_anonymous_bad_ids_still_require_authentication(secured_api, path):
    assert (await secured_api.client.get(path)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["statistics", "page"])
async def test_database_failures_are_safe_503_without_payloads_in_logs(storage_api, resource, monkeypatch, caplog):
    from tests.test_storage_api import SESSION as FULL_SESSION

    client, database, _ = storage_api
    marker = "private-payload-marker"
    if resource == "statistics":
        monkeypatch.setattr(database.statistics, "insert_one", AsyncMock(side_effect=OperationFailure(marker)))
        body, path = {**FULL_SESSION, "student": marker}, "/api/statistics/"
    else:
        monkeypatch.setattr(database.sessions, "insert_one", AsyncMock(side_effect=OperationFailure(marker)))
        body, path = {**PAGE, "title": marker}, "/api/statistics/page"
    response = await client.post(path, json=body)
    assert response.status_code == 503, response.text
    assert marker not in response.text
    assert marker not in caplog.text


@pytest.mark.asyncio
async def test_valid_utc_and_default_timestamps_reach_storage(storage_api):
    from tests.test_storage_api import SESSION as FULL_SESSION

    client, database, _ = storage_api
    explicit = {**FULL_SESSION["actions"][0], "timestamp": "2026-10-27T10:00:00+03:00"}
    default = {key: value for key, value in explicit.items() if key != "timestamp"}
    response = await client.post("/api/statistics/", json={**FULL_SESSION, "actions": [explicit, default]})
    assert response.status_code == 201, response.text
    stored = next(iter(database.statistics.records.values()))
    assert stored["actions"][0]["timestamp"] == datetime(2026, 10, 27, 7)
    assert isinstance(stored["actions"][1]["timestamp"], datetime)


def test_documented_ingestion_examples_satisfy_the_new_constraints():
    for example in CreateSessionData.model_json_schema()["examples"]:
        CreateSessionData.model_validate(example)


@pytest.mark.asyncio
async def test_internal_response_model_errors_are_not_disguised_as_client_validation(secured_api):
    import main

    secured_api.stats.get_session.return_value = {"invalid_server_data": True}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.get(f"/api/statistics/{ADMIN}", headers=admin_headers(secured_api))
    assert response.status_code == 500


def test_openapi_documents_id_and_numeric_constraints():
    import main

    schema = main.app.openapi()
    for resource in ("user", "statistics"):
        for operation in schema["paths"][f"/api/{resource}/{{{'user_id' if resource == 'user' else 'session_id'}}}"].values():
            identifier = next(param for param in operation["parameters"] if param["in"] == "path")["schema"]
            assert identifier["pattern"] == r"^[0-9a-fA-F]{24}$"
            assert identifier["minLength"] == identifier["maxLength"] == 24
    params = {item["name"]: item["schema"] for item in schema["paths"]["/api/statistics/"]["get"]["parameters"]}
    assert params["page"]["maximum"] == MAX_PAGE
    assert params["pageSize"]["maximum"] == MAX_PAGE_SIZE
    assert schema["components"]["schemas"]["CreateSessionData"]["properties"]["session_id"]["maxLength"] == 24
