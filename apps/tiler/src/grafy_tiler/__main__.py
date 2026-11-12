"""``python -m grafy_tiler``: serve the tiler with the configured worker count."""

import uvicorn

from .settings import Settings


def main() -> None:
    settings = Settings()  # pyright: ignore[reportCallIssue]
    uvicorn.run(
        "grafy_tiler.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        # Every request is already logged by the API in front of this service.
        access_log=False,
        # Reverse-proxy headers are never trusted: only the API reaches this.
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
