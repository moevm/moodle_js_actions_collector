from unittest.mock import AsyncMock, Mock, MagicMock

import pytest
from bson import ObjectId

from src.core.modules.database.statistics import MongoPageRepo


@pytest.fixture
def metadata() -> dict:
    return {
        "page": "https://moodle.example/mod/page/view.php?id=7",
        "title": "Reading",
        "browser": "Mozilla/5.0 test browser",
        "window": {"width": 1200, "height": 800},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_html", [None, "<html>private legacy page</html>"])
async def test_create_record_saves_only_metadata(metadata: dict, legacy_html: str | None) -> None:
    record_id = ObjectId()
    client = Mock()
    client.sessions.insert_one = AsyncMock(return_value=Mock(inserted_id=record_id))
    client.sessions.find_one = AsyncMock(return_value={"_id": record_id, **metadata})
    payload = dict(metadata)
    if legacy_html is not None:
        payload["page_html"] = legacy_html

    result = await MongoPageRepo(client).create_record(payload)

    client.sessions.insert_one.assert_awaited_once_with(metadata)
    assert result == {"_id": str(record_id), **metadata}
    assert "page_html" not in result
    # An internal caller's input must not be mutated to remove a legacy field.
    if legacy_html is not None:
        assert payload["page_html"] == legacy_html


@pytest.mark.asyncio
async def test_export_requests_only_metadata_from_mongodb(metadata: dict) -> None:
    record_id = ObjectId()
    client = Mock()
    cursor = MagicMock()
    cursor.batch_size.return_value = cursor
    cursor.max_time_ms.return_value = cursor
    cursor.__aiter__.return_value = [{"_id": record_id, **metadata}]
    cursor.close = AsyncMock()
    client.sessions.find.return_value = cursor

    result = [row async for row in MongoPageRepo(client).iter_records()]

    # An inclusion projection excludes historical HTML before it enters RAM.
    client.sessions.find.assert_called_once_with(
        {}, {"page": 1, "browser": 1, "title": 1, "window": 1}
    )
    assert result == [{"_id": str(record_id), **metadata}]
    assert "page_html" not in result[0]
    cursor.close.assert_awaited_once()
