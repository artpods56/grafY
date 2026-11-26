"""``python -m grafy_tiler``: serve the tiler with the configured worker count."""

import uvicorn

from grafy_tiler.settings import Settings

# The API pools its connections and drops idle ones after 5 s (httpx's default).
# The tiler must wait clearly longer: when both give up at 5 s, the API reuses a
# connection that is closing and reports the tiler as unavailable.
IDLE_CONNECTION_SECONDS = 30


def main() -> None:
    settings = Settings()  # pyright: ignore[reportCallIssue]
    uvicorn.run(
        "grafy_tiler.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        timeout_keep_alive=IDLE_CONNECTION_SECONDS,
        # Every request is already logged by the API in front of this service.
        access_log=False,
        # Reverse-proxy headers are never trusted: only the API reaches this.
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
