import json
from collections.abc import Mapping
from ipaddress import ip_address
from typing import cast

import httpx
from pydantic import SecretStr

from .errors import GrafyClientError


class HttpTransport:
    def __init__(
        self,
        *,
        base_url: str,
        token: SecretStr,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        if token.get_secret_value().strip() == "":
            raise ValueError("Grafy personal access token must not be blank")
        parsed_base_url = httpx.URL(base_url)
        if parsed_base_url.scheme not in {"http", "https"}:
            raise ValueError("Grafy API base URL must use HTTP or HTTPS")
        if parsed_base_url.host == "":
            raise ValueError("Grafy API base URL must contain a host")
        if parsed_base_url.scheme == "http":
            host = parsed_base_url.host
            is_loopback = host == "localhost"
            if not is_loopback:
                try:
                    is_loopback = ip_address(host).is_loopback
                except ValueError:
                    is_loopback = False
            if not is_loopback:
                raise ValueError(
                    "Grafy API base URL must use HTTPS unless it targets localhost "
                    "or a loopback IP address"
                )
        if parsed_base_url.username != "" or parsed_base_url.password != "":
            raise ValueError("Grafy API base URL must not contain user information")
        if parsed_base_url.query != b"" or parsed_base_url.fragment != "":
            raise ValueError("Grafy API base URL must not contain a query or fragment")

        self.base_url = str(parsed_base_url).rstrip("/")
        self._token = token
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"HttpTransport(base_url={self.base_url!r}, token=<redacted>)"

    async def close(self) -> None:
        await self._http.aclose()

    async def request_json(
        self,
        *,
        operation: str,
        method: str,
        path: str,
        json_payload: object | None = None,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str | list[str]] | None = None,
        sensitive_values: tuple[str, ...] = (),
    ) -> object:
        request_headers = dict(headers or {})
        token = self._token.get_secret_value()
        request_headers["Authorization"] = f"Bearer {token}"
        try:
            response = await self._http.request(
                method,
                path,
                headers=request_headers,
                json=json_payload,
                files=files,
                params=params,
            )
        except httpx.RequestError as exc:
            raise GrafyClientError(
                operation=operation,
                detail="HTTP transport failed",
            ) from exc
        if response.is_error:
            try:
                response_payload: object = response.json()
                detail_value: object = response_payload
                if isinstance(response_payload, dict) and "detail" in response_payload:
                    response_mapping = cast(
                        Mapping[object, object],
                        response_payload,
                    )
                    detail_value = response_mapping["detail"]
                if isinstance(detail_value, str):
                    detail = detail_value
                else:
                    detail = json.dumps(
                        detail_value,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
            except (ValueError, UnicodeDecodeError):
                detail = response.text
            for sensitive in (token, *sensitive_values):
                if sensitive != "":
                    detail = detail.replace(sensitive, "<redacted>")
            if detail.strip() == "":
                detail = response.reason_phrase or "Request failed"
            raise GrafyClientError(
                operation=operation,
                detail=detail[:4_000],
                status_code=response.status_code,
                request_id=response.headers.get("X-Request-ID"),
            )
        try:
            return response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise GrafyClientError(
                operation=operation,
                detail="Server returned a non-JSON success response",
                status_code=response.status_code,
                request_id=response.headers.get("X-Request-ID"),
            ) from exc


__all__ = ["HttpTransport"]
