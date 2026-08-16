import asyncio
import os
import subprocess
from uuid import uuid4

import pytest

from grafy_agent.bundles import inspect_node_source_bundle
from grafy_agent.models import (
    AgentLease,
    SandboxExecutionAuthority,
    SandboxExecutionRequest,
    SandboxNetworkMode,
)
from grafy_agent.verification import CleanSandboxSourceBundleVerifier
from grafy_core.domain.agent_authoring import (
    AgentArtifactType,
    AgentPortDirection,
    CapabilityManifest,
    GeneratedNodeManifest,
    GeneratedNodePort,
    RuntimeArtifactReference,
    RuntimeLimits,
)
from grafy_core.nodes import PortShape
from grafy_core.ports.generated_execution import GeneratedNodeExecutionRequest
from grafy_core.source_bundles import (
    GeneratedNodeBuildDocument,
    GeneratedNodeSourceDefinition,
)

from grafy_agent_worker.execution import SandboxGeneratedReleaseExecutor
from grafy_agent_worker.sandbox.docker import (
    DockerSandboxSettings,
    DockerSandboxWorkspace,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("GRAFY_RUN_DOCKER_AGENT_TESTS") != "true",
    reason="set GRAFY_RUN_DOCKER_AGENT_TESTS=true for the real Docker sandbox test",
)


@pytest.mark.asyncio
async def test_exact_bundle_freezes_and_executes_offline_in_real_docker() -> None:
    sandbox = DockerSandboxWorkspace(
        DockerSandboxSettings(trusted_development_enabled=True)
    )
    environment_id = uuid4()
    run_id = uuid4()
    draft_id = uuid4()
    workspace_id = uuid4()
    workspace = await sandbox.ensure_workspace(
        environment_id=environment_id,
        provider_environment_id=None,
        profile_id="python-uv",
    )
    lease = AgentLease(
        workspace_id=workspace_id,
        thread_id=uuid4(),
        environment_id=environment_id,
        run_id=run_id,
        lease_token=uuid4(),
        fencing_token=1,
        target_draft_ids=(draft_id,),
    )
    session = await sandbox.open_session(
        workspace,
        SandboxExecutionAuthority.from_agent_lease(lease),
    )
    manifest = GeneratedNodeManifest(
        title="Triple",
        description="Triple values in Docker.",
        inputs=(
            GeneratedNodePort(
                direction=AgentPortDirection.INPUT,
                name="values",
                artifact_type=AgentArtifactType(
                    id="scalar.integer",
                    schema_version=1,
                ),
                shape=PortShape.MANY,
            ),
        ),
        outputs=(
            GeneratedNodePort(
                direction=AgentPortDirection.OUTPUT,
                name="result",
                artifact_type=AgentArtifactType(
                    id="scalar.integer",
                    schema_version=1,
                ),
                shape=PortShape.MANY,
            ),
        ),
    )
    capabilities = CapabilityManifest(
        runtime=RuntimeLimits(
            cpu_millis=1_000,
            memory_megabytes=512,
            wall_time_seconds=30,
            process_count=16,
            thread_count=16,
            persistent_disk_bytes=2_147_483_648,
            temporary_disk_bytes=67_108_864,
            input_bytes=1_048_576,
            output_bytes=1_048_576,
            outbound_request_count=0,
            outbound_response_bytes=0,
            outbound_total_bytes=0,
        )
    )
    definition = GeneratedNodeSourceDefinition(
        manifest=manifest,
        capabilities=capabilities,
    )
    artifact_reference: str | None = None
    try:
        files = {
            "node/pyproject.toml": (
                "[project]\n"
                'name = "docker-generated-node"\n'
                'version = "0.1.0"\n'
                'requires-python = ">=3.12,<3.13"\n'
                "dependencies = []\n\n"
                "[dependency-groups]\n"
                'dev = ["pytest==8.4.2"]\n\n'
                "[tool.pytest.ini_options]\n"
                'pythonpath = ["."]\n'
                'testpaths = ["tests"]\n'
            ),
            "node/node.json": definition.model_dump_json(indent=2) + "\n",
            "node/src/node.py": (
                "def run(inputs):\n"
                "    return {'result': [value * 3 for value in inputs['values']]}\n"
            ),
            "node/tests/test_node.py": (
                "from src.node import run\n\n"
                "def test_triple():\n"
                "    assert run({'values': [2]}) == {'result': [6]}\n"
            ),
        }
        for path, content in files.items():
            await sandbox.write_text(
                session,
                path=path,
                content=content,
                max_bytes=1_048_576,
            )
        locked = await sandbox.execute(
            session,
            SandboxExecutionRequest(
                argv=("uv", "lock"),
                cwd="node",
                timeout_seconds=180,
                max_output_bytes=1_048_576,
                network_mode=SandboxNetworkMode.PACKAGE_INDEX,
            ),
        )
        assert locked.exit_code == 0, locked.stderr
        archive = await sandbox.export_directory(
            session,
            path="node",
            max_bytes=67_108_864,
        )
        detached = await sandbox.execute(
            session,
            SandboxExecutionRequest(
                argv=(
                    "python3",
                    "-c",
                    (
                        "import subprocess,sys; "
                        "subprocess.Popen([sys.executable,'-c',"
                        '"import pathlib,time; time.sleep(5); '
                        "pathlib.Path('/workspace/detached.txt').write_text('late')\""
                        "],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
                        "stderr=subprocess.DEVNULL,close_fds=True,"
                        "start_new_session=True)"
                    ),
                ),
                cwd="node",
                timeout_seconds=30,
                max_output_bytes=65_536,
                network_mode=SandboxNetworkMode.BLOCKED,
            ),
        )
        assert detached.exit_code == 0, detached.stderr
        with pytest.raises(FileNotFoundError):
            await sandbox.read_text(
                session,
                path="detached.txt",
                max_bytes=1_024,
            )
        await sandbox.terminate_session(session)
        session = await sandbox.open_session(
            workspace,
            SandboxExecutionAuthority(
                execution_id=uuid4(),
                token=uuid4(),
                fencing_token=2,
            ),
        )
        await asyncio.sleep(6)
        with pytest.raises(FileNotFoundError):
            await sandbox.read_text(
                session,
                path="detached.txt",
                max_bytes=1_024,
            )
    finally:
        await sandbox.terminate_session(session)
        await sandbox.destroy_workspace(workspace)

    source_bundle = inspect_node_source_bundle(archive)
    verification = await CleanSandboxSourceBundleVerifier(sandbox).verify(
        lease=lease,
        source_bundle=source_bundle,
        profile_id="python-uv",
    )
    artifact_reference = verification.runtime_artifact.reference
    runtime_artifact = RuntimeArtifactReference(
        provider=verification.runtime_artifact.provider,
        ref=verification.runtime_artifact.reference,
        digest=verification.runtime_artifact.digest,
    )
    document = GeneratedNodeBuildDocument(
        source_digest=verification.source_digest,
        lock_digest=verification.lock_digest,
        tests_digest=verification.tests_digest,
        implementation_digest=verification.implementation_digest,
        manifest=manifest,
        capabilities=capabilities,
        runtime_image_digest=verification.runtime_image_digest,
        profile_digest=verification.profile_digest,
        runtime_artifact=runtime_artifact,
    )
    request = GeneratedNodeExecutionRequest(
        request_id=uuid4(),
        workspace_id=workspace_id,
        node_id=uuid4(),
        revision=1,
        build_digest=document.digest,
        build_document=document,
        inputs={"values": [3, 4]},
    )
    try:
        result = await SandboxGeneratedReleaseExecutor(
            {"docker-trusted-development": sandbox},
            max_request_bytes=1_048_576,
            max_response_bytes=1_048_576,
        ).execute(request)
        assert result.outputs == {"result": [9, 12]}
    finally:
        subprocess.run(
            ("docker", "image", "rm", "--force", artifact_reference),
            check=False,
            capture_output=True,
        )
