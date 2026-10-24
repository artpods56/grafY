"""The shared egress pin, in the HTTP dialect the Mistral SDK speaks.

`grafy_core.egress.PinnedPublicAddressTransport` decides which address a name may
be dialed on and is written against `httpx`. The Mistral SDK builds its requests
on `httpx2`, a separate library that agrees on the shape a transport sees: the
same request carrying `url`, `headers` and `extensions`, and a response its client
can read. So the pin is handed over untouched with this library's own transport
underneath it, and nothing in between decides anything.

One behaviour does not cross the boundary. The pin dials the next resolved address
when a dial fails with `httpx.ConnectError` or `httpx.ConnectTimeout`, and
`httpx2` raises its own unrelated classes, so a destination with several addresses
tries one address here and fails the request rather than the check. Widening that
would mean translating `httpx2` failures into `httpx` ones, which the SDK below
would stop recognising as its own connection errors.
"""

from typing import Any, cast

import httpx2

from grafy_core.egress import EgressPolicy, PinnedPublicAddressTransport


class EgressPinnedHttpx2Transport(httpx2.AsyncBaseTransport):
    """Dial through the shared egress pin from an `httpx2` client."""

    def __init__(self, *, policy: EgressPolicy | None = None) -> None:
        self._pin = PinnedPublicAddressTransport(
            policy=policy,
            # The pin hands the request it decided on straight to the transport
            # underneath, so this library's own transport goes in; the two
            # libraries spell that base class apart.
            transport=cast("Any", httpx2.AsyncHTTPTransport()),
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        # The pin reads and rewrites `url`, `headers` and `extensions`, which
        # `httpx2` spells the same way, then hands the request to the transport
        # underneath it -- this library's own. Both casts say that and nothing more.
        response = await self._pin.handle_async_request(cast("Any", request))
        return cast("httpx2.Response", response)

    async def aclose(self) -> None:
        await self._pin.aclose()


__all__ = ["EgressPinnedHttpx2Transport"]
