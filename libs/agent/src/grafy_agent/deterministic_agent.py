"""Deterministic coding-agent adapter for local demonstrations and behavioral tests."""

from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from grafy_agent.errors import AgentConfigurationError, AgentRuntimeError
from grafy_agent.models import (
    AgentLease,
    CodingAgentRequest,
    CodingAgentResult,
    SandboxSession,
)
from grafy_agent.ports import (
    AgentAuthoringControlPort,
    SandboxWorkspacePort,
    SourceBundleVerifierPort,
)
from grafy_agent.tools import NodeAuthoringTools
from grafy_core.source_bundles import GeneratedNodeSourceDefinition


class DeterministicNodeProject(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    definition: GeneratedNodeSourceDefinition
    source: str = Field(min_length=1, max_length=1_048_576)
    tests: str = Field(min_length=1, max_length=1_048_576)
    dependencies: tuple[str, ...] = ()
    summary: str = Field(default="Deterministic node implementation", min_length=1)


class DeterministicCodingAgent:
    """Apply an explicit node project plan; never fabricates command success."""

    def __init__(self, projects: dict[UUID, DeterministicNodeProject]) -> None:
        if not projects:
            raise AgentConfigurationError(
                "Deterministic coding agent requires at least one explicit node project"
            )
        self._projects = dict(projects)

    async def run(
        self,
        *,
        request: CodingAgentRequest,
        lease: AgentLease,
        session: SandboxSession,
        profile_id: str,
        sandbox: SandboxWorkspacePort,
        verifier: SourceBundleVerifierPort,
        control: AgentAuthoringControlPort,
    ) -> CodingAgentResult:
        del request
        if await control.cancellation_requested(lease):
            raise AgentRuntimeError(f"Agent run {lease.run_id} was cancelled")
        tools = NodeAuthoringTools(
            sandbox=sandbox,
            session=session,
            control=control,
            verifier=verifier,
            profile_id=profile_id,
            lease=lease,
        )
        for draft_node_id in lease.target_draft_ids:
            try:
                project = self._projects[draft_node_id]
            except KeyError as exc:
                raise AgentConfigurationError(
                    f"No deterministic project is configured for draft {draft_node_id}"
                ) from exc
            await tools.write_file(
                draft_node_id,
                "node.json",
                project.definition.model_dump_json(indent=2) + "\n",
            )
            await tools.write_file(draft_node_id, "src/node.py", project.source)
            await tools.write_file(draft_node_id, "tests/test_node.py", project.tests)
            if project.dependencies:
                added = await tools.uv_add(draft_node_id, project.dependencies)
                if added.exit_code != 0:
                    raise AgentRuntimeError(added.stderr or added.stdout)
            locked = await tools.uv_lock(draft_node_id)
            if locked.exit_code != 0:
                raise AgentRuntimeError(locked.stderr or locked.stdout)
            synced = await tools.uv_sync(draft_node_id)
            if synced.exit_code != 0:
                raise AgentRuntimeError(synced.stderr or synced.stdout)
            tested = await tools.uv_test(draft_node_id)
            if tested.exit_code != 0:
                raise AgentRuntimeError(tested.stderr or tested.stdout)
            await tools.propose_release(draft_node_id, project.summary)
        return CodingAgentResult(
            summary="Deterministic projects were built, tested, and proposed",
            model_name="deterministic-local",
        )


__all__ = ["DeterministicCodingAgent", "DeterministicNodeProject"]
