"""Stage a new Project together with its first checkpoint and its head (ADR 0020).

A Project is never half-present: the identity row, the revision-1 checkpoint of its
document and the collaboration head that opens on that checkpoint are written in one
transaction. This module stages those three plus the checkpoint mapping that lets a
later ``checkpoint`` call recognise the head as already durable, and leaves the commit
to the caller so a route can audit in the same transaction.
"""

from datetime import UTC, datetime
from typing import NamedTuple
from uuid import UUID, uuid4

from grafy_core.domain.collaboration import (
    ProjectCheckpointMapping,
    ProjectHead,
)
from grafy_core.domain.projects import Project, ProjectCheckpoint
from grafy_core.kernel.project import ProjectDocument
from grafy_core.ports.collaboration import CollaborationRepositoryPort
from grafy_core.ports.projects import ProjectRepositoryPort

#: The Graph id a new Project opens on when the caller names no other.
MAIN_GRAPH_ID = "main"
#: The name a new Project's first Graph carries when the caller names no other.
MAIN_GRAPH_NAME = "Main"
#: The revision a staged Project starts at. Checkpoints are numbered from one.
INITIAL_CHECKPOINT_REVISION = 1


def _utc_now() -> datetime:
    return datetime.now(UTC)


class StagedProject(NamedTuple):
    """What staging wrote: the rows a caller reads back after committing."""

    project: Project
    checkpoint: ProjectCheckpoint
    head: ProjectHead


async def stage_project(
    project: Project,
    document: ProjectDocument,
    *,
    projects: ProjectRepositoryPort,
    collaboration: CollaborationRepositoryPort,
    room_epoch: UUID | None = None,
    checkpointed_at: datetime | None = None,
) -> StagedProject:
    """Stage Project, checkpoint 1, head and mapping in the caller's transaction.

    The head is opened at collaboration sequence 0 with its checkpoint sequence at
    0 and ``checkpoint_revision`` at the staged revision, so the head is fully
    checkpointed the moment it exists and the first submitted batch is accepted at
    sequence 1.
    """

    if room_epoch is None:
        room_epoch = uuid4()
    checkpointed_at = _utc_now() if checkpointed_at is None else checkpointed_at
    checkpoint = ProjectCheckpoint(
        workspace_id=project.workspace_id,
        project_id=project.id,
        revision=INITIAL_CHECKPOINT_REVISION,
        name=project.name,
        document=document,
        created_at=checkpointed_at,
    )
    head = ProjectHead.for_existing_project(
        workspace_id=project.workspace_id,
        project_id=project.id,
        name=project.name,
        document=document,
        checkpoint_revision=checkpoint.revision,
        room_epoch=room_epoch,
        updated_at=checkpointed_at,
    )
    mapping = ProjectCheckpointMapping(
        workspace_id=project.workspace_id,
        project_id=project.id,
        room_epoch=head.room_epoch,
        collaboration_sequence=head.checkpoint_sequence,
        checkpoint_revision=checkpoint.revision,
    )
    await projects.add(project)
    await projects.add_checkpoint(checkpoint)
    await collaboration.add_head(head)
    await collaboration.add_checkpoint_mapping(mapping)
    return StagedProject(project=project, checkpoint=checkpoint, head=head)


__all__ = [
    "INITIAL_CHECKPOINT_REVISION",
    "MAIN_GRAPH_ID",
    "MAIN_GRAPH_NAME",
    "StagedProject",
    "stage_project",
]
