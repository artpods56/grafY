import asyncio
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

from grafy_api.app_state import get_resources


class HealthResponse(BaseModel):
    status: Literal["ok"]


def health() -> HealthResponse:
    return HealthResponse(status="ok")


async def readiness(request: Request) -> HealthResponse:
    try:
        async with asyncio.timeout(3.0):
            resources = get_resources(request.app)

            async with resources.database.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Service unavailable",
        ) from exc

    return HealthResponse(status="ok")
