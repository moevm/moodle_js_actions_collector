import re
from datetime import datetime, timezone

import pytest

from src.models.filter import StatisticsFilter
from tests.test_security_api import ADMIN, bearer, secured_api


@pytest.mark.parametrize("text", ["answer[0]", "a+b", "(", ".", "^mousedown$", r"a\b", "$value", "Имя [Тест]"])
def test_text_filters_are_literal_in_both_query_and_action_projection(text):
    filters = StatisticsFilter(element_name=text, student_email=text)
    query = filters.mongo_query()
    condition = query["actions"]["$elemMatch"]["element_name"]
    assert re.fullmatch(condition["$regex"], text, flags=re.IGNORECASE)
    assert condition["$regex"] == re.escape(text)
    assert query["email"]["$regex"] == condition["$regex"]
    expression = filters.action_projection()["$set"]["actions"]["$filter"]["cond"]["$and"][0]["$regexMatch"]
    assert expression["regex"]["$literal"] == condition["$regex"]
    assert expression["options"] == condition["$options"] == "i"


def test_filters_share_one_action_match_and_utc_bounds():
    filters = StatisticsFilter(element_name="answer[0]", event_type="mousedown",
                               begin_timestamp=datetime(2026, 10, 27, tzinfo=timezone.utc))
    same_action = filters.mongo_query()["actions"]["$elemMatch"]
    assert set(same_action) == {"event_type", "element_name", "timestamp"}
    assert same_action["timestamp"]["$gte"].tzinfo is None
    clauses = filters.action_projection()["$set"]["actions"]["$filter"]["cond"]["$and"]
    assert {"$gte": ["$$action.timestamp", filters.begin_timestamp]} in clauses


def test_unfiltered_actions_need_no_projection_and_zero_id_is_not_ignored():
    assert StatisticsFilter(student_name="Test").action_projection() is None
    assert StatisticsFilter(student_id=0).mongo_query() == {"student_id": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/statistics/", "/api/download/statistics"])
@pytest.mark.parametrize("text", ["x" * 257, "answer\0name"])
async def test_bad_text_filters_are_rejected_as_http_422_before_reading(secured_api, path, text):
    state = secured_api
    response = await state.client.get(path, params={"element_name": text},
        headers=bearer(state.tokens.issue(state.users.records[ADMIN])))
    assert response.status_code == 422, response.text
    state.stats.get_all_sessions.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["(", "x" * 256])
async def test_literal_parenthesis_and_maximum_text_length_are_valid_http_queries(secured_api, text):
    state = secured_api
    response = await state.client.get("/api/statistics/", params={"element_name": text},
        headers=bearer(state.tokens.issue(state.users.records[ADMIN])))
    assert response.status_code == 200, response.text
