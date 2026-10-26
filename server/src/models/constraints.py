from datetime import datetime, timezone
from typing import Annotated

from pydantic import Field


BSON_INT64_MAX = (1 << 63) - 1
MongoObjectId = Annotated[str, Field(min_length=24, max_length=24, pattern=r"^[0-9a-fA-F]{24}$")]
MoodleUserId = Annotated[int, Field(ge=0, le=BSON_INT64_MAX)]


def utc_datetime(value: datetime) -> datetime:
    """Return naive UTC suitable for BSON, including at Python's date limits."""
    if value.tzinfo is None:
        return value
    try:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    except (OverflowError, ValueError) as error:
        raise ValueError("Timestamp falls outside the supported UTC datetime range") from error
