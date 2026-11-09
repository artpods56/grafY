"""Small single-process abuse controls for the initial one-owner deployment."""

from collections.abc import Callable
from dataclasses import dataclass
import base64
import hashlib
import hmac
import time
from asyncio import Lock
from secrets import token_urlsafe
from uuid import UUID

from fastapi import Response


BROWSER_ABUSE_COOKIE = "grafy_browser_abuse"
_BROWSER_ABUSE_COOKIE_MAX_AGE = 24 * 60 * 60
_BROWSER_COOKIE_CONTEXT = b"grafy.browser-abuse.v1\x00"


@dataclass(frozen=True, slots=True)
class BrowserAbuseKeys:
    browser_key: str
    network_key: str


@dataclass
class _Window:
    started_at: float
    count: int = 0


@dataclass
class _LoginReservation:
    browser_digest: bytes
    network_digest: bytes
    expires_at: float


class AuthAbuseControl:
    _max_tracked_keys = 4096

    def __init__(
        self,
        *,
        window_seconds: float = 60.0,
        login_start_limit: int = 10,
        callback_limit: int = 20,
        session_failure_limit: int = 30,
        pat_creation_limit: int = 10,
        outstanding_login_limit: int = 2,
        network_outstanding_login_limit: int = 8,
        outstanding_login_ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window_seconds = window_seconds
        self._limits = {
            "login_start": login_start_limit,
            "callback": callback_limit,
            "session_failure": session_failure_limit,
            "pat_creation": pat_creation_limit,
        }
        self._outstanding_login_limit = outstanding_login_limit
        self._network_outstanding_login_limit = network_outstanding_login_limit
        self._outstanding_login_ttl_seconds = outstanding_login_ttl_seconds
        self._clock = clock
        self._windows: dict[tuple[str, str, bytes], _Window] = {}
        self._reservations: dict[UUID, _LoginReservation] = {}
        self._browser_reservations: dict[bytes, set[UUID]] = {}
        self._network_reservations: dict[bytes, set[UUID]] = {}
        self._lock = Lock()

    async def allow_login_start(
        self,
        browser_key: str,
        network_key: str | None = None,
    ) -> bool:
        return await self._allow("login_start", browser_key, network_key)

    async def allow_callback(
        self,
        browser_key: str,
        network_key: str | None = None,
    ) -> bool:
        return await self._allow("callback", browser_key, network_key)

    async def allow_session_failure(self, browser_key: str) -> bool:
        return await self._allow("session_failure", browser_key)

    async def allow_pat_creation(self, user_key: str) -> bool:
        return await self._allow("pat_creation", user_key)

    async def reserve_login(
        self,
        browser_key: str,
        transaction_id: UUID,
        network_key: str | None = None,
    ) -> bool:
        now = self._clock()
        browser_digest = _digest(browser_key)
        network_digest = _digest(network_key or browser_key)
        async with self._lock:
            self._prune_reservations(now)
            if transaction_id in self._reservations:
                return False
            browser_reservations: set[UUID] | None = self._browser_reservations.get(
                browser_digest
            )
            network_reservations: set[UUID] | None = self._network_reservations.get(
                network_digest
            )
            if (
                browser_reservations is None
                and len(self._browser_reservations) >= self._max_tracked_keys
            ):
                return False
            if (
                network_reservations is None
                and len(self._network_reservations) >= self._max_tracked_keys
            ):
                return False
            if (
                browser_reservations is not None
                and len(browser_reservations) >= self._outstanding_login_limit
            ):
                return False
            if (
                network_reservations is not None
                and len(network_reservations) >= self._network_outstanding_login_limit
            ):
                return False
            if browser_reservations is None:
                browser_reservations = set()
                self._browser_reservations[browser_digest] = browser_reservations
            if network_reservations is None:
                network_reservations = set()
                self._network_reservations[network_digest] = network_reservations
            self._reservations[transaction_id] = _LoginReservation(
                browser_digest=browser_digest,
                network_digest=network_digest,
                expires_at=now + self._outstanding_login_ttl_seconds,
            )
            browser_reservations.add(transaction_id)
            network_reservations.add(transaction_id)
            return True

    async def release_login(self, transaction_id: UUID) -> None:
        async with self._lock:
            self._remove_reservation(transaction_id)

    async def _allow(
        self,
        kind: str,
        browser_key: str,
        network_key: str | None = None,
    ) -> bool:
        now = self._clock()
        dimensions = [("browser", browser_key)]
        if network_key is not None:
            dimensions.append(("network", network_key))
        async with self._lock:
            expired_keys = [
                window_key
                for window_key, window in self._windows.items()
                if now - window.started_at >= self._window_seconds
            ]
            for expired_key in expired_keys:
                del self._windows[expired_key]
            window_keys = [
                (kind, dimension, _digest(key)) for dimension, key in dimensions
            ]
            missing_count = sum(
                window_key not in self._windows for window_key in window_keys
            )
            if len(self._windows) + missing_count > self._max_tracked_keys:
                return False
            for window_key in window_keys:
                window = self._windows.get(window_key)
                if window is not None and window.count >= self._limits[kind]:
                    return False
            for window_key in window_keys:
                window = self._windows.get(window_key)
                if window is None:
                    self._windows[window_key] = _Window(
                        started_at=now,
                        count=1,
                    )
                else:
                    window.count += 1
            return True

    def _prune_reservations(self, now: float) -> None:
        expired_ids = [
            transaction_id
            for transaction_id, reservation in self._reservations.items()
            if reservation.expires_at <= now
        ]
        for transaction_id in expired_ids:
            self._remove_reservation(transaction_id)

    def _remove_reservation(self, transaction_id: UUID) -> None:
        reservation = self._reservations.pop(transaction_id, None)
        if reservation is None:
            return
        browser_reservations = self._browser_reservations.get(
            reservation.browser_digest
        )
        if browser_reservations is not None:
            browser_reservations.discard(transaction_id)
            if not browser_reservations:
                del self._browser_reservations[reservation.browser_digest]
        network_reservations = self._network_reservations.get(
            reservation.network_digest
        )
        if network_reservations is not None:
            network_reservations.discard(transaction_id)
            if not network_reservations:
                del self._network_reservations[reservation.network_digest]


def request_browser_keys(
    request: object,
    *,
    secret: bytes,
) -> BrowserAbuseKeys:
    state = getattr(request, "state", None)
    cached_browser_key = getattr(state, "auth_browser_key", None)
    cached_network_key = getattr(state, "auth_network_key", None)
    if isinstance(cached_browser_key, str) and isinstance(cached_network_key, str):
        return BrowserAbuseKeys(
            browser_key=cached_browser_key,
            network_key=cached_network_key,
        )
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    network_key = f"ip:{host}" if isinstance(host, str) and host else "ip:unknown"
    cookies = getattr(request, "cookies", {})
    supplied_cookie = cookies.get(BROWSER_ABUSE_COOKIE)
    browser_key = _verify_browser_abuse_cookie(supplied_cookie, secret)
    path = getattr(getattr(request, "url", None), "path", "")
    if browser_key is None:
        if isinstance(path, str) and "/auth/oidc/" not in path:
            browser_key = network_key
        else:
            browser_key = token_urlsafe(32)
    if state is not None:
        state.auth_browser_key = browser_key
        state.auth_network_key = network_key
    return BrowserAbuseKeys(
        browser_key=browser_key,
        network_key=network_key,
    )


def make_browser_abuse_cookie(browser_key: str, *, secret: bytes) -> str:
    payload = browser_key.encode("ascii")
    encoded_payload = _encode(payload)
    signature = hmac.new(
        secret,
        _BROWSER_COOKIE_CONTEXT + payload,
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_encode(signature)}"


def set_browser_abuse_cookie(
    response: Response,
    browser_key: str,
    *,
    secret: bytes,
    secure: bool,
) -> None:
    response.set_cookie(
        BROWSER_ABUSE_COOKIE,
        make_browser_abuse_cookie(browser_key, secret=secret),
        max_age=_BROWSER_ABUSE_COOKIE_MAX_AGE,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/api/v1/auth/oidc",
    )


def _verify_browser_abuse_cookie(
    value: object,
    secret: bytes,
) -> str | None:
    if not isinstance(value, str) or len(value) > 256:
        return None
    parts = value.split(".")
    if len(parts) != 2:
        return None
    try:
        payload = _decode(parts[0])
        supplied_signature = _decode(parts[1])
        browser_key = payload.decode("ascii")
    except (UnicodeDecodeError, ValueError):
        return None
    if not browser_key or len(browser_key) > 128:
        return None
    expected_signature = hmac.new(
        secret,
        _BROWSER_COOKIE_CONTEXT + payload,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        return None
    return browser_key


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    if not value or len(value) > 256:
        raise ValueError("encoded value is too long")
    return base64.b64decode(
        value + "=" * (-len(value) % 4),
        altchars=b"-_",
        validate=True,
    )


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


__all__ = [
    "AuthAbuseControl",
    "BROWSER_ABUSE_COOKIE",
    "BrowserAbuseKeys",
    "make_browser_abuse_cookie",
    "request_browser_keys",
    "set_browser_abuse_cookie",
]
