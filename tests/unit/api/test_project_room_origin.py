from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException, WebSocket

from grafy_api.services.application import build_app_identity
from grafy_api.settings import Settings
from grafy_api.v1.routes.collaboration.views import _require_websocket_origin
from grafy_persistence.database import create_database
from grafy_shared.config import AppConfig


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("http://localhost:3000", True),
        ("http://localhost:3001", True),
        ("http://localhost:3002", False),
        (None, False),
    ],
)
async def test_project_room_requires_a_trusted_browser_origin(
    origin: str | None, allowed: bool
) -> None:
    settings = Settings(
        app=AppConfig(
            public_origin="http://localhost:3000",
            cors_origins="http://localhost:3001",
        ),
    )
    database = create_database("sqlite+aiosqlite:///:memory:")
    try:
        app = FastAPI()
        app.state.identity = build_app_identity(settings, database)
        headers = [] if origin is None else [(b"origin", origin.encode())]
        websocket = WebSocket(
            {"type": "websocket", "app": app, "headers": headers},
            receive=AsyncMock(),
            send=AsyncMock(),
        )

        if allowed:
            _require_websocket_origin(websocket)
        else:
            with pytest.raises(HTTPException) as denied:
                _require_websocket_origin(websocket)
            assert denied.value.status_code == 403
            assert denied.value.detail == "Origin validation failed"
    finally:
        await database.dispose()
