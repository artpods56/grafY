"""HTTP adapter for the internal tiler: the only code that knows its wire protocol."""

import asyncio
import time

import httpx
from pydantic import Field, ValidationError

from grafy_crypto.grants import MAX_PAGE, Grant
from grafy_shared.config.tiler import TilerConfig

from grafy_api.artifacts.images import (
    ImageProxyError,
    TiffSource,
    TileExtension,
    TilerImage,
    TilerPort,
    TilerWindow,
    WindowCoordinates,
    WindowPlacement,
)
from grafy_api.artifacts.models import ImageInfoResponse

IMAGE_RESPONSE_MAX_BYTES = 8 * 1024 * 1024


class _WindowRequest(WindowCoordinates):
    # The page travels in the signed grant.
    page: int = Field(ge=0, le=MAX_PAGE, exclude=True)


class HttpTiler(TilerPort):
    def __init__(
        self, config: TilerConfig, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self._config = config
        self._client = (
            client
            if client is not None
            else httpx.AsyncClient(
                timeout=config.tiler_timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            )
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def info(self, source: TiffSource) -> ImageInfoResponse:
        image, _ = await self._get(
            source, "info", content_type="application/json", display=False
        )
        try:
            return ImageInfoResponse.model_validate_json(image.body)
        except ValidationError as exc:
            raise ImageProxyError(502, "Tiler returned invalid image metadata") from exc

    async def tile(
        self, source: TiffSource, *, z: int, x: int, y: int, extension: TileExtension
    ) -> TilerImage:
        image, _ = await self._get(
            source,
            f"tiles/{z}/{x}/{y}.{extension}",
            content_type="image/png" if extension == "png" else "image/jpeg",
        )
        return image

    async def thumbnail(self, source: TiffSource, *, edge: int) -> TilerImage:
        image, _ = await self._get(source, "thumbnail", params={"edge": edge})
        return image

    async def read_window(
        self, source: TiffSource, *, col: int, row: int, width: int, height: int
    ) -> TilerWindow:
        try:
            request = _WindowRequest(
                col=col, row=row, width=width, height=height, page=source.page
            )
        except ValidationError as exc:
            raise ImageProxyError(422, "Invalid TIFF pixel window or page") from exc
        params = request.model_dump()
        image, headers = await self._get(
            source,
            "window",
            params=params,
            content_type="image/png",
            display=False,
            attempts=2,
        )
        try:
            placement = WindowPlacement.model_validate_json(
                headers.get("X-Grafy-Window", "")
            )
        except ValidationError as exc:
            raise ImageProxyError(
                502, "Tiler returned invalid window placement"
            ) from exc
        if placement.model_dump(exclude={"affine", "crs"}) != params:
            raise ImageProxyError(502, "Tiler returned a different window")
        return TilerWindow(image.body, placement)

    async def _get(
        self,
        source: TiffSource,
        path: str,
        *,
        content_type: str | None = None,
        params: dict[str, int] | None = None,
        display: bool = True,
        attempts: int = 1,
    ) -> tuple[TilerImage, httpx.Headers]:
        """GET one tiler path. `content_type=None` accepts PNG or JPEG."""
        config = self._config
        assert config.tiler_url is not None
        assert config.tiler_shared_key is not None
        grant = Grant(
            bucket=source.bucket,
            key=source.key,
            sha256=source.sha256,
            byte_size=source.byte_size,
            page=source.page,
            expires_at=int(time.time()) + 60,
        )
        token = grant.sign_grant(
            config.tiler_shared_key.get_secret_value().split(",")[0].strip().encode()
        )
        url = str(config.tiler_url).rstrip("/") + "/" + path
        if path == "info":
            deadline = config.tiler_info_timeout_seconds
        elif path == "window":
            deadline = config.tiler_window_timeout_seconds
        else:
            deadline = config.tiler_timeout_seconds
        for attempt in range(attempts):
            try:
                async with (
                    asyncio.timeout(deadline),
                    self._client.stream(
                        "GET",
                        url,
                        headers={"X-Grafy-Grant": token},
                        params=params,
                        follow_redirects=False,
                        timeout=deadline,
                    ) as response,
                ):
                    if response.status_code != 200:
                        status = response.status_code
                        if status in {404, 409, 413, 415, 422}:
                            raise ImageProxyError(
                                status, "Tiler could not render this image"
                            )
                        if status == 503:
                            retry = response.headers.get("Retry-After", "2")
                            raise ImageProxyError(
                                503,
                                "Tiler is busy",
                                str(min(30, max(1, int(retry))))
                                if retry.isdigit() and len(retry) <= 8
                                else "2",
                            )
                        raise ImageProxyError(502, f"Tiler returned HTTP {status}")
                    received = response.headers.get("Content-Type", "").split(";")[0]
                    allowed = (
                        {"image/png", "image/jpeg"}
                        if content_type is None
                        else {content_type}
                    )
                    if received not in allowed:
                        raise ImageProxyError(
                            502, "Tiler returned an invalid content type"
                        )
                    if (
                        display
                        and response.headers.get("X-Grafy-Renderer")
                        != config.tiler_renderer_version
                    ):
                        raise ImageProxyError(
                            502,
                            "Tiler renderer version does not match API configuration",
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > IMAGE_RESPONSE_MAX_BYTES:
                            raise ImageProxyError(
                                502, "Tiler response exceeds the size limit"
                            )
                    return TilerImage(bytes(body), received), response.headers
            except (TimeoutError, httpx.TimeoutException) as exc:
                if attempt + 1 < attempts:
                    continue
                raise ImageProxyError(503, "Tiler timed out", "2") from exc
            except httpx.HTTPError as exc:
                raise ImageProxyError(503, "Tiler is unavailable", "2") from exc
        raise AssertionError("tiler request attempts exhausted")
