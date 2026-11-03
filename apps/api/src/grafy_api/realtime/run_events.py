"""Post-commit Run and instance-state fanout to Project rooms."""

import logging
from collections.abc import Callable, Sequence
from uuid import UUID

from grafy_core.domain.identity import ActorContext
from grafy_core.domain.runs import Run
from grafy_core.kernel.instances import InstanceKey
from grafy_core.ports.collaboration import CollaborationUnitOfWorkPort

from grafy_api.realtime.hub import ProjectRoomHub
from grafy_api.realtime.publish import actor_presentation_for
from grafy_api.realtime.protocol import (
    ActiveRunSummary,
    InstanceKeyEntry,
    InstanceStateEntry,
    InstancesChangedMessage,
    RunFinishedMessage,
    RunStartedMessage,
    RunTargetSummary,
)
from grafy_api.runs.ports import InstanceStateSnapshot

logger = logging.getLogger(__name__)


async def run_summary(
    run: Run, uow_factory: Callable[[], CollaborationUnitOfWorkPort]
) -> ActiveRunSummary:
    starter = None
    if run.started_by_user_id is not None:
        starter = await actor_presentation_for(
            uow_factory, ActorContext(user_id=run.started_by_user_id)
        )
    return ActiveRunSummary(
        run_id=run.id,
        graph_id=run.graph_id,
        targets=tuple(
            RunTargetSummary(node_id=target.node_id, call_path=target.call_path)
            for target in run.targets
        ),
        starter=starter,
        started_at=run.created_at,
    )


def instance_key_entry(key: InstanceKey) -> InstanceKeyEntry:
    return InstanceKeyEntry(
        project_id=UUID(key.project_id),
        graph_id=key.graph_id,
        call_path=key.call_path,
        node_id=key.node_id,
        map_index=key.map_index,
    )


def instance_state_entry(snapshot: InstanceStateSnapshot) -> InstanceStateEntry:
    return InstanceStateEntry(
        **instance_key_entry(snapshot.key).model_dump(),
        state=snapshot.state.value,
        fingerprint=snapshot.fingerprint,
        last_result_fingerprint=snapshot.last_result_fingerprint,
        error=None if snapshot.error is None else snapshot.error[:2000],
    )


class ProjectRunEvents:
    def __init__(
        self,
        *,
        hub: ProjectRoomHub,
        uow_factory: Callable[[], CollaborationUnitOfWorkPort],
    ) -> None:
        self._hub = hub
        self._uow_factory = uow_factory

    async def run_started(self, run: Run) -> None:
        try:
            await self._hub.publish_model(
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                message=RunStartedMessage(
                    run=await run_summary(run, self._uow_factory)
                ),
            )
        except Exception:
            logger.exception("run_started_fanout_failed run_id=%s", run.id)

    async def run_finished(self, run: Run) -> None:
        try:
            await self._hub.publish_model(
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                message=RunFinishedMessage(
                    run_id=run.id,
                    status=run.status.value,
                    error=None if run.error is None else run.error[:2000],
                ),
            )
        except Exception:
            logger.exception("run_finished_fanout_failed run_id=%s", run.id)

    async def instances_changed(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        changed: Sequence[InstanceStateSnapshot],
        removed: Sequence[InstanceKey],
    ) -> None:
        try:
            async with self._uow_factory() as uow:
                head = await uow.collaboration.get_head(workspace_id, project_id)
            if head is None:
                return
            await self._hub.publish_model(
                workspace_id=workspace_id,
                project_id=project_id,
                message=InstancesChangedMessage(
                    changed=tuple(instance_state_entry(item) for item in changed),
                    removed=tuple(instance_key_entry(key) for key in removed),
                    head_sequence=head.collaboration_sequence,
                ),
            )
        except Exception:
            logger.exception("instance_state_fanout_failed project_id=%s", project_id)
