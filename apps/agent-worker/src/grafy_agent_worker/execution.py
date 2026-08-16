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
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.ports.generated_execution import (
    GeneratedNodeExecutionRequest,
    GeneratedNodeExecutionResult,
)


_OUTPUTS_ADAPTER = TypeAdapter(dict[str, JsonValue])
_RUNTIME_RUNNER = """import asyncio,contextlib,importlib.util,inspect,json,pathlib,resource,sys
input_limit=int(sys.argv[1]); output_limit=int(sys.argv[2]); task_limit=int(sys.argv[3])
resource.setrlimit(resource.RLIMIT_NPROC,(task_limit,task_limit))
resource.setrlimit(resource.RLIMIT_FSIZE,(output_limit,output_limit))
raw=sys.stdin.buffer.read(input_limit+1)
if len(raw)>input_limit: raise RuntimeError('generated-node input exceeds its limit')
inputs=json.loads(raw)
source=pathlib.Path('src/node.py').resolve()
spec=importlib.util.spec_from_file_location('grafy_generated_node',source)
if spec is None or spec.loader is None: raise RuntimeError('could not load generated node')
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
run=getattr(module,'run',None)
if not callable(run): raise RuntimeError('generated node must export callable run(inputs)')
with contextlib.redirect_stdout(sys.stderr): result=run(inputs)
if inspect.isawaitable(result):
 with contextlib.redirect_stdout(sys.stderr): result=asyncio.run(result)
encoded=json.dumps(result,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':')).encode()
if len(encoded)>output_limit: raise RuntimeError('generated-node output exceeds its limit')
sys.stdout.buffer.write(encoded)
"""


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
                        _RUNTIME_RUNNER,
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
