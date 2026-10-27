import pymongo
from fastapi import APIRouter, HTTPException, Depends
from starlette import status

from src.depends import db, get_storage_guard, require_admin
from src.core.storage import DatabaseStorageGuard, StorageSnapshot

router = APIRouter()


@router.get("/storage", response_description="Cached MongoDB storage budget status", dependencies=[Depends(require_admin)])
async def storage_status(guard: DatabaseStorageGuard = Depends(get_storage_guard)) -> StorageSnapshot:
    return guard.snapshot()


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
    response_description="Healthcheck ping",
    response_model_by_alias=False
)
async def healthcheck():
    try:
        with pymongo.timeout(5):
            return await db.command("ping")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"message": "Database instance is unhealthy", "error": str(e)})
