"""The collaborative life of a Project: head, command batches, checkpoints (ADR 0020).

One Project, one room, one command sequence. This service is the only writer of a
Project head: it opens rooms (``create_project``, ``copy_project``), accepts command
batches (``submit_commands``), makes draft state durable (``checkpoint``), brings a
retained checkpoint back as the current state (``restore_checkpoint``) and closes rooms
(``delete_project``).

Three rules hold throughout:

* **A batch is the unit of acceptance.** ``apply_project_commands`` decides whether the
  whole batch goes in, and an accepted batch advances the collaboration sequence
  exactly once. A rejection leaves the head untouched.
* **A command id is a promise.** The same id, re-submitted with the same signed batch,
  returns the same outcome and does not move the head again. The same id with a
  different batch is an idempotency mismatch, not a retry.
* **Nothing is durable until it is checkpointed.** The head carries the draft; a
  ``ProjectCheckpoint`` is an immutable revision of it, and the way back from an
  accepted change is a restore, which is itself a new checkpoint.

There is no execution lock anywhere here: a run reads a checkpoint and never holds the
document, so an edit is never refused because something is computing.
"""

import hmac
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import NamedTuple
from uuid import UUID, uuid4

from grafy_core.application.identity import authorize_workspace
from grafy_core.application.project_creation import (
    MAIN_GRAPH_ID,
    MAIN_GRAPH_NAME,
    stage_project,
)
from grafy_core.domain.collaboration import (
    AddGraphCommand,
    CollaborationActorKind,
    CommandReceiptOutcome,
    ProjectCheckpointMapping,
    ProjectCommand,
    ProjectCommandReceipt,
    ProjectHead,
    apply_project_commands,
    command_hmac_digest,
    command_requires_exact_sequence,
    empty_project_document,
    sanitize_project_for_cross_workspace_copy,
)
from grafy_core.domain.errors import (
    CapabilityDeniedError,
    CollaborationCommandRejectedError,
    CollaborationHeadConflictError,
    CollaborationIdempotencyMismatchError,
    CollaborationUncheckpointedError,
    ConcurrentWriteError,
    MissingProjectHeadError,
    NotFoundError,
    ProjectCheckpointConflictError,
    UserDisabledError,
)
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceAccess,
    WorkspaceCapability,
)
from grafy_core.domain.projects import (
    Project,
    ProjectCheckpoint,
    validated_project_name,
)
from grafy_core.domain.security_audit import (
    SecurityAuditActorKind,
    SecurityAuditEvent,
    SecurityAuditOutcome,
)
from grafy_core.ports.collaboration import CollaborationUnitOfWorkPort


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ProjectCreation(NamedTuple):
    """What ``create_project`` produced.

    ``receipt`` is present only when the caller passed the ``command_id`` that makes a
    retried creation replayable.
    """

    project: Project
    head: ProjectHead
    receipt: ProjectCommandReceipt | None


class CommandSubmission(NamedTuple):
    """The head after one accepted batch, and the receipt that recorded it."""

    head: ProjectHead
    receipt: ProjectCommandReceipt


class CheckpointOutcome(NamedTuple):
    """The head and the checkpoint revision it is now level with."""

    head: ProjectHead
    revision: int


class ProjectCopy(NamedTuple):
    """The new Project a cross-Workspace copy produced, with its own head.

    ``receipt`` is present only when the caller passed the ``command_id`` that makes a
    retried copy replayable.
    """

    project: Project
    head: ProjectHead
    receipt: ProjectCommandReceipt | None


class CollaborationService:
    """Command acceptance, checkpointing and restore for Project documents."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], CollaborationUnitOfWorkPort],
        *,
        command_hmac_key: bytes,
        command_hmac_key_version: int,
    ) -> None:
        if not command_hmac_key:
            raise ValueError("Command HMAC key must not be empty")
        if command_hmac_key_version < 1:
            raise ValueError("Command HMAC key version must be at least 1")
        self._unit_of_work_factory = unit_of_work_factory
        self._command_hmac_key = command_hmac_key
        self._command_hmac_key_version = command_hmac_key_version

    async def create_project(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        name: str,
        graph_id: str = MAIN_GRAPH_ID,
        graph_name: str = MAIN_GRAPH_NAME,
        project_id: UUID | None = None,
        command_id: UUID | None = None,
    ) -> ProjectCreation:
        """Open a Project with one empty Graph, its checkpoint 1 and its head.

        Pass ``project_id`` and ``command_id`` together to make creation replayable:
        a second call with the same pair and the same payload returns the Project that
        the first call created instead of opening a second one.
        """

        self._require_id_pair(project_id=project_id, command_id=command_id)
        project = Project(
            workspace_id=workspace_id,
            name=name,
            created_by_user_id=actor.user_id,
            id=uuid4() if project_id is None else project_id,
        )
        document = empty_project_document(graph_id, graph_name)
        opening_batch: tuple[ProjectCommand, ...] = (
            AddGraphCommand(graph_id=graph_id, name=graph_name),
        )
        async with self._unit_of_work_factory() as unit_of_work:
            access = await self._authorize(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.CREATE_PROJECT,
                operation="collaboration.project.create",
                resource_id=str(project.id),
            )
            try:
                access.require(WorkspaceCapability.CHECKPOINT_PROJECT)
            except CapabilityDeniedError:
                await self._reject(
                    unit_of_work,
                    actor=actor,
                    workspace_id=workspace_id,
                    operation="collaboration.project.create",
                    error_code="capability_denied",
                    resource_id=str(project.id),
                )
                raise

            replay = await self._opening_replay(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                project_id=project.id,
                name=project.name,
                commands=opening_batch,
                command_id=command_id,
                operation="collaboration.project.create",
            )
            if replay is not None:
                return replay

            staged = await stage_project(
                project,
                document,
                projects=unit_of_work.projects,
                collaboration=unit_of_work.collaboration,
            )
            receipt = await self._stage_opening_receipt(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                project_id=project.id,
                head=staged.head,
                commands=opening_batch,
                command_id=command_id,
            )
            await self._success(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                operation="collaboration.project.create",
                resource_id=str(project.id),
            )
            await unit_of_work.commit()
        return ProjectCreation(
            project=staged.project,
            head=staged.head,
            receipt=receipt,
        )

    async def get_head(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectHead:
        """The draft state a room opens on: document, name and sequence.

        A Project the Workspace does not own is simply not there. A Project that is
        there but has no head is an integrity failure, not an empty room.
        """

        async with self._unit_of_work_factory() as unit_of_work:
            await self._authorize(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.VIEW_PROJECT,
                operation="collaboration.head.read",
                resource_id=str(project_id),
            )
            await self._project_or_raise(unit_of_work, workspace_id, project_id)
            head = await unit_of_work.collaboration.get_head(workspace_id, project_id)
        if head is None:
            raise MissingProjectHeadError(
                workspace_id=workspace_id, project_id=project_id
            )
        return head

    async def submit_commands(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
        command_id: UUID,
        observed_sequence: int,
        observed_room_epoch: UUID,
        commands: Sequence[ProjectCommand],
    ) -> CommandSubmission:
        """Accept one ordered batch against the head, or reject the whole of it.

        The batch is signed over its commands, the sequence the client read and the
        room epoch it read. A repeat of that promise replays the receipt; a different
        promise under the same id is refused. A batch whose first command the head has
        already moved past is refused as a head conflict, so the client reloads.
        """

        if not commands:
            raise CollaborationCommandRejectedError(
                code="empty_batch",
                message="Project command batch must not be empty",
            )
        batch = tuple(commands)
        async with self._unit_of_work_factory() as unit_of_work:
            await self._authorize(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.EDIT_PROJECT,
                operation="collaboration.command.submit",
                resource_id=str(project_id),
            )
            await self._project_or_raise(unit_of_work, workspace_id, project_id)
            digest = self._digest(
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=actor.user_id,
                room_epoch=observed_room_epoch,
                observed_sequence=observed_sequence,
                commands=batch,
            )
            existing = await unit_of_work.collaboration.get_receipt(
                workspace_id,
                project_id,
                command_id,
            )
            if existing is not None:
                if not hmac.compare_digest(existing.command_hmac, digest):
                    await self._reject(
                        unit_of_work,
                        actor=actor,
                        workspace_id=workspace_id,
                        operation="collaboration.command.submit",
                        error_code="idempotency_mismatch",
                        resource_id=str(project_id),
                    )
                    raise CollaborationIdempotencyMismatchError(
                        workspace_id=workspace_id,
                        graph_id=project_id,
                        command_id=command_id,
                    )
                head = await unit_of_work.collaboration.get_head(
                    workspace_id,
                    project_id,
                )
                if head is None:
                    raise MissingProjectHeadError(
                        workspace_id=workspace_id, project_id=project_id
                    )
                return CommandSubmission(
                    head=head,
                    receipt=existing.model_copy(
                        update={"outcome": CommandReceiptOutcome.IDEMPOTENT_REPLAY}
                    ),
                )

            head = await unit_of_work.collaboration.lock_head(workspace_id, project_id)
            if head is None:
                raise MissingProjectHeadError(
                    workspace_id=workspace_id, project_id=project_id
                )
            if head.room_epoch != observed_room_epoch or (
                head.collaboration_sequence < observed_sequence
            ):
                raise await self._head_moved(
                    unit_of_work,
                    actor=actor,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    head=head,
                    expected_sequence=observed_sequence,
                )
            if head.collaboration_sequence > observed_sequence and (
                command_requires_exact_sequence(batch)
            ):
                raise await self._head_moved(
                    unit_of_work,
                    actor=actor,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    head=head,
                    expected_sequence=observed_sequence,
                )

            next_name, next_document = apply_project_commands(
                name=head.name,
                document=head.document,
                commands=batch,
            )
            head.apply_accepted_batch(name=next_name, document=next_document)
            receipt = ProjectCommandReceipt(
                workspace_id=workspace_id,
                project_id=project_id,
                command_id=command_id,
                command_hmac=digest,
                hmac_key_version=self._command_hmac_key_version,
                actor_kind=CollaborationActorKind.USER,
                actor_user_id=actor.user_id,
                room_epoch=head.room_epoch,
                accepted_sequence=head.collaboration_sequence,
                outcome=CommandReceiptOutcome.ACCEPTED,
            )
            await unit_of_work.collaboration.save_head(head)
            await unit_of_work.collaboration.add_receipt(receipt)
            await self._success(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                operation="collaboration.command.submit",
                resource_id=str(project_id),
            )
            await unit_of_work.commit()
        return CommandSubmission(head=head, receipt=receipt)

    async def checkpoint(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
        expected_sequence: int,
        expected_room_epoch: UUID,
    ) -> CheckpointOutcome:
        """Make the head durable as the next immutable Project checkpoint.

        Checkpointing is idempotent for a state already made durable: an already
        fully-checkpointed head returns the revision it is level with rather than
        appending a second copy of the same document.
        """

        async with self._unit_of_work_factory() as unit_of_work:
            await self._authorize(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.CHECKPOINT_PROJECT,
                operation="collaboration.checkpoint",
                resource_id=str(project_id),
            )
            await self._project_or_raise(unit_of_work, workspace_id, project_id)
            head = await unit_of_work.collaboration.lock_head(workspace_id, project_id)
            if head is None:
                raise MissingProjectHeadError(
                    workspace_id=workspace_id, project_id=project_id
                )
            if (
                head.room_epoch != expected_room_epoch
                or head.collaboration_sequence != expected_sequence
            ):
                raise await self._head_moved(
                    unit_of_work,
                    actor=actor,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    head=head,
                    expected_sequence=expected_sequence,
                )
            if head.is_fully_checkpointed:
                mapping = await unit_of_work.collaboration.get_checkpoint_mapping(
                    workspace_id,
                    project_id,
                    room_epoch=head.room_epoch,
                    collaboration_sequence=head.checkpoint_sequence,
                )
                revision = (
                    head.checkpoint_revision
                    if mapping is None
                    else mapping.checkpoint_revision
                )
                return CheckpointOutcome(head=head, revision=revision)

            revision = head.checkpoint_revision + 1
            checkpoint = ProjectCheckpoint(
                workspace_id=workspace_id,
                project_id=project_id,
                revision=revision,
                name=head.name,
                document=head.document,
                created_at=_utc_now(),
            )
            mapping = ProjectCheckpointMapping(
                workspace_id=workspace_id,
                project_id=project_id,
                room_epoch=head.room_epoch,
                collaboration_sequence=head.collaboration_sequence,
                checkpoint_revision=revision,
            )
            head.record_checkpoint(
                sequence=head.collaboration_sequence,
                revision=revision,
            )
            try:
                await unit_of_work.projects.add_checkpoint(checkpoint)
                await unit_of_work.collaboration.add_checkpoint_mapping(mapping)
                await unit_of_work.collaboration.save_head(head)
                await self._success(
                    unit_of_work,
                    actor=actor,
                    workspace_id=workspace_id,
                    operation="collaboration.checkpoint",
                    resource_id=str(project_id),
                )
                await unit_of_work.commit()
            except ConcurrentWriteError as exc:
                raise ProjectCheckpointConflictError(
                    project_id=project_id,
                    expected_revision=revision,
                    actual_revision=None,
                ) from exc
        return CheckpointOutcome(head=head, revision=revision)

    async def restore_checkpoint(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
        revision: int,
        expected_room_epoch: UUID,
        expected_sequence: int,
    ) -> CheckpointOutcome:
        """Make a retained checkpoint the current state, as a new checkpoint.

        Checkpoints are append-only, so restoring does not erase the history that
        followed: the restored document is written forward as a new revision. The room
        epoch is reset so every participant has to rehydrate the restored document, and
        uncheckpointed draft work is refused rather than silently discarded.
        """

        async with self._unit_of_work_factory() as unit_of_work:
            await self._authorize(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.CHECKPOINT_PROJECT,
                operation="collaboration.checkpoint.restore",
                resource_id=str(project_id),
            )
            await self._project_or_raise(unit_of_work, workspace_id, project_id)
            checkpoint = await unit_of_work.projects.get_checkpoint(
                workspace_id,
                project_id,
                revision,
            )
            if checkpoint is None:
                raise NotFoundError("Project checkpoint", f"{project_id}@{revision}")
            head = await unit_of_work.collaboration.lock_head(workspace_id, project_id)
            if head is None:
                raise MissingProjectHeadError(
                    workspace_id=workspace_id, project_id=project_id
                )
            if (
                head.room_epoch != expected_room_epoch
                or head.collaboration_sequence != expected_sequence
            ):
                raise await self._head_moved(
                    unit_of_work,
                    actor=actor,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    head=head,
                    expected_sequence=expected_sequence,
                )
            if not head.is_fully_checkpointed:
                raise await self._uncheckpointed(
                    unit_of_work,
                    actor=actor,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    head=head,
                )

            restored_revision = head.checkpoint_revision + 1
            restored = ProjectCheckpoint(
                workspace_id=workspace_id,
                project_id=project_id,
                revision=restored_revision,
                name=checkpoint.name,
                document=checkpoint.document,
                created_at=_utc_now(),
            )
            # The room reopens rather than rewinds: a fresh epoch and sequence 0 make
            # every participant rehydrate, and the document they get is the restored
            # one. The head's own invariants are checked by its constructor.
            reopened = ProjectHead.for_existing_project(
                workspace_id=workspace_id,
                project_id=project_id,
                name=restored.name,
                document=restored.document,
                checkpoint_revision=restored.revision,
                updated_at=restored.created_at,
            )
            mapping = ProjectCheckpointMapping(
                workspace_id=workspace_id,
                project_id=project_id,
                room_epoch=reopened.room_epoch,
                collaboration_sequence=0,
                checkpoint_revision=restored.revision,
            )
            try:
                await unit_of_work.projects.add_checkpoint(restored)
                await unit_of_work.collaboration.add_checkpoint_mapping(mapping)
                await unit_of_work.collaboration.save_head(reopened)
                await self._success(
                    unit_of_work,
                    actor=actor,
                    workspace_id=workspace_id,
                    operation="collaboration.checkpoint.restore",
                    resource_id=str(project_id),
                )
                await unit_of_work.commit()
            except ConcurrentWriteError as exc:
                raise ProjectCheckpointConflictError(
                    project_id=project_id,
                    expected_revision=restored_revision,
                    actual_revision=None,
                ) from exc
        return CheckpointOutcome(head=reopened, revision=restored_revision)

    async def copy_project(
        self,
        *,
        actor: ActorContext,
        source_workspace_id: UUID,
        source_project_id: UUID,
        target_workspace_id: UUID,
        expected_room_epoch: UUID,
        expected_sequence: int,
        command_id: UUID | None = None,
        project_id: UUID | None = None,
        name: str | None = None,
    ) -> ProjectCopy:
        """Copy a Project's current head into another Workspace.

        The caller needs ``view_project`` where the copy comes from and
        ``create_project`` where it goes. Every Graph is sanitized: workspace-scoped
        references cannot travel, so a copy that would carry one is rejected rather
        than quietly emptied. The source head must still be where the caller read it,
        so a copy never takes a draft the source has moved on from.
        """

        self._require_id_pair(project_id=project_id, command_id=command_id)
        async with self._unit_of_work_factory() as unit_of_work:
            await self._authorize_pair(
                unit_of_work,
                actor=actor,
                requirements=(
                    (source_workspace_id, WorkspaceCapability.VIEW_PROJECT),
                    (target_workspace_id, WorkspaceCapability.CREATE_PROJECT),
                ),
                operation="collaboration.project.copy",
                resource_id=str(source_project_id),
            )
            await self._project_or_raise(
                unit_of_work, source_workspace_id, source_project_id
            )
            source_head = await unit_of_work.collaboration.lock_head(
                source_workspace_id,
                source_project_id,
            )
            if source_head is None:
                raise MissingProjectHeadError(
                    workspace_id=source_workspace_id, project_id=source_project_id
                )
            if (
                source_head.room_epoch != expected_room_epoch
                or source_head.collaboration_sequence != expected_sequence
            ):
                raise await self._head_moved(
                    unit_of_work,
                    actor=actor,
                    workspace_id=source_workspace_id,
                    project_id=source_project_id,
                    head=source_head,
                    expected_sequence=expected_sequence,
                )

            copied_document = sanitize_project_for_cross_workspace_copy(
                source_head.document
            )
            copied_name = (
                source_head.name if name is None else validated_project_name(name)
            )
            resolved_project_id = uuid4() if project_id is None else project_id
            opening_batch = tuple(
                AddGraphCommand(
                    graph_id=graph.id,
                    name=graph.name,
                    document=graph.document,
                )
                for graph in copied_document.graphs
            )
            replay = await self._opening_replay(
                unit_of_work,
                actor=actor,
                workspace_id=target_workspace_id,
                project_id=resolved_project_id,
                name=copied_name,
                commands=opening_batch,
                command_id=command_id,
                operation="collaboration.project.copy",
            )
            if replay is not None:
                project, head, receipt = replay
                return ProjectCopy(project=project, head=head, receipt=receipt)

            project = Project(
                workspace_id=target_workspace_id,
                name=copied_name,
                created_by_user_id=actor.user_id,
                id=resolved_project_id,
            )
            staged = await stage_project(
                project,
                copied_document,
                projects=unit_of_work.projects,
                collaboration=unit_of_work.collaboration,
            )
            receipt = await self._stage_opening_receipt(
                unit_of_work,
                actor=actor,
                workspace_id=target_workspace_id,
                project_id=project.id,
                head=staged.head,
                commands=opening_batch,
                command_id=command_id,
            )
            await self._success(
                unit_of_work,
                actor=actor,
                workspace_id=target_workspace_id,
                operation="collaboration.project.copy",
                resource_id=str(project.id),
            )
            await unit_of_work.commit()
        return ProjectCopy(project=staged.project, head=staged.head, receipt=receipt)

    async def delete_project(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
        expected_room_epoch: UUID | None = None,
        expected_sequence: int | None = None,
    ) -> None:
        """Close a room and remove the Project. Its retained checkpoints go with it.

        With the sequence the caller read, the caller is saying "delete what I am
        looking at" and a moved head stops it. Without one, uncheckpointed draft work
        is refused instead of discarded.
        """

        async with self._unit_of_work_factory() as unit_of_work:
            await self._authorize(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                capability=WorkspaceCapability.DELETE_PROJECT,
                operation="collaboration.project.delete",
                resource_id=str(project_id),
            )
            project = await unit_of_work.projects.get(workspace_id, project_id)
            if project is None:
                raise NotFoundError("Project", str(project_id))
            head = await unit_of_work.collaboration.lock_head(workspace_id, project_id)
            if head is None:
                raise MissingProjectHeadError(
                    workspace_id=workspace_id, project_id=project_id
                )
            if expected_room_epoch is not None and expected_sequence is not None:
                if (
                    head.room_epoch != expected_room_epoch
                    or head.collaboration_sequence != expected_sequence
                ):
                    raise await self._head_moved(
                        unit_of_work,
                        actor=actor,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        head=head,
                        expected_sequence=expected_sequence,
                    )
            elif not head.is_fully_checkpointed:
                raise await self._uncheckpointed(
                    unit_of_work,
                    actor=actor,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    head=head,
                )
            await unit_of_work.collaboration.remove_head(workspace_id, project_id)
            await unit_of_work.projects.remove(workspace_id, project)
            await self._success(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                operation="collaboration.project.delete",
                resource_id=str(project_id),
            )
            await unit_of_work.commit()

    async def _project_or_raise(
        self,
        unit_of_work: CollaborationUnitOfWorkPort,
        workspace_id: UUID,
        project_id: UUID,
    ) -> Project:
        """Tenancy before anything else: this Workspace has no such Project."""

        project = await unit_of_work.projects.get(workspace_id, project_id)
        if project is None:
            raise NotFoundError("Project", str(project_id))
        return project

    def _require_id_pair(
        self,
        *,
        project_id: UUID | None,
        command_id: UUID | None,
    ) -> None:
        """A replayable opening needs an id the retry can find the receipt under."""

        if command_id is not None and project_id is None:
            raise ValueError(
                "A command id replays only when the caller also fixes project_id"
            )

    def _digest(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        actor_user_id: UUID | None,
        room_epoch: UUID,
        observed_sequence: int,
        commands: Sequence[ProjectCommand],
    ) -> bytes:
        return command_hmac_digest(
            self._command_hmac_key,
            key_version=self._command_hmac_key_version,
            workspace_id=workspace_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            room_epoch=room_epoch,
            observed_sequence=observed_sequence,
            commands=commands,
        )

    async def _opening_replay(
        self,
        unit_of_work: CollaborationUnitOfWorkPort,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
        name: str,
        commands: Sequence[ProjectCommand],
        command_id: UUID | None,
        operation: str,
    ) -> ProjectCreation | None:
        """The Project an already-accepted opening created, or ``None``.

        The room epoch is written here rather than read from the client, so a retry
        re-signs with the epoch stored in the receipt: what has to match is the
        payload, the actor and the sequence, not a fresh random epoch.
        """

        if command_id is None:
            return None
        existing = await unit_of_work.collaboration.get_receipt(
            workspace_id,
            project_id,
            command_id,
        )
        if existing is None:
            return None
        head = await unit_of_work.collaboration.get_head(workspace_id, project_id)
        project = await unit_of_work.projects.get(workspace_id, project_id)
        if head is None or project is None:
            raise MissingProjectHeadError(
                workspace_id=workspace_id, project_id=project_id
            )
        digest = self._digest(
            workspace_id=workspace_id,
            project_id=project_id,
            actor_user_id=actor.user_id,
            room_epoch=existing.room_epoch,
            observed_sequence=0,
            commands=commands,
        )
        if not hmac.compare_digest(existing.command_hmac, digest) or head.name != name:
            await self._reject(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                operation=operation,
                error_code="idempotency_mismatch",
                resource_id=str(project_id),
            )
            raise CollaborationIdempotencyMismatchError(
                workspace_id=workspace_id,
                graph_id=project_id,
                command_id=command_id,
            )
        return ProjectCreation(
            project=project,
            head=head,
            receipt=existing.model_copy(
                update={"outcome": CommandReceiptOutcome.IDEMPOTENT_REPLAY}
            ),
        )

    async def _stage_opening_receipt(
        self,
        unit_of_work: CollaborationUnitOfWorkPort,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
        head: ProjectHead,
        commands: Sequence[ProjectCommand],
        command_id: UUID | None,
    ) -> ProjectCommandReceipt | None:
        """Record the batch an opening accepted, when the caller gave a command id."""

        if command_id is None:
            return None
        receipt = ProjectCommandReceipt(
            workspace_id=workspace_id,
            project_id=project_id,
            command_id=command_id,
            command_hmac=self._digest(
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=actor.user_id,
                room_epoch=head.room_epoch,
                observed_sequence=0,
                commands=commands,
            ),
            hmac_key_version=self._command_hmac_key_version,
            actor_kind=CollaborationActorKind.USER,
            actor_user_id=actor.user_id,
            room_epoch=head.room_epoch,
            accepted_sequence=head.collaboration_sequence,
            outcome=CommandReceiptOutcome.ACCEPTED,
        )
        await unit_of_work.collaboration.add_receipt(receipt)
        return receipt

    async def _authorize(
        self,
        unit_of_work: CollaborationUnitOfWorkPort,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        capability: WorkspaceCapability,
        operation: str,
        resource_id: str | None,
    ) -> WorkspaceAccess:
        try:
            return await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=capability,
            )
        except (UserDisabledError, NotFoundError, CapabilityDeniedError) as exc:
            await self._reject(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                operation=operation,
                error_code=_rejection_code(exc),
                resource_id=resource_id,
            )
            raise

    async def _authorize_pair(
        self,
        unit_of_work: CollaborationUnitOfWorkPort,
        *,
        actor: ActorContext,
        requirements: Sequence[tuple[UUID, WorkspaceCapability]],
        operation: str,
        resource_id: str | None,
    ) -> None:
        """Authorize both ends of a copy in a stable order, so they cannot deadlock."""

        for workspace_id, capability in sorted(
            requirements, key=lambda requirement: str(requirement[0])
        ):
            await self._authorize(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
                capability=capability,
                operation=operation,
                resource_id=resource_id,
            )

    async def _head_moved(
        self,
        unit_of_work: CollaborationUnitOfWorkPort,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
        head: ProjectHead,
        expected_sequence: int,
    ) -> CollaborationHeadConflictError:
        await self._reject(
            unit_of_work,
            actor=actor,
            workspace_id=workspace_id,
            operation="collaboration.head.conflict",
            error_code="head_moved",
            resource_id=str(project_id),
        )
        return CollaborationHeadConflictError(
            workspace_id=workspace_id,
            graph_id=project_id,
            expected_sequence=expected_sequence,
            actual_sequence=head.collaboration_sequence,
            room_epoch=head.room_epoch,
        )

    async def _uncheckpointed(
        self,
        unit_of_work: CollaborationUnitOfWorkPort,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        project_id: UUID,
        head: ProjectHead,
    ) -> CollaborationUncheckpointedError:
        await self._reject(
            unit_of_work,
            actor=actor,
            workspace_id=workspace_id,
            operation="collaboration.head.uncheckpointed",
            error_code="uncheckpointed_head",
            resource_id=str(project_id),
        )
        return CollaborationUncheckpointedError(
            workspace_id=workspace_id,
            graph_id=project_id,
            head_sequence=head.collaboration_sequence,
            checkpoint_sequence=head.checkpoint_sequence,
        )

    async def _reject(
        self,
        unit_of_work: CollaborationUnitOfWorkPort,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        operation: str,
        error_code: str,
        resource_id: str | None,
    ) -> None:
        """Commit a refusal before the caller's mutation is staged, so it is not lost."""

        await self._audit(
            unit_of_work,
            actor=actor,
            workspace_id=workspace_id,
            operation=operation,
            outcome=SecurityAuditOutcome.FAILURE,
            resource_id=resource_id,
            error_code=error_code,
        )
        await unit_of_work.commit()

    async def _success(
        self,
        unit_of_work: CollaborationUnitOfWorkPort,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        operation: str,
        resource_id: str,
    ) -> None:
        await self._audit(
            unit_of_work,
            actor=actor,
            workspace_id=workspace_id,
            operation=operation,
            outcome=SecurityAuditOutcome.SUCCESS,
            resource_id=resource_id,
        )

    async def _audit(
        self,
        unit_of_work: CollaborationUnitOfWorkPort,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        operation: str,
        outcome: SecurityAuditOutcome,
        resource_id: str | None,
        error_code: str | None = None,
    ) -> None:
        """Metadata-only: never a command body, a config value or a secret."""

        await unit_of_work.security_audit.add(
            SecurityAuditEvent(
                actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                user_id=actor.user_id,
                credential_reference=actor.credential_reference,
                workspace_id=workspace_id,
                operation=operation,
                outcome=outcome,
                resource_type="project",
                resource_id=resource_id,
                error_code=error_code,
            )
        )


def _rejection_code(exc: Exception) -> str:
    if isinstance(exc, UserDisabledError):
        return "disabled_user"
    if isinstance(exc, NotFoundError):
        return "not_found"
    return "capability_denied"


__all__ = [
    "CheckpointOutcome",
    "CollaborationService",
    "CommandSubmission",
    "ProjectCopy",
    "ProjectCreation",
]
