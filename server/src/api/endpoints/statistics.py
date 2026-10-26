from typing import List

from fastapi import APIRouter, HTTPException, Body, Depends
from fastapi.encoders import jsonable_encoder
from starlette import status

from starlette.responses import Response

from src.api.exports import json_export

from src.core.modules.service.errors import SessionNotFoundError
from src.depends import (
    get_statistics_service, require_storage_capacity, STORAGE_WRITE_RESPONSES,
    require_current_user, require_admin, require_ingestion_key,
)
from src.models.filter import SessionFilter, StatisticsFilter
from src.models.session_data import SessionData, CreateSessionData
from src.models.session_data import CreatePageData

router = APIRouter()
download_router = APIRouter(dependencies=[Depends(require_current_user)])
service = get_statistics_service()


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
    response_description="Get statistics",
    dependencies=[Depends(require_current_user)],
    response_model=List,
    response_model_by_alias=False
)
async def get_all_sessions(params: SessionFilter = Depends()):
    try:
        return await service.get_all_sessions(params)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/{session_id}",
    status_code=status.HTTP_200_OK,
    response_description="Get session statistic",
    dependencies=[Depends(require_current_user)],
    response_model=SessionData,
    response_model_by_alias=False
)
async def get_session_by_id(session_id: str):
    try:
        return await service.get_session(session_id)
    except Exception as e:
        if isinstance(e, SessionNotFoundError):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        else:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_description="Add new session",
    dependencies=[Depends(require_ingestion_key), Depends(require_storage_capacity)],
    responses=STORAGE_WRITE_RESPONSES,
    response_model=SessionData,
    response_model_by_alias=False
)
async def create_session(session: CreateSessionData = Body()):
    try:
        session = jsonable_encoder(session)
        return await service.create_session(session)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_description="Delete a session statistic",
    dependencies=[Depends(require_admin)],
)
async def delete_session(session_id: str):
    try:
        res = await service.delete_session(session_id)
        if res.deleted_count == 1:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        if isinstance(e, SessionNotFoundError):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Deleting session {session_id} failed: {str(e)}"
            )
        else:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@download_router.get(
    "/statistics",
    response_description="Stream all statistics matching the filters, without table pagination",
    responses={429: {"description": "Another export is running"}, 503: {"description": "Export unavailable"}}
)
async def download_data(params: StatisticsFilter = Depends()):
    return await json_export(service.iter_sessions(params), filename="data.json", with_total=True)


@router.post(
    "/page",
    status_code=status.HTTP_201_CREATED,
    response_description="Register page metadata without HTML",
    dependencies=[Depends(require_ingestion_key), Depends(require_storage_capacity)],
    responses=STORAGE_WRITE_RESPONSES,
    response_model=str,
    response_model_by_alias=False
)
async def create_page(page: CreatePageData = Body()):
    try:
        page = jsonable_encoder(page)
        created_page = await service.create_page(page)
        return created_page['_id']
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@download_router.get(
    "/sessions",
    response_description="Stream page metadata without HTML",
    responses={429: {"description": "Another export is running"}, 503: {"description": "Export unavailable"}}
)
async def download_sessions():
    return await json_export(service.iter_pages(), filename="sessions.json")
