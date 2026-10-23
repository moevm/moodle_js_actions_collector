import pytest

from src.models.session_data import CreatePageData, PageData


@pytest.fixture
def metadata() -> dict:
    return {
        "page": "https://moodle.example/mod/page/view.php?id=7",
        "browser": "Mozilla/5.0 test browser",
        "title": "Reading",
        "window": {"width": 1200, "height": 800},
    }


@pytest.mark.parametrize("legacy_html", [None, "<html>private legacy page</html>"])
def test_page_registration_accepts_metadata_and_discards_legacy_html(
    metadata: dict, legacy_html: str | None
) -> None:
    payload = dict(metadata)
    if legacy_html is not None:
        payload["page_html"] = legacy_html

    saved = CreatePageData.model_validate(payload).model_dump(mode="json")

    assert saved == metadata
    assert "page_html" not in saved


def test_page_response_does_not_expose_historical_html(metadata: dict) -> None:
    record = PageData.model_validate({
        "_id": "60d5ec49f1a4a21f6c8b4567",
        **metadata,
        "page_html": "<html>private historical page</html>",
    }).model_dump(mode="json", by_alias=True)

    assert record == {"_id": "60d5ec49f1a4a21f6c8b4567", **metadata}


@pytest.mark.parametrize("model", [CreatePageData, PageData])
def test_page_schema_does_not_advertise_html(model: type[CreatePageData] | type[PageData]) -> None:
    schema = model.model_json_schema()

    assert "page_html" not in schema["properties"]
    assert "page_html" not in schema.get("required", [])
