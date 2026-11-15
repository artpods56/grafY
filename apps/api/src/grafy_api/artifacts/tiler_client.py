"""HTTP adapter for the internal tiler: the only code that knows its wire protocol."""

import time

import httpx
from pydantic import ValidationError

from grafy_crypto.grants import Grant, sign_grant
from grafy_shared.config.tiler import TilerConfig

from grafy_api.artifacts.images import (
    ImageProxyError,
    TiffSource,
    TileExtension,
    TilerImage,
    TilerPort,
)
from grafy_api.artifacts.models import ImageInfoResponse

IMAGE_RESPONSE_MAX_BYTES = 8 * 1024 * 1024


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
        image = await self._get(
            source, "info", content_type="application/json", rendered=False
        )
        try:
            return ImageInfoResponse.model_validate_json(image.body)
        except ValidationError as exc:
            raise ImageProxyError(502, "Tiler returned invalid image metadata") from exc

    async def tile(
        self, source: TiffSource, *, z: int, x: int, y: int, extension: TileExtension
    ) -> TilerImage:
        return await self._get(
            source,
            f"tiles/{z}/{x}/{y}.{extension}",
            content_type="image/png" if extension == "png" else "image/jpeg",
        )

    async def thumbnail(self, source: TiffSource, *, edge: int) -> TilerImage:
        return await self._get(source, "thumbnail", edge=edge)

    async def _get(
        self,
        source: TiffSource,
        path: str,
        *,
        content_type: str | None = None,
        edge: int | None = None,
        rendered: bool = True,
    ) -> TilerImage:
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
        token = sign_grant(grant, config.tiler_shared_key.get_secret_value().encode())
        url = str(config.tiler_url).rstrip("/") + "/" + path
        try:
            async with self._client.stream(
                "GET",
                url,
                headers={"X-Grafy-Grant": token},
                params={} if edge is None else {"edge": edge},
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    status = response.status_code
                    if status in {404, 409, 413, 422}:
                        raise ImageProxyError(
                            status, "Tiler could not render this image"
                        )
                    if status == 503:
                        retry = response.headers.get("Retry-After", "2")
                        raise ImageProxyError(
                            503, "Tiler is busy", retry if retry.isdigit() else "2"
                        )
                    raise ImageProxyError(502, "Tiler returned an invalid response")
                received = response.headers.get("Content-Type", "").split(";")[0]
                allowed = (
                    {"image/png", "image/jpeg"}
                    if content_type is None
                    else {content_type}
                )
                if received not in allowed:
                    raise ImageProxyError(502, "Tiler returned an invalid content type")
                if (
                    rendered
                    and response.headers.get("X-Grafy-Renderer")
                    != config.tiler_renderer_version
                ):
                    raise ImageProxyError(
                        502, "Tiler renderer version does not match API configuration"
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > IMAGE_RESPONSE_MAX_BYTES:
                        raise ImageProxyError(
                            502, "Tiler response exceeds the size limit"
                        )
        except httpx.HTTPError as exc:
            raise ImageProxyError(503, "Tiler is unavailable", "2") from exc
        return TilerImage(bytes(body), received)
