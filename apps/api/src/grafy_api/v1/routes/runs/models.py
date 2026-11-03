from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.graph_documents import GraphIdentifier
from grafy_core.domain.runs import Run, RunStatus, RunTarget
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.results import StoredResult
from grafy_core.kernel.state import InstanceState

from grafy_api.runs.ports import InstanceStateSnapshot


class RunApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RunTargetRequest(RunApiModel):
    node_id: GraphIdentifier
    call_path: tuple[GraphIdentifier, ...] = ()

    def to_target(self) -> RunTarget:
        return RunTarget(node_id=self.node_id, call_path=self.call_path)


class StartRunRequest(RunApiModel):
    graph_id: GraphIdentifier
    targets: tuple[RunTargetRequest, ...] = ()


class RunResponse(RunApiModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    graph_id: str
    targets: tuple[RunTargetRequest, ...]
    started_by_user_id: UUID | None
    status: RunStatus
    created_at: datetime
    finished_at: datetime | None
    error: str | None

    @classmethod
    def from_run(cls, run: Run) -> "RunResponse":
        return cls(
            id=run.id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            graph_id=run.graph_id,
            targets=tuple(
                RunTargetRequest(node_id=target.node_id, call_path=target.call_path)
                for target in run.targets
            ),
            started_by_user_id=run.started_by_user_id,
            status=run.status,
            created_at=run.created_at,
            finished_at=run.finished_at,
            error=run.error,
        )


class InstanceKeyResponse(RunApiModel):
    project_id: UUID
    graph_id: str
    call_path: tuple[str, ...]
    node_id: str
    map_index: int | None = Field(default=None, ge=0)

    @classmethod
    def from_key(cls, key: InstanceKey) -> "InstanceKeyResponse":
        return cls(
            project_id=UUID(key.project_id),
            graph_id=key.graph_id,
            call_path=key.call_path,
            node_id=key.node_id,
            map_index=key.map_index,
        )


class InstanceStateResponse(RunApiModel):
    key: InstanceKeyResponse
    state: InstanceState
    fingerprint: str
    last_result_fingerprint: str | None
    error: str | None

    @classmethod
    def from_snapshot(cls, snapshot: InstanceStateSnapshot) -> "InstanceStateResponse":
        return cls(
            key=InstanceKeyResponse.from_key(snapshot.key),
            state=snapshot.state,
            fingerprint=snapshot.fingerprint,
            last_result_fingerprint=snapshot.last_result_fingerprint,
            error=snapshot.error,
        )


class InstanceResultResponse(RunApiModel):
    instance: InstanceStateResponse
    result_fingerprint: str | None
    outputs: dict[str, ArtifactOutputValue] | None
    created_at: datetime | None

    @classmethod
    def from_result(
        cls,
        snapshot: InstanceStateSnapshot,
        result: StoredResult | None,
    ) -> "InstanceResultResponse":
        return cls(
            instance=InstanceStateResponse.from_snapshot(snapshot),
            result_fingerprint=None if result is None else result.fingerprint,
            outputs=None if result is None else dict(result.outputs),
            created_at=None if result is None else result.created_at,
        )
