import ssl
from dataclasses import dataclass

import httpx
import truststore

from grafy_core.egress import (
    EgressPolicy,
    default_egress_policy,
    dial_port,
    resolved_dial_addresses,
    validated_public_destination,
)

from grafy_api.services.errors import ArtifactContentUnavailableError

from grafy_api.artifacts.models import GeoWmsSourcePayload


WMS_RESPONSE_BYTE_BUDGET = 5 * 1_024 * 1_024


@dataclass(frozen=True, slots=True)
class GeoTileRead:
    content: bytes
    content_type: str
    etag: str | None


class WmsTileClient:
    """Fetches remote WMS raster tiles through the deployment egress guard."""

    def __init__(
        self,
        *,
        egress_policy: EgressPolicy | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        # A WMS tile URL is author input, so the deployment policy decides what
        # it may reach. `None` takes the policy named by the environment.
        self._egress_policy = (
            default_egress_policy() if egress_policy is None else egress_policy
        )
        self._client = (
            httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                follow_redirects=False,
                http2=False,
                trust_env=False,
                verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            )
            if client is None
            else client
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_tile(
        self,
        source: GeoWmsSourcePayload,
        *,
        z: int,
        x: int,
        y: int,
    ) -> GeoTileRead:
        _ = validated_public_destination(source.url, service_name="WMS")
        host = source.url.host
        if host is None:
            raise ArtifactContentUnavailableError("WMS URL does not have a host")
        extent = 20_037_508.342789244
        span = extent * 2 / (1 << z)
        west = -extent + x * span
        east = west + span
        north = extent - y * span
        south = north - span
        parameters = {
            "service": "WMS",
            "request": "GetMap",
            "version": source.version,
            "layers": source.layer,
            "styles": source.style_name or "",
            "format": source.format,
            "transparent": "true",
            "width": "256",
            "height": "256",
            "bbox": f"{west},{south},{east},{north}",
        }
        if source.version == "1.3.0":
            parameters["crs"] = "EPSG:3857"
        else:
            parameters["srs"] = "EPSG:3857"
        service_request_url = httpx.URL(str(source.url))
        try:
            # One guard for every dial: the same resolve-and-decide step the
            # Plugin families share answers this host, then the tile is dialed
            # on that address while the request keeps the configured name.
            addresses = await resolved_dial_addresses(
                host,
                dial_port(source.url),
                policy=self._egress_policy,
            )
            for address_index, resolved_address in enumerate(addresses):
                pinned_url = service_request_url.copy_with(host=resolved_address)
                try:
                    chunks: list[bytes] = []
                    byte_size = 0
                    async with self._client.stream(
                        "GET",
                        pinned_url,
                        params=parameters,
                        headers={
                            "Accept": source.format,
                            "Connection": "close",
                            "Host": service_request_url.netloc.decode("ascii"),
                        },
                        extensions={
                            "sni_hostname": service_request_url.raw_host.decode("ascii")
                        },
                    ) as response:
                        if response.status_code < 200 or response.status_code >= 300:
                            raise ValueError(
                                f"WMS returned HTTP {response.status_code}"
                            )
                        response_type = (
                            response.headers.get("content-type", "")
                            .split(";", 1)[0]
                            .strip()
                            .lower()
                        )
                        if response_type != source.format:
                            raise ValueError(
                                f"WMS returned {response_type or 'no content type'}, "
                                f"expected {source.format}"
                            )
                        async for chunk in response.aiter_bytes():
                            byte_size += len(chunk)
                            if byte_size > WMS_RESPONSE_BYTE_BUDGET:
                                raise ValueError(
                                    f"WMS tile exceeds {WMS_RESPONSE_BYTE_BUDGET} bytes"
                                )
                            chunks.append(chunk)
                    return GeoTileRead(
                        content=b"".join(chunks),
                        content_type=source.format,
                        etag=None,
                    )
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    if address_index == len(addresses) - 1:
                        raise
            raise RuntimeError(f"WMS host {host!r} had no usable public address")
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not fetch WMS layer {source.layer!r} from "
                f"{source.url.host} for tile {z}/{x}/{y}"
            ) from exc


__all__ = [
    "GeoTileRead",
    "WMS_RESPONSE_BYTE_BUDGET",
    "WmsTileClient",
]
