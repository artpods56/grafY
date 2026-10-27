from hashlib import sha256
import ssl

import httpx
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    TypeAdapter,
    field_validator,
)
import truststore

from grafy_core.artifacts import JsonObject
from grafy_core.egress import (
    EgressPolicy,
    EgressRejectedError,
    dial_port,
    resolved_dial_addresses,
    validated_public_destination,
)

from grafy_plugin_gis.models import (
    Bounds,
    GeoFeatureCollection,
)


_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)
# Bound both compact wire data and the much larger Python object graph produced
# while validating GeoJSON. Neither a small page size nor paging alone is a cap.
WFS_IMPORT_MAX_FEATURES = 10_000
WFS_IMPORT_TOTAL_RESPONSE_MAX_BYTES = 16 * 1024 * 1024


class WfsImportError(RuntimeError):
    pass


class _WfsFeaturePage(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    features: list[JsonObject]
    number_matched: StrictInt | None = Field(default=None, alias="numberMatched")
    number_returned: StrictInt | None = Field(default=None, alias="numberReturned")

    @field_validator("number_matched", "number_returned", mode="before")
    @classmethod
    def parse_counts(cls, value: JsonValue | None) -> JsonValue | None:
        if value in {None, "unknown"}:
            return None
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return value


class WfsClient:
    """Fetches bounded WFS 2.0 GeoJSON pages from a real remote service."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        egress_policy: EgressPolicy | None = None,
    ) -> None:
        self._transport = transport
        # None means the deployment policy named by the environment, read per
        # page so an operator grant is honoured without rebuilding the client.
        self._egress_policy = egress_policy

    async def fetch_feature_collection(
        self,
        *,
        service_url: str,
        type_name: str,
        source_name: str,
        page_size: int,
        max_page_bytes: int,
        timeout_seconds: float,
        max_features: int,
        bbox: Bounds | None,
        sort_by: str | None = None,
    ) -> GeoFeatureCollection:
        try:
            parsed_url = _HTTP_URL_ADAPTER.validate_python(service_url)
            validated_public_destination(parsed_url, service_name="WFS")
        except ValueError as exc:
            raise WfsImportError(
                f"Rejected WFS 2.0 service endpoint {service_url!r} for type "
                f"{type_name!r}: {exc}"
            ) from exc
        service_url = str(parsed_url)
        service_request_url = httpx.URL(service_url)
        service_host = parsed_url.host
        service_port = dial_port(parsed_url)
        if service_host is None:
            raise WfsImportError(
                f"Rejected WFS 2.0 service endpoint {service_url!r} for type "
                f"{type_name!r}: URL must include a host"
            )

        if page_size < 1:
            raise ValueError("WFS page_size must be positive")
        if max_features < 1:
            raise ValueError("WFS max_features must be positive")
        if max_features > WFS_IMPORT_MAX_FEATURES:
            raise WfsImportError(
                f"Rejected WFS 2.0 import from {service_url!r} for type "
                f"{type_name!r}: max_features={max_features} exceeds the "
                f"first-release limit of {WFS_IMPORT_MAX_FEATURES}"
            )
        if max_page_bytes < 1:
            raise ValueError("WFS max_page_bytes must be positive")
        if max_page_bytes > WFS_IMPORT_TOTAL_RESPONSE_MAX_BYTES:
            raise WfsImportError(
                f"Rejected WFS 2.0 import from {service_url!r} for type "
                f"{type_name!r}: max_page_bytes={max_page_bytes} exceeds the "
                "first-release cumulative response limit of "
                f"{WFS_IMPORT_TOTAL_RESPONSE_MAX_BYTES} bytes"
            )
        if page_size > max_features:
            page_size = max_features

        features: list[JsonObject] = []
        start_index = 0
        previous_page_hash: str | None = None
        total_response_bytes = 0
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        ) as client:
            response_bytes = bytearray()
            while len(features) < max_features:
                request_count = min(
                    page_size,
                    max_features - len(features),
                )
                params: dict[str, str | int] = {
                    "service": "WFS",
                    "version": "2.0.0",
                    "request": "GetFeature",
                    "typeNames": type_name,
                    "outputFormat": "application/json",
                    "srsName": "EPSG:4326",
                    "count": request_count,
                    "startIndex": start_index,
                }
                if sort_by is not None:
                    params["sortBy"] = sort_by
                if bbox is not None:
                    params["bbox"] = ",".join(str(coordinate) for coordinate in bbox)
                    params["bbox"] += ",EPSG:4326"

                # One page is one decision: the guard answers at the moment of
                # the connection, so a name that rebinds between pages is caught
                # on the page that rebinds rather than on the first one only.
                try:
                    resolved_addresses = await resolved_dial_addresses(
                        service_host,
                        service_port,
                        policy=self._egress_policy,
                    )
                except (EgressRejectedError, OSError) as exc:
                    raise WfsImportError(
                        f"Rejected WFS 2.0 GetFeature from {service_url!r} for "
                        f"type {type_name!r} at startIndex={start_index}, "
                        f"count={request_count} after runtime DNS validation: {exc}"
                    ) from exc

                try:
                    response_bytes.clear()
                    for address_index, resolved_address in enumerate(
                        resolved_addresses
                    ):
                        pinned_url = service_request_url.copy_with(
                            host=resolved_address
                        )
                        try:
                            async with client.stream(
                                "GET",
                                pinned_url,
                                params=params,
                                headers={
                                    "Accept": (
                                        "application/geo+json, application/json"
                                    ),
                                    "Host": service_request_url.netloc.decode("ascii"),
                                },
                                extensions={
                                    "sni_hostname": service_request_url.raw_host.decode(
                                        "ascii"
                                    )
                                },
                            ) as response:
                                response.raise_for_status()
                                response_bytes.clear()
                                async for chunk in response.aiter_bytes():
                                    response_bytes.extend(chunk)
                                    if len(response_bytes) > max_page_bytes:
                                        raise WfsImportError(
                                            "WFS 2.0 GetFeature from "
                                            f"{service_url!r} for type "
                                            f"{type_name!r} at "
                                            f"startIndex={start_index} exceeded "
                                            f"the {max_page_bytes}-byte page limit"
                                        )
                            break
                        except (httpx.ConnectError, httpx.ConnectTimeout):
                            if address_index == len(resolved_addresses) - 1:
                                raise
                except WfsImportError:
                    raise
                except httpx.HTTPStatusError as exc:
                    raise WfsImportError(
                        f"Failed WFS 2.0 GetFeature from {service_url!r} for "
                        f"type {type_name!r} at startIndex={start_index}, "
                        f"count={request_count}, status={exc.response.status_code}"
                    ) from exc
                except httpx.HTTPError as exc:
                    raise WfsImportError(
                        f"Failed WFS 2.0 GetFeature from {service_url!r} for "
                        f"type {type_name!r} at startIndex={start_index}, "
                        f"count={request_count}: {exc}"
                    ) from exc

                prospective_total_response_bytes = total_response_bytes + len(
                    response_bytes
                )
                if (
                    prospective_total_response_bytes
                    > WFS_IMPORT_TOTAL_RESPONSE_MAX_BYTES
                ):
                    raise WfsImportError(
                        f"WFS 2.0 GetFeature from {service_url!r} for type "
                        f"{type_name!r} at startIndex={start_index} would exceed "
                        "the first-release cumulative response limit of "
                        f"{WFS_IMPORT_TOTAL_RESPONSE_MAX_BYTES} bytes "
                        f"(received {prospective_total_response_bytes})"
                    )

                try:
                    page = _WfsFeaturePage.model_validate_json(response_bytes)
                except Exception as exc:
                    raise WfsImportError(
                        f"WFS 2.0 GetFeature from {service_url!r} for type "
                        f"{type_name!r} at startIndex={start_index} returned "
                        "invalid GeoJSON"
                    ) from exc

                if page.type != "FeatureCollection":
                    raise WfsImportError(
                        f"WFS 2.0 GetFeature from {service_url!r} for type "
                        f"{type_name!r} returned GeoJSON type {page.type!r}, "
                        "expected 'FeatureCollection'"
                    )
                if page.number_returned is not None and page.number_returned != len(
                    page.features
                ):
                    raise WfsImportError(
                        f"WFS 2.0 GetFeature from {service_url!r} for type "
                        f"{type_name!r} reported numberReturned={page.number_returned} "
                        f"but included {len(page.features)} features"
                    )
                if len(page.features) > request_count:
                    raise WfsImportError(
                        f"WFS 2.0 GetFeature from {service_url!r} for type "
                        f"{type_name!r} returned {len(page.features)} features, "
                        f"exceeding requested count={request_count}"
                    )
                if not page.features:
                    break

                page_hash = sha256(response_bytes).hexdigest()
                if previous_page_hash == page_hash:
                    raise WfsImportError(
                        f"WFS 2.0 service {service_url!r} ignored paging for type "
                        f"{type_name!r}; repeated page at startIndex={start_index}"
                    )
                previous_page_hash = page_hash
                features.extend(page.features)
                total_response_bytes = prospective_total_response_bytes
                start_index += len(page.features)

                if (
                    page.number_matched is not None
                    and start_index >= page.number_matched
                ):
                    break
                if len(page.features) < request_count:
                    break

        try:
            return GeoFeatureCollection.from_features(features, source_name)
        except ValueError as exc:
            raise WfsImportError(
                f"WFS 2.0 GetFeature from {service_url!r} for type {type_name!r} "
                "did not return a valid EPSG:4326 GeoJSON FeatureCollection"
            ) from exc


__all__ = [
    "WFS_IMPORT_MAX_FEATURES",
    "WFS_IMPORT_TOTAL_RESPONSE_MAX_BYTES",
    "WfsClient",
    "WfsImportError",
]
