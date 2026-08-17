import asyncio
from hashlib import sha256
import json
from time import monotonic
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from grafy_agent.errors import AgentRuntimeError
from grafy_agent.models import (
    SandboxExecutionAuthority,
    SandboxExecutionRequest,
    SandboxNetworkMode,
    SandboxRuntimeArtifact,
)
from grafy_agent.ports import SandboxWorkspacePort
from grafy_agent_worker.sandbox.guest import program
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.ports.generated_execution import (
    GeneratedNodeExecutionRequest,
    GeneratedNodeExecutionResult,
)


_OUTPUTS_ADAPTER = TypeAdapter(dict[str, JsonValue])


class SandboxGeneratedReleaseExecutor:
    """Execute one immutable release in a fresh offline provider workspace."""

    def __init__(
        self,
        sandboxes: dict[str, SandboxWorkspacePort],
        *,
        max_request_bytes: int,
        max_response_bytes: int,
    ) -> None:
        if not sandboxes:
            raise ValueError("Generated release executor requires a sandbox provider")
        self._sandboxes = dict(sandboxes)
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes

    async def execute(
        self,
        request: GeneratedNodeExecutionRequest,
        /,
    ) -> GeneratedNodeExecutionResult:
        build = request.build_document
        capabilities = build.capabilities
        if capabilities.secret_refs:
            raise AgentRuntimeError(
                "Generated-node secret capabilities are not supported by this executor"
            )
        if capabilities.object_store:
            raise AgentRuntimeError(
                "Generated-node object-store capabilities are not supported by this executor"
            )
        if capabilities.outbound_http_origins:
            raise AgentRuntimeError(
                "Generated-node outbound HTTP requires the isolated egress proxy"
            )
        try:
            sandbox = self._sandboxes[build.runtime_artifact.provider]
        except KeyError as exc:
            raise AgentRuntimeError(
                "No isolated executor is configured for runtime artifact provider "
                f"{build.runtime_artifact.provider!r}"
            ) from exc

        inputs = json.dumps(
            request.inputs,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        input_limit = min(
            capabilities.runtime.input_bytes,
            self._max_request_bytes,
        )
        if len(inputs) > input_limit:
            raise AgentRuntimeError(
                f"Generated-node input is {len(inputs)} bytes; limit is {input_limit}"
            )
        output_limit = min(
            capabilities.runtime.output_bytes,
            self._max_response_bytes,
        )
        artifact = SandboxRuntimeArtifact(
            provider=build.runtime_artifact.provider,
            reference=build.runtime_artifact.ref,
            digest=build.runtime_artifact.digest,
        )
        workspace = await sandbox.create_runtime_workspace(
            environment_id=uuid4(),
            artifact=artifact,
            limits=capabilities.runtime,
        )
        session = None
        started = monotonic()
        try:
            session = await sandbox.open_session(
                workspace,
                SandboxExecutionAuthority(
                    execution_id=request.request_id,
                    token=uuid4(),
                    fencing_token=1,
                ),
            )
            result = await sandbox.execute(
                session,
                SandboxExecutionRequest(
                    argv=(
                        ".venv/bin/python",
                        "-I",
                        "-c",
                        program("runtime_runner"),
                        str(input_limit),
                        str(output_limit),
                        str(
                            min(
                                capabilities.runtime.process_count,
                                capabilities.runtime.thread_count,
                            )
                        ),
                    ),
                    cwd="node",
                    stdin=inputs,
                    timeout_seconds=capabilities.runtime.wall_time_seconds,
                    max_output_bytes=output_limit,
                    network_mode=SandboxNetworkMode.BLOCKED,
                ),
            )
            if result.exit_code != 0:
                raise AgentRuntimeError(
                    "Generated-node runtime failed with exit status "
                    f"{result.exit_code}; request id {request.request_id}"
                )
            if result.output_truncated:
                raise AgentRuntimeError("Generated-node output exceeded its byte limit")
            try:
                outputs = _OUTPUTS_ADAPTER.validate_json(result.stdout)
            except ValidationError as exc:
                raise AgentRuntimeError(
                    "Generated-node runtime returned invalid JSON outputs"
                ) from exc
            execution_digest = sha256(
                request.canonical_json_bytes()
                + b"\x00"
                + json.dumps(
                    outputs,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            return GeneratedNodeExecutionResult(
                request_id=request.request_id,
                outputs=outputs,
                execution_digest=execution_digest,
                duration_ms=max(
                    result.duration_ms,
                    int((monotonic() - started) * 1_000),
                ),
            )
        finally:
            try:
                if session is not None:
                    await sandbox.terminate_session(session)
            finally:
                await asyncio.shield(sandbox.destroy_workspace(workspace))


__all__ = ["SandboxGeneratedReleaseExecutor"]
