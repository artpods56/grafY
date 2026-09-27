import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from grafy_persistence.database import create_database

from grafy_api.app_state import get_identity
from grafy_api.diagnostics import configure_diagnostics
from grafy_api.health import HealthResponse, health, readiness
from grafy_api.http_errors import register_http_error_handlers
from grafy_api.plugins.runtime.egress import PluginEgressBrokerPolicy
from grafy_api.services.application import (
    acquire_api_owner_lease,
    build_app_identity,
    build_app_resources,
    run_periodic_cleanup,
)
from grafy_api.settings import Settings, get_settings
from grafy_api.v1.routes.artifacts.views import router as artifacts_router
from grafy_api.v1.routes.auth.views import router as auth_router
from grafy_api.v1.routes.catalog.views import router as catalog_router
from grafy_api.v1.routes.collaboration.views import router as collaboration_router
from grafy_api.v1.routes.executions.views import router as executions_router
from grafy_api.v1.routes.library.views import router as library_router
from grafy_api.v1.routes.modules.views import router as modules_router
from grafy_api.v1.routes.node_secrets.views import router as node_secrets_router
from grafy_api.v1.routes.saved_graphs.views import (
    browser_router as graph_browser_router,
)
from grafy_api.v1.routes.saved_graphs.views import (
    folder_router as graph_folders_router,
)
from grafy_api.v1.routes.saved_graphs.views import (
    router as saved_graphs_router,
)
from grafy_api.v1.routes.templates.views import router as templates_router
from grafy_api.v1.routes.uploads.views import router as uploads_router
from grafy_api.v1.routes.workspaces.views import me_router
from grafy_api.v1.routes.workspaces.views import router as workspaces_router


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_diagnostics(
        level=resolved_settings.app.log_level,
        renderer=resolved_settings.app.log_renderer,
    )
    # Reaching an egress policy is what proves the configured destinations parse
    # and the broker image is pinned. Config no longer imports the Plugin runtime,
    # so this composition root builds that policy up front: a deployment with
    # half-wired egress still fails before it serves a request.
    egress_policy = PluginEgressBrokerPolicy.from_config(resolved_settings.egress)
    database = create_database(resolved_settings.app.resolved_database_url)
    identity = build_app_identity(resolved_settings, database)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        owner_lease = acquire_api_owner_lease(
            resolved_settings.app.workspace,
            required=resolved_settings.app.require_single_api_owner,
        )
        try:
            resources = await build_app_resources(
                settings=resolved_settings,
                database=database,
                egress_policy=egress_policy,
                owner_lease=owner_lease,
            )
            try:
                app.state.resources = resources
                cleanup_task = asyncio.create_task(
                    run_periodic_cleanup(
                        settings=resolved_settings,
                        auth_service=identity.auth_service,
                        resources=resources,
                    )
                )
                try:
                    yield
                finally:
                    cleanup_task.cancel()
                    await asyncio.gather(cleanup_task, return_exceptions=True)
            finally:
                try:
                    await resources.cleanup()
                finally:
                    if getattr(app.state, "resources", None) is resources:
                        del app.state.resources
        finally:
            try:
                await database.dispose()
            finally:
                if owner_lease is not None:
                    owner_lease.release()

    application = FastAPI(
        title="Grafy API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    async def browser_abuse_cookie_boundary(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if "/auth/oidc/" in request.url.path:
            browser_key = getattr(request.state, "auth_browser_key", None)
            if isinstance(browser_key, str):
                get_identity(request.app).auth_service.set_browser_abuse_cookie(
                    response,
                    browser_key,
                )
        return response

    application.middleware("http")(browser_abuse_cookie_boundary)

    application.state.identity = identity
    register_http_error_handlers(application)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.app.allowed_cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "Accept-Ranges",
            "Cache-Control",
            "Content-Length",
            "Content-Range",
            "ETag",
            "X-Request-ID",
        ],
    )
    application.add_api_route(
        "/health",
        health,
        methods=["GET"],
        response_model=HealthResponse,
        include_in_schema=False,
    )

    application.add_api_route(
        "/ready",
        readiness,
        methods=["GET"],
        response_model=HealthResponse,
        include_in_schema=False,
    )
    application.include_router(auth_router, prefix="/v1")
    application.include_router(workspaces_router, prefix="/v1")
    application.include_router(me_router, prefix="/v1")
    application.include_router(graph_browser_router, prefix="/v1")
    application.include_router(graph_folders_router, prefix="/v1")
    application.include_router(saved_graphs_router, prefix="/v1")
    application.include_router(collaboration_router, prefix="/v1")
    application.include_router(node_secrets_router, prefix="/v1")
    application.include_router(catalog_router, prefix="/v1")
    application.include_router(modules_router, prefix="/v1")
    application.include_router(templates_router, prefix="/v1")
    application.include_router(uploads_router, prefix="/v1")
    application.include_router(executions_router, prefix="/v1")
    application.include_router(artifacts_router, prefix="/v1")
    application.include_router(library_router, prefix="/v1")
    return application


app = create_app()
