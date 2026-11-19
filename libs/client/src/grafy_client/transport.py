import json
from collections.abc import AsyncIterable, Mapping
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
        # An ASGI transport delivers every request to the app it wraps, whatever host
        # the URL names, so a client built this way can only ever address that app.
        self._in_process_host: str | None = None
        if isinstance(transport, httpx.ASGITransport):
            self._in_process_host = f"{parsed_base_url.host}:{parsed_base_url.port}"
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"HttpTransport(base_url={self.base_url!r}, token=<redacted>)"

    def _refuse_unreachable_target(self, *, operation: str, path: str) -> None:
        """Refuse a URL this client cannot deliver to, rather than misroute it.

        Only an in-process client is restricted, and only an absolute URL to another
        host. A signed upload target is exactly that: `httpx.ASGITransport` would hand
        the bytes to the API instead of the bucket and the transfer would fail as a
        puzzling 404. The host is reported, never the URL, whose query is a signature.
        """

        if self._in_process_host is None:
            return
        target = httpx.URL(path)
        if target.host == "":
            return
        if f"{target.host}:{target.port}" == self._in_process_host:
            return
        unreachable = f"{target.host}:{target.port}"
        raise GrafyClientError(
            operation=operation,
            detail=(
                f"This client talks to the API in process and cannot send bytes to "
                f"{unreachable}. Upload the file over HTTP to the API address instead."
            ),
        )

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
        params: Mapping[str, str | int | list[str]] | None = None,
        sensitive_values: tuple[str, ...] = (),
    ) -> object:
        response = await self.send(
            operation=operation,
            method=method,
            path=path,
            json_payload=json_payload,
            files=files,
            headers=headers,
            params=params,
            sensitive_values=sensitive_values,
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

    async def send(
        self,
        *,
        operation: str,
        method: str,
        path: str,
        json_payload: object | None = None,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
        content: bytes | AsyncIterable[bytes] | None = None,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str | int | list[str]] | None = None,
        sensitive_values: tuple[str, ...] = (),
        authenticate: bool = True,
    ) -> httpx.Response:
        """Send one request and raise a redacted `GrafyClientError` on failure.

        ``authenticate=False`` is for a signed object-storage URL: the signature is
        the credential there, and the bearer token must never leave for that host.
        """

        self._refuse_unreachable_target(operation=operation, path=path)
        request_headers = dict(headers or {})
        token = self._token.get_secret_value()
        if authenticate:
            request_headers["Authorization"] = f"Bearer {token}"
        try:
            response = await self._http.request(
                method,
                path,
                headers=request_headers,
                json=json_payload,
                files=files,
                content=content,
                params=params,
            )
        except httpx.RequestError as exc:
            raise GrafyClientError(
                operation=operation,
                detail="HTTP transport failed",
            ) from exc
        if not response.is_error:
            return response
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


__all__ = ["HttpTransport"]
