import asyncio

from uvicorn import Config, Server

from grafy_agent.ports import SandboxWorkspacePort
from grafy_agent.pydantic_ai_agent import CodingAgentSettings, PydanticAICodingAgent
from grafy_agent_worker.sandbox import (
    DaytonaSandboxSettings,
    DaytonaSandboxWorkspace,
    DockerSandboxSettings,
    DockerSandboxWorkspace,
)
from grafy_core.application.agent_authoring import AgentAuthoringService
from grafy_core.ports.agent_authoring import AgentAuthoringUnitOfWorkPort
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_storage import create_file_storage

from grafy_agent_worker.settings import AgentWorkerSettings
from grafy_agent_worker.worker import AgentWorker
from grafy_agent_worker.execution import SandboxGeneratedReleaseExecutor
from grafy_agent_worker.http import (
    ExecutionRequestAuthenticator,
    create_execution_app,
)


async def run_worker() -> None:
    settings = AgentWorkerSettings()
    database = create_database(settings.resolved_database_url)

    def unit_of_work_factory() -> AgentAuthoringUnitOfWorkPort:
        return SqlAlchemyUnitOfWork(database.sessions)

    authoring = AgentAuthoringService(unit_of_work_factory)
    storage = create_file_storage(
        backend=settings.storage_backend,
        local_root=settings.workspace / "objects",
        s3_endpoint_url=settings.s3_endpoint_url,
        s3_region=settings.s3_region,
        s3_access_key_id=(
            settings.s3_access_key_id.get_secret_value()
            if settings.s3_access_key_id is not None
            else None
        ),
        s3_secret_access_key=(
            settings.s3_secret_access_key.get_secret_value()
            if settings.s3_secret_access_key is not None
            else None
        ),
        s3_force_path_style=settings.s3_force_path_style,
    )
    providers: dict[str, SandboxWorkspacePort] = {}
    daytona: DaytonaSandboxWorkspace | None = None
    daytona_settings = DaytonaSandboxSettings()
    if daytona_settings.api_key is not None:
        daytona = DaytonaSandboxWorkspace(daytona_settings)
        providers["daytona"] = daytona
    docker_settings = DockerSandboxSettings()
    if docker_settings.trusted_development_enabled:
        docker = DockerSandboxWorkspace(docker_settings)
        providers["docker-trusted-development"] = docker
    if not providers:
        await database.dispose()
        raise RuntimeError(
            "No agent sandbox provider is configured; set Daytona credentials or "
            "explicitly enable the trusted-development Docker adapter"
        )
    worker = AgentWorker(
        settings=settings,
        service=authoring,
        coding_agent=PydanticAICodingAgent(CodingAgentSettings()),
        sandboxes=providers,
        storage=storage,
    )
    executor = SandboxGeneratedReleaseExecutor(
        providers,
        max_request_bytes=settings.executor_max_request_bytes,
        max_response_bytes=settings.executor_max_response_bytes,
    )
    authenticator = ExecutionRequestAuthenticator(
        settings.require_executor_hmac_secret(),
        skew_seconds=settings.executor_signature_skew_seconds,
        replay_cache_entries=settings.executor_replay_cache_entries,
    )
    app = create_execution_app(
        executor=executor,
        authenticator=authenticator,
        max_request_bytes=settings.executor_max_request_bytes,
        max_concurrent_executions=settings.executor_max_concurrent_executions,
        max_queued_executions=settings.executor_max_queued_executions,
        admission_timeout_seconds=settings.executor_admission_timeout_seconds,
    )
    server = Server(
        Config(
            app,
            host=settings.executor_host,
            port=settings.executor_port,
            access_log=False,
            lifespan="off",
        )
    )
    try:
        worker_task = asyncio.create_task(worker.run_forever(), name="agent-worker")
        server_task = asyncio.create_task(
            server.serve(),
            name="generated-node-executor",
        )
        done, pending = await asyncio.wait(
            {worker_task, server_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
    finally:
        if daytona is not None:
            await daytona.close()
        await database.dispose()


__all__ = ["run_worker"]
