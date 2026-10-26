import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator


MAX_PAGE_SIZE = 100
MAX_SEARCH_LENGTH = 256
TEXT_PATTERN = r"^[^\x00]*$"
ACTION_TEXT_FIELDS = ("action_type", "event_type", "element_type", "element_name")


def literal_text(value: str) -> dict:
    # Treat punctuation as text; reject legacy arrays instead of matching an
    # arbitrary array member while projecting a different set of actions.
    return {"$regex": re.escape(value), "$options": "i", "$not": {"$type": "array"}}


class StatisticsFilter(BaseModel):
    begin_timestamp: Optional[datetime] = Field(default=None, description="start date")
    end_timestamp: Optional[datetime] = Field(default=None, description="stop date")
    student_id: Optional[int] = Field(default=None, description="student moodle id")
    student_name: Optional[str] = Field(default=None, max_length=MAX_SEARCH_LENGTH, pattern=TEXT_PATTERN, description="student FIO; case-insensitive literal substring")
    student_email: Optional[str] = Field(default=None, max_length=MAX_SEARCH_LENGTH, pattern=TEXT_PATTERN, description="student email; case-insensitive literal substring")
    course_title: Optional[str] = Field(default=None, max_length=MAX_SEARCH_LENGTH, pattern=TEXT_PATTERN, description="course; case-insensitive literal substring")
    action_type: Optional[str] = Field(default=None, max_length=MAX_SEARCH_LENGTH, pattern=TEXT_PATTERN, description="action type; case-insensitive literal substring")
    event_type: Optional[str] = Field(default=None, max_length=MAX_SEARCH_LENGTH, pattern=TEXT_PATTERN, description="event type; case-insensitive literal substring")
    element_type: Optional[str] = Field(default=None, max_length=MAX_SEARCH_LENGTH, pattern=TEXT_PATTERN, description="element type; case-insensitive literal substring")
    element_name: Optional[str] = Field(default=None, max_length=MAX_SEARCH_LENGTH, pattern=TEXT_PATTERN, description="element name; case-insensitive literal substring")

    @field_validator("begin_timestamp", "end_timestamp")
    @classmethod
    def utc_timestamp(cls, value):
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def action_query(self) -> dict:
        conditions = {field: literal_text(value) for field in ACTION_TEXT_FIELDS if (value := getattr(self, field))}
        dates = {}
        if self.begin_timestamp is not None:
            dates["$gte"] = self.begin_timestamp
        if self.end_timestamp is not None:
            dates["$lte"] = self.end_timestamp
        if dates:
            conditions["timestamp"] = {**dates, "$not": {"$type": "array"}}
        return conditions

    def mongo_query(self) -> dict:
        result = {}
        actions = self.action_query()
        if actions:
            result["actions"] = {"$elemMatch": actions}
        if self.student_id is not None:
            result["student_id"] = self.student_id
        for attribute, field in [("student_name", "student"), ("student_email", "email"), ("course_title", "course")]:
            if value := getattr(self, attribute):
                result[field] = literal_text(value)
        return result

    def action_projection(self) -> dict | None:
        conditions = self.action_query()
        if not conditions:
            return None
        clauses = []
        for field, condition in conditions.items():
            value = f"$$action.{field}"
            if "$regex" in condition:
                clauses.append({"$regexMatch": {
                    "input": {"$cond": [{"$eq": [{"$type": value}, "string"]}, value, ""]},
                    "regex": {"$literal": condition["$regex"]}, "options": condition["$options"],
                }})
            else:
                clauses.append({"$eq": [{"$type": value}, "date"]})
                clauses.extend({operator: [value, bound]} for operator, bound in condition.items() if operator in {"$gte", "$lte"})
        return {"$set": {"actions": {"$filter": {
            "input": {"$ifNull": ["$actions", []]}, "as": "action", "cond": {"$and": clauses},
        }}}}


class SessionFilter(StatisticsFilter):
    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=10, ge=1, le=MAX_PAGE_SIZE)

    def query(self) -> tuple[dict, dict[str, int]]:
        return self.mongo_query(), {"page": self.page, "pageSize": self.pageSize}
