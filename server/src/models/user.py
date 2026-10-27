import uuid
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field
from enum import Enum


class Role(str, Enum):
    admin = "admin"
    regular = "regular"


class User(BaseModel):
    id: str = Field(default_factory=uuid.uuid4, alias="_id")
    name: str = Field(...)
    surname: str = Field(...)
    lastname: str = Field(...)
    email: EmailStr = Field(...)
    position: Role = Field(...)

    class Config:
        populate_by_field_name = True
        json_schema_extra = {
            "example": {
                "id": str(uuid.uuid4()),
                "name": "Иван",
                "surname": "Иванов",
                "lastname": "Иванович",
                "email": "iiivanov@edu.ru",
                "position": Role.regular,
            }
        }


class UpdateUser(BaseModel):
    name: Optional[str]
    surname: Optional[str]
    lastname: Optional[str]
    email: Optional[EmailStr]
    position: Optional[Role]
    password: Optional[str] = Field(default=None, min_length=1, max_length=1024)

    class Config:
        populate_by_field_name = True
        json_schema_extra = {
            "example": {
                "name": "Иван",
                "surname": "Иванов",
                "lastname": "Иванович",
                "email": "iiivanov@edu.ru",
                "position": Role.regular,
                "password": "sdfsdfwgesdgcx"
            }
        }


class CreateUser(BaseModel):
    name: str = Field(...)
    surname: str = Field(...)
    lastname: str = Field(...)
    email: EmailStr = Field(...)
    password: str = Field(..., min_length=1, max_length=1024)

    class Config:
        populate_by_field_name = True
        json_schema_extra = {
            "example": {
                "name": "Иван",
                "surname": "Иванов",
                "lastname": "Иванович",
                "email": "iiivanov@edu.ru",
                "password": "sdfsdfwgesdgcx"
            }
        }


class SignInData(BaseModel):
    email: EmailStr = Field(...)
    password: str = Field(..., min_length=1, max_length=1024)

    class Config:
        populate_by_field_name = True
        json_schema_extra = {
            "example": {
                "email": "iiivanov@edu.ru",
                "password": "sdfsdfwgesdgcx"
            }
        }


class AuthSession(User):
    model_config = {"json_schema_extra": {}}
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
