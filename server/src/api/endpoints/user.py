import logging
from typing import List

from fastapi import APIRouter, HTTPException, Body, Depends
from fastapi.encoders import jsonable_encoder
from pymongo.errors import PyMongoError
from starlette import status
from starlette.responses import Response

from src.core.modules.service.errors import (
    ProtectedAdminError, UserAlreadyExistsError, UserEmptyDataError,
    UserManagementUnavailableError, UserNotFoundError,
)
from src.depends import get_user_service, require_storage_capacity, STORAGE_WRITE_RESPONSES, require_admin
from src.models.user import User, UpdateUser, CreateUser
from src.models.constraints import MongoObjectId

router = APIRouter(dependencies=[Depends(require_admin)])

service = get_user_service()

MANAGEMENT_RESPONSES = {
    409: {"description": "Email is already in use, or the protected administrator cannot be removed/demoted"},
    503: {"description": "User management or storage monitoring is unavailable"},
}
ADMIN_PROTECTION_DESCRIPTION = (
    "Before the first deletion or demotion, the existing administrator with the lowest MongoDB _id "
    "is permanently protected. Its reference is stored in collector_settings/protected-administrator "
    "and survives API restarts. This account cannot be deleted or demoted even when other admins exist; "
    "its name, email and password can be changed. Other administrators can be deleted or demoted. "
    "If the protected account is manually removed from MongoDB, destructive user operations stop: "
    "restore that account and its admin role from backup instead of deleting the guard reference."
)


def user_error(error: Exception) -> HTTPException:
    headers = {"Cache-Control": "no-store"}
    if isinstance(error, UserNotFoundError):
        return HTTPException(404, "User not found", headers=headers)
    if isinstance(error, UserEmptyDataError):
        return HTTPException(400, "Empty user update", headers=headers)
    if isinstance(error, UserAlreadyExistsError):
        return HTTPException(409, {"code": "email_conflict", "message": "User email is already in use"}, headers=headers)
    if isinstance(error, ProtectedAdminError):
        return HTTPException(409, {
            "code": "protected_administrator",
            "message": "The protected administrator cannot be deleted or demoted; other fields can be updated",
        }, headers=headers)
    # Driver messages can contain addresses, queries and index contents.
    logging.error("User operation failed: %s (cause: %s)", type(error).__name__, type(error.__cause__).__name__)
    if isinstance(error, (UserManagementUnavailableError, PyMongoError)):
        return HTTPException(503, {"code": "user_management_unavailable", "message": "User management is unavailable"}, headers=headers)
    return HTTPException(500, "User operation failed", headers=headers)


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
    response_description="List all users",
    response_model=List[User],
    response_model_by_alias=False
)
async def get_all_users():
    try:
        return await service.get_all_users()
    except Exception as error:
        raise user_error(error) from error


@router.get(
    "/{user_id}",
    status_code=status.HTTP_200_OK,
    response_description="Retrieve a user",
    responses={404: {"description": "A valid ID has no matching user"}},
    response_model=User,
    response_model_by_alias=False,
)
async def get_user(user_id: MongoObjectId):
    try:
        return await service.get_user(user_id)
    except Exception as error:
        raise user_error(error) from error


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_description="Add new user",
    dependencies=[Depends(require_storage_capacity)],
    responses={**STORAGE_WRITE_RESPONSES, **MANAGEMENT_RESPONSES},
    response_model=User,
    response_model_by_alias=False,
)
async def create_user(user_data: CreateUser = Body()):
    try:
        user = jsonable_encoder(user_data)
        return await service.create_user(user)
    except Exception as error:
        raise user_error(error) from error


@router.put(
    "/{user_id}",
    status_code=status.HTTP_200_OK,
    response_description="Update user",
    description=ADMIN_PROTECTION_DESCRIPTION,
    dependencies=[Depends(require_storage_capacity)],
    responses={**STORAGE_WRITE_RESPONSES, **MANAGEMENT_RESPONSES,
               404: {"description": "A valid ID has no matching user"}},
    response_model_by_alias=False,
    response_model=User
)
async def update_user(user_id: MongoObjectId, user_data: UpdateUser = Body()):
    try:
        return await service.update_user(user_id, user_data)
    except Exception as error:
        raise user_error(error) from error


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_description="Delete a user",
    description=ADMIN_PROTECTION_DESCRIPTION,
    responses={**MANAGEMENT_RESPONSES, 404: {"description": "A valid ID has no matching user"}},
)
async def delete_user(user_id: MongoObjectId):
    try:
        res = await service.delete_user(user_id)
        if res.deleted_count == 1:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as error:
        raise user_error(error) from error
