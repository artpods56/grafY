import time
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import HttpUrl, SecretStr, ValidationError

from grafy_api.artifacts.images import ArtifactImageService
from grafy_api.artifacts.tiler_client import IMAGE_RESPONSE_MAX_BYTES, HttpTiler
from grafy_api.v1.routes.artifacts.dependencies import artifact_image_service
from grafy_api.v1.routes.artifacts.images import router
from grafy_api.v1.routes.auth.dependencies import identity_service, workspace_actor
from grafy_core.artifacts import ArtifactObject
from grafy_core.domain.errors import CapabilityDeniedError
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceAccess,
    WorkspaceCapability,
    WorkspaceMembership,
    WorkspacePatPrincipal,
    WorkspaceRole,
)
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_crypto.grants import Grant
from grafy_shared.config.tiler import TilerConfig

WS = UUID(int=1)
USER = UUID(int=2)
KEY = "test-key-" * 8


class Identity:
    allowed = True

    async def authorize(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        capability: WorkspaceCapability,
    ) -> WorkspaceAccess:
        assert capability == WorkspaceCapability.VIEW_ARTIFACTS
        if not self.allowed:
            raise HTTPException(403, "Membership revoked")
        return WorkspaceAccess(
            actor=actor,
            workspace_id=workspace_id,
            membership=WorkspaceMembership(
                workspace_id=workspace_id,
                user_id=actor.user_id,
                role=WorkspaceRole.VIEWER,
            ),
        )


@dataclass
class Harness:
    client: httpx.AsyncClient
    uow: InMemoryUnitOfWork
    artifact: ArtifactObject
    requests: list[httpx.Request]
    app: FastAPI
    identity: Identity
    config: TilerConfig
    status: int = 200
    body: bytes = b"tile bytes"
    content_type: str = "image/jpeg"
    renderer: str = "1"
    fail: bool = False

    @property
    def path(self) -> str:
        return f"/v1/workspaces/{WS}/artifacts/{self.artifact.id}/image"


@pytest.fixture
async def proxy() -> AsyncIterator[Harness]:
    uow = InMemoryUnitOfWork()
    artifact = ArtifactObject(
        workspace_id=WS,
        artifact_type="file.tiff",
        schema_version=1,
        content_type="image/tiff",
        bucket="bucket",
        object_key="workspace/scan.tif",
        sha256="a" * 64,
        byte_size=100,
    )
    async with uow:
        await uow.artifacts.add(artifact)
        await uow.commit()
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    config = TilerConfig(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        tiler_url=HttpUrl("http://tiler:8100"),
        tiler_shared_key=SecretStr(KEY),
    )
    identity = Identity()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as client:
        harness = Harness(client, uow, artifact, [], app, identity, config)

        def upstream(request: httpx.Request) -> httpx.Response:
            harness.requests.append(request)
            if harness.fail:
                raise httpx.ConnectError("connection failed", request=request)
            return httpx.Response(
                harness.status,
                content=harness.body,
                headers={
                    "Content-Type": harness.content_type,
                    "X-Grafy-Renderer": harness.renderer,
                    "Retry-After": "3",
                    "Location": "https://other.test",
                    "Set-Cookie": "secret=never-forward",
                },
            )

        service = ArtifactImageService(
            uow,
            config,
            HttpTiler(
                config,
                client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
            ),
        )
        app.dependency_overrides[artifact_image_service] = lambda: service
        app.dependency_overrides[identity_service] = lambda: identity
        app.dependency_overrides[workspace_actor] = lambda: ActorContext(user_id=USER)

        async def denied(_: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"detail": str(exc)}, status_code=403)

        app.add_exception_handler(CapabilityDeniedError, denied)

        try:
            yield harness
        finally:
            await service.close()


async def test_tile_signs_source_and_returns_only_image_and_cache_headers(
    proxy: Harness,
) -> None:
    response = await proxy.client.get(proxy.path + "/tiles/11/2/1.jpg?page=2")
    assert response.status_code == 200
    assert response.content == b"tile bytes"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, max-age=300"
    assert "set-cookie" not in response.headers
    assert "location" not in response.headers
    assert "x-grafy-grant" not in response.headers
    request = proxy.requests[0]
    assert str(request.url) == "http://tiler:8100/tiles/11/2/1.jpg"
    grant = Grant.verify_grant(
        request.headers["X-Grafy-Grant"],
        keys=[KEY.encode()],
        bucket="bucket",
        now=int(time.time()),
        skew_seconds=0,
        max_source_bytes=1024,
    )
    assert (grant.key, grant.page, grant.sha256, grant.byte_size) == (
        "workspace/scan.tif",
        2,
        "a" * 64,
        100,
    )
    assert 58 <= grant.expires_at - int(time.time()) <= 60


async def test_conditional_get_checks_access_before_skipping_upstream(
    proxy: Harness,
) -> None:
    url = proxy.path + "/tiles/11/2/1.jpg"
    first = await proxy.client.get(url)
    headers = {"If-None-Match": '"other", W/' + first.headers["etag"]}
    response = await proxy.client.get(url, headers=headers)
    assert response.status_code == 304 and response.content == b""
    assert len(proxy.requests) == 1
    proxy.identity.allowed = False
    assert (await proxy.client.get(url, headers=headers)).status_code == 403
    assert len(proxy.requests) == 1


async def test_other_workspace_cannot_read_or_get_304(proxy: Harness) -> None:
    url = proxy.path.replace(str(WS), str(UUID(int=9))) + "/tiles/0/0/0.jpg"
    assert (
        await proxy.client.get(url, headers={"If-None-Match": "*"})
    ).status_code == 404
    assert not proxy.requests


async def test_pat_without_view_scope_is_denied(proxy: Harness) -> None:
    proxy.app.dependency_overrides[workspace_actor] = lambda: WorkspacePatPrincipal(
        actor=ActorContext(user_id=USER),
        workspace_id=WS,
        capabilities=frozenset(),
        token_id=UUID(int=8),
    )
    assert (await proxy.client.get(proxy.path + "/info")).status_code == 403
    assert not proxy.requests


async def test_no_actor_cannot_read(proxy: Harness) -> None:
    async def unauthenticated() -> ActorContext:
        raise HTTPException(401, "Authentication required")

    proxy.app.dependency_overrides[workspace_actor] = unauthenticated
    assert (await proxy.client.get(proxy.path + "/info")).status_code == 401
    assert not proxy.requests


@pytest.mark.parametrize(
    "suffix",
    [
        "/tiles/-1/0/0.jpg",
        "/tiles/0/-1/0.jpg",
        "/tiles/0/0/0.gif",
        "/info?page=-1",
        "/info?page=1024",
        "/thumbnail?edge=300",
    ],
)
async def test_invalid_parameters_never_call_tiler(proxy: Harness, suffix: str) -> None:
    assert (await proxy.client.get(proxy.path + suffix)).status_code == 422
    assert not proxy.requests


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (403, 502),
        (302, 502),
        (500, 502),
        (404, 404),
        (409, 409),
        (413, 413),
        (415, 415),
        (422, 422),
        (503, 503),
    ],
)
async def test_upstream_errors_are_sanitized(
    proxy: Harness, status: int, expected: int
) -> None:
    proxy.status = status
    proxy.body = b"internal details"
    response = await proxy.client.get(proxy.path + "/tiles/0/0/0.jpg")
    assert response.status_code == expected
    assert b"internal details" not in response.content
    assert len(proxy.requests) == 1
    if expected == 503:
        assert response.headers["retry-after"] == "3"


async def test_unexpected_upstream_status_is_visible(proxy: Harness) -> None:
    proxy.status = 500
    response = await proxy.client.get(proxy.path + "/info")
    assert response.status_code == 502
    assert response.json() == {"detail": "Tiler returned HTTP 500"}


async def test_connection_failure_is_retryable(proxy: Harness) -> None:
    proxy.fail = True
    response = await proxy.client.get(proxy.path + "/info")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "2"


@pytest.mark.parametrize(
    "fault", ["oversize", "content_type", "renderer", "invalid_info"]
)
async def test_invalid_upstream_success_is_rejected(proxy: Harness, fault: str) -> None:
    suffix = "/tiles/0/0/0.jpg"
    if fault == "oversize":
        proxy.body = b"x" * (IMAGE_RESPONSE_MAX_BYTES + 1)
    if fault == "content_type":
        proxy.content_type = "text/html"
    if fault == "renderer":
        proxy.renderer = "2"
    if fault == "invalid_info":
        suffix = "/info"
        proxy.content_type = "application/json"
        proxy.body = b"{}"
    assert (await proxy.client.get(proxy.path + suffix)).status_code == 502


async def test_thumbnail_forwards_edge_and_page(proxy: Harness) -> None:
    response = await proxy.client.get(proxy.path + "/thumbnail?edge=512&page=1")
    assert response.status_code == 200
    assert proxy.requests[0].url.params["edge"] == "512"


async def test_disabled_proxy_returns_501(proxy: Harness) -> None:
    proxy.config.tiler_url = None
    assert (await proxy.client.get(proxy.path + "/info")).status_code == 501
    assert not proxy.requests


@pytest.mark.parametrize("content_type", ["image/png", "application/pdf"])
async def test_non_tiff_is_rejected(proxy: Harness, content_type: str) -> None:
    async with proxy.uow:
        artifact = await proxy.uow.artifacts.get(WS, proxy.artifact.id)
        assert artifact is not None
        artifact = replace(artifact, id=uuid4(), content_type=content_type)
        proxy.artifact = artifact
        await proxy.uow.artifacts.add(artifact)
        await proxy.uow.commit()
    assert (await proxy.client.get(proxy.path + "/info")).status_code == 415
    assert not proxy.requests


def test_enabled_proxy_requires_strong_key() -> None:
    with pytest.raises(ValidationError):
        TilerConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            tiler_url=HttpUrl("http://tiler:8100"),
            tiler_shared_key=SecretStr("short"),
        )


async def test_info_returns_a_typed_descriptor(proxy: Harness) -> None:
    info = {
        "width": 1024,
        "height": 512,
        "page": 0,
        "page_count": 1,
        "band_count": 1,
        "dtype": "uint8",
        "bit_depth": 8,
        "kind": "gray",
        "has_alpha": False,
        "tile_size": 512,
        "min_level": 1,
        "max_level": 10,
        "tile_format": "jpg",
        "resampling": "average",
        "overview_count": 0,
        "overview_level": None,
        "value_range": None,
        "palette": None,
        "georeferenced": False,
        "crs": None,
        "bounds_wgs84": None,
    }
    proxy.body = json.dumps(info).encode()
    proxy.content_type = "application/json"
    response = await proxy.client.get(proxy.path + "/info")
    assert response.status_code == 200
    assert response.json() == {
        key: info[key]
        for key in (
            "width",
            "height",
            "page_count",
            "has_alpha",
            "tile_size",
            "min_level",
            "max_level",
            "tile_format",
        )
    }


async def test_etags_distinguish_page_coordinates_edge_and_renderer(
    proxy: Harness,
) -> None:
    urls = [
        "/tiles/10/0/0.jpg",
        "/tiles/10/0/0.jpg?page=1",
        "/tiles/10/1/0.jpg",
        "/tiles/9/0/0.jpg",
        "/thumbnail?edge=128",
        "/thumbnail?edge=512",
    ]
    tags: set[str] = set()
    for suffix in urls:
        response = await proxy.client.get(proxy.path + suffix)
        assert response.status_code == 200
        tags.add(response.headers["etag"])
    proxy.config.tiler_renderer_version = proxy.renderer = "2"
    response = await proxy.client.get(proxy.path + urls[0])
    assert response.status_code == 200
    tags.add(response.headers["etag"])
    assert len(tags) == len(urls) + 1


async def test_rotation_signs_with_current_key(proxy: Harness) -> None:
    previous = "previous-key-" * 4
    proxy.config.tiler_shared_key = SecretStr(f" {KEY} , {previous} ")
    response = await proxy.client.get(proxy.path + "/tiles/10/0/0.jpg")
    assert response.status_code == 200
    grant = Grant.verify_grant(
        proxy.requests[0].headers["X-Grafy-Grant"],
        keys=[KEY.encode()],
        bucket="bucket",
        now=int(time.time()),
        skew_seconds=0,
        max_source_bytes=1024,
    )
    assert grant.sha256 == proxy.artifact.sha256


@pytest.mark.parametrize(
    "keys", ["x" * 32 + ",short", "," + "x" * 32, ",".join(["x" * 32] * 3)]
)
def test_rotation_rejects_invalid_key_lists(keys: str) -> None:
    with pytest.raises(ValidationError):
        TilerConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            tiler_url=HttpUrl("http://tiler:8100"),
            tiler_shared_key=SecretStr(keys),
        )


async def test_operation_timeouts(proxy: Harness) -> None:
    await proxy.client.get(proxy.path + "/thumbnail")
    assert proxy.requests[-1].extensions["timeout"]["read"] == 10
    await proxy.client.get(proxy.path + "/info")
    assert proxy.requests[-1].extensions["timeout"]["read"] == 30


async def test_whole_request_deadline_releases_stalled_upstream(proxy: Harness) -> None:
    import asyncio
    from grafy_api.artifacts.images import ImageProxyError, TiffSource

    entered = asyncio.Event()
    never_finishes = asyncio.Event()

    async def stalled(request: httpx.Request) -> httpx.Response:
        entered.set()
        await never_finishes.wait()
        return httpx.Response(200)

    proxy.config.tiler_timeout_seconds = 0.01
    tiler = HttpTiler(
        proxy.config, client=httpx.AsyncClient(transport=httpx.MockTransport(stalled))
    )
    try:
        with pytest.raises(ImageProxyError) as failure:
            await tiler.thumbnail(
                TiffSource("bucket", "scan.tif", "a" * 64, 100, 0), edge=256
            )
        assert entered.is_set()
        assert failure.value.status == 503
        assert failure.value.retry_after == "2"
    finally:
        await tiler.close()
