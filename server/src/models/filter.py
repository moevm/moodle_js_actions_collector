from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SessionFilter(BaseModel):
    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=10, ge=-1)
    begin_timestamp: Optional[datetime] = Field(default=None, description="start date")
    end_timestamp: Optional[datetime] = Field(default=None, description="stop date")
    student_id: Optional[int] = Field(default=None, description="student moodle id")
    student_name: Optional[str] = Field(default=None, description="student FIO")
    student_email: Optional[str] = Field(default=None, description="student email")
    course_title: Optional[str] = Field(default=None, description="name of the course")
    action_type: Optional[str] = Field(default=None, description="action type")
    event_type: Optional[str] = Field(default=None, description="event type")
    element_type: Optional[str] = Field(default=None, description="element type")
    element_name: Optional[str] = Field(default=None, description="element name")


    @field_validator("begin_timestamp", "end_timestamp")
    @classmethod
    def utc_timestamp(cls, value):
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @field_validator("pageSize")
    @classmethod
    def valid_page_size(cls, value):
        if value == 0:
            raise ValueError("pageSize must be positive or -1")
        return value

    def query(self):
        filter_dict = {}
        action_filter = {}
        pages = {
            'page': self.page,
            'pageSize': self.pageSize
        }
        if self.begin_timestamp or self.end_timestamp:
            timestamp_filter = {}
            if self.begin_timestamp:
                timestamp_filter['$gte'] = self.begin_timestamp
            if self.end_timestamp:
                timestamp_filter['$lte'] = self.end_timestamp
            if timestamp_filter:
                action_filter['timestamp'] = timestamp_filter

        if self.action_type:
            action_filter['action_type'] = {'$regex': self.action_type, '$options': 'i'}
        if self.event_type:
            action_filter['event_type'] = {'$regex': self.event_type, '$options': 'i'}
        if self.element_type:
            action_filter['element_type'] = {'$regex': self.element_type, '$options': 'i'}
        if self.element_name:
            action_filter['element_name'] = {'$regex': self.element_name, '$options': 'i'}

        if action_filter:
            filter_dict['actions'] = {'$elemMatch': action_filter}

        if self.student_id:
            filter_dict['student_id'] = self.student_id
        if self.student_name:
            filter_dict['student'] = {'$regex': self.student_name, '$options': 'i'}
        if self.student_email:
            filter_dict['email'] = {'$regex': self.student_email, '$options': 'i'}
        if self.course_title:
            filter_dict['course'] = {'$regex': self.course_title, '$options': 'i'}

        return filter_dict, pages