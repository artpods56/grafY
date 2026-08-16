from io import BytesIO
from hashlib import sha256
from uuid import UUID

from grafy_agent.models import (
    AgentLease,
    AgentProgress,
    CapabilityProposal,
    CapabilityProposalReceipt,
    ReleaseProposal,
    ReleaseProposalReceipt,
)
from grafy_core.application.agent_authoring import AgentAuthoringService
from grafy_core.domain.agent_authoring import (
    AgentRunStatus,
    BuildArtifactSet,
    NodeBuildAttempt,
    NodeBuildStatus,
    RuntimeArtifactReference,
)
from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.source_bundles import (
    MAX_SOURCE_BUNDLE_BYTES,
    GeneratedNodeBuildDocument,
)
from grafy_core.ports.storage import FileMetadata, FileStoragePort, SaveFileCommand


class WorkerAuthoringControl:
    """Fenced model-tool adapter over the core authoring application service."""

    def __init__(
        self,
        *,
        service: AgentAuthoringService,
        storage: FileStoragePort,
        storage_bucket: str,
        lease: AgentLease,
        builds: tuple[NodeBuildAttempt, ...],
    ) -> None:
        self._service = service
        self._storage = storage
        self._storage_bucket = storage_bucket
        self._lease = lease
        self._builds = {build.draft_node_id: build for build in builds}

    async def record_progress(
        self,
        lease: AgentLease,
        progress: AgentProgress,
    ) -> None:
        self._require_lease(lease)
        build = (
            self._builds.get(progress.draft_node_id)
            if progress.draft_node_id is not None
            else None
        )
        await self._service.append_run_message(
            workspace_id=lease.workspace_id,
            run_id=lease.run_id,
            message=progress.message,
            draft_node_id=progress.draft_node_id,
            build_attempt_id=build.id if build is not None else None,
            lease_token=lease.lease_token,
            fencing_token=lease.fencing_token,
        )

    async def cancellation_requested(self, lease: AgentLease) -> bool:
        self._require_lease(lease)
        run = await self._service.get_run(lease.workspace_id, lease.run_id)
        return run.status in {AgentRunStatus.CANCELLING, AgentRunStatus.CANCELLED}

    async def request_capabilities(
        self,
        lease: AgentLease,
        proposal: CapabilityProposal,
    ) -> CapabilityProposalReceipt:
        self._require_lease(lease)
        self._require_build(proposal.draft_node_id)
        await self._service.append_run_message(
            workspace_id=lease.workspace_id,
            run_id=lease.run_id,
            message=(
                "Requested runtime capabilities "
                f"{proposal.capabilities.digest}: {proposal.rationale}"
            ),
            draft_node_id=proposal.draft_node_id,
            build_attempt_id=self._builds[proposal.draft_node_id].id,
            lease_token=lease.lease_token,
            fencing_token=lease.fencing_token,
        )
        return CapabilityProposalReceipt(
            capability_digest=proposal.capabilities.digest,
        )

    async def propose_release(
        self,
        lease: AgentLease,
        proposal: ReleaseProposal,
    ) -> ReleaseProposalReceipt:
        self._require_lease(lease)
        build = self._require_build(proposal.draft_node_id)
        verification = proposal.verification
        if (
            verification.source_digest != proposal.source_bundle.source_digest
            or verification.lock_digest != proposal.source_bundle.lock_digest
            or verification.tests_digest != proposal.source_bundle.tests_digest
            or verification.implementation_digest
            != proposal.source_bundle.implementation_digest
        ):
            raise RuntimeError(
                "Release verification does not attest the proposed source bundle"
            )
        if build.status is NodeBuildStatus.CODING:
            build = await self._service.advance_build(
                workspace_id=lease.workspace_id,
                build_attempt_id=build.id,
                status=NodeBuildStatus.TESTING,
                lease_token=lease.lease_token,
                fencing_token=lease.fencing_token,
            )
            self._builds[proposal.draft_node_id] = build
        if build.status is not NodeBuildStatus.TESTING:
            raise RuntimeError(
                f"Build {build.id} cannot propose a release from {build.status.value}"
            )
        if (
            proposal.source_bundle.source_digest
            != proposal.source_bundle.archive.sha256
        ):
            raise RuntimeError(
                "Proposed source digest does not match the source archive"
            )
        source_key = (
            f"generated-nodes/{lease.workspace_id}/{proposal.draft_node_id}/sources/"
            f"{proposal.source_bundle.source_digest}.tar.gz"
        )
        existing = await self._storage.stat(self._storage_bucket, source_key)
        if existing is None:
            # Check the durable database fence after the object-store read and
            # immediately before the only object-store mutation. A revocation can
            # still race two independent systems, so the destination is also an
            # immutable content-addressed key and save must use create semantics.
            await self._service.append_run_message(
                workspace_id=lease.workspace_id,
                run_id=lease.run_id,
                message=(
                    "Staging exact source bundle "
                    f"{proposal.source_bundle.source_digest}"
                ),
                draft_node_id=proposal.draft_node_id,
                build_attempt_id=build.id,
                lease_token=lease.lease_token,
                fencing_token=lease.fencing_token,
            )
            metadata: FileMetadata = {
                "source": "agent-authoring",
                "artifact_kind": "generated-node-source",
                "job_id": str(lease.run_id),
                "sha256": proposal.source_bundle.source_digest,
            }
            try:
                with BytesIO(proposal.source_bundle.archive.data) as stream:
                    stored = await self._storage.save(
                        SaveFileCommand(
                            bucket=self._storage_bucket,
                            path=source_key,
                            stream=stream,
                            content_type="application/gzip",
                            metadata=metadata,
                            allow_overwrite=False,
                        )
                    )
            except ObjectAlreadyExistsError:
                # Another correctly fenced worker may have won the create race.
                # Accept only the exact content-addressed bytes.
                await self._require_stored_source_bundle(
                    source_key,
                    proposal.source_bundle.source_digest,
                )
            else:
                if (
                    stored.byte_size != proposal.source_bundle.archive.byte_count
                    or stored.sha256 != proposal.source_bundle.source_digest
                ):
                    raise RuntimeError(
                        f"Storage did not persist exact source bundle at {source_key!r}"
                    )
        else:
            await self._require_stored_source_bundle(
                source_key,
                proposal.source_bundle.source_digest,
            )
        runtime_artifact = RuntimeArtifactReference(
            provider=verification.runtime_artifact.provider,
            ref=verification.runtime_artifact.reference,
            digest=verification.runtime_artifact.digest,
        )
        build_document = GeneratedNodeBuildDocument(
            source_digest=proposal.source_bundle.source_digest,
            lock_digest=proposal.source_bundle.lock_digest,
            tests_digest=proposal.source_bundle.tests_digest,
            implementation_digest=proposal.source_bundle.implementation_digest,
            manifest=proposal.manifest,
            capabilities=proposal.capabilities,
            runtime_image_digest=verification.runtime_image_digest,
            profile_digest=verification.profile_digest,
            runtime_artifact=runtime_artifact,
        )
        artifacts = BuildArtifactSet(
            source_bundle_key=source_key,
            source_digest=proposal.source_bundle.source_digest,
            lock_digest=proposal.source_bundle.lock_digest,
            tests_digest=proposal.source_bundle.tests_digest,
            build_digest=build_document.digest,
            implementation_digest=proposal.source_bundle.implementation_digest,
            runtime_image_digest=verification.runtime_image_digest,
            profile_digest=verification.profile_digest,
            runtime_artifact=runtime_artifact,
            tests_passed=True,
        )
        # A second durable fence check prevents finalization after lease loss.
        await self._service.append_run_message(
            workspace_id=lease.workspace_id,
            run_id=lease.run_id,
            message=f"Release proposal: {proposal.summary}",
            draft_node_id=proposal.draft_node_id,
            build_attempt_id=build.id,
            lease_token=lease.lease_token,
            fencing_token=lease.fencing_token,
        )
        approved_build = await self._service.request_build_approval(
            workspace_id=lease.workspace_id,
            build_attempt_id=build.id,
            manifest=proposal.manifest,
            capabilities=proposal.capabilities,
            artifacts=artifacts,
            lease_token=lease.lease_token,
            fencing_token=lease.fencing_token,
        )
        self._builds[proposal.draft_node_id] = approved_build
        return ReleaseProposalReceipt(build_attempt_id=approved_build.id)

    def _require_lease(self, lease: AgentLease) -> None:
        if lease != self._lease:
            raise RuntimeError(f"Agent run {lease.run_id} used a stale control lease")

    def _require_build(self, draft_node_id: UUID) -> NodeBuildAttempt:
        try:
            return self._builds[draft_node_id]
        except KeyError as exc:
            raise RuntimeError(
                f"Draft node {draft_node_id} has no build in run {self._lease.run_id}"
            ) from exc

    async def _require_stored_source_bundle(
        self,
        source_key: str,
        source_digest: str,
    ) -> None:
        stream = await self._storage.load(self._storage_bucket, source_key)
        try:
            stored = stream.read(MAX_SOURCE_BUNDLE_BYTES + 1)
        finally:
            stream.close()
        if (
            len(stored) > MAX_SOURCE_BUNDLE_BYTES
            or sha256(stored).hexdigest() != source_digest
        ):
            raise RuntimeError(f"Immutable source bundle collision at {source_key!r}")


__all__ = ["WorkerAuthoringControl"]
