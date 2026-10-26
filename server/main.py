import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.api import api_router
from src.core.storage import StorageWriteRejected
from src.depends import get_storage_guard


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    guard = get_storage_guard()
    await guard.start()
    try:
        yield
    finally:
        await guard.stop()


app = FastAPI(lifespan=lifespan)


@app.exception_handler(StorageWriteRejected)
async def storage_write_rejected(request: Request, error: StorageWriteRejected) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"detail": str(error), "code": error.code},
        headers={"Retry-After": str(error.retry_after)},
    )


app.include_router(
    api_router,
    prefix="/api",
    tags=["api"],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:18082").split(",") if x.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
    )
