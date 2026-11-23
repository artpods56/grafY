"""Code-defined starter Projects and the bundled sample they open on.

ADR 0016 keeps reuse as a copy of a document, not a template aggregate. ADR 0010
keeps Library folders with the people who make them, so the sample is filed at
the Library root and never under a folder this server invents.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol
from uuid import UUID

from grafy_core.application.collaboration import CollaborationService
from grafy_core.application.project_creation import MAIN_GRAPH_ID, MAIN_GRAPH_NAME
from grafy_core.artifacts import ArtifactRef
from grafy_core.canonical_conversions import PNG_FILE_TO_RASTER
from grafy_core.domain.credentials import SharedCredentialBindingMode
from grafy_core.domain.graph_documents import (
    GraphConversion,
    GraphDocument,
    GraphEdge,
    GraphNode,
    GraphNodeLayout,
    GraphOrigin,
    GraphPoint,
    GraphPresentationDocument,
    GraphPresentationLink,
    GraphPresentationViewer,
    GraphPresentationViewerLayout,
)
from grafy_core.domain.identity import ActorContext
from grafy_core.domain.projects import Project
from grafy_core.nodes import ServiceContractKey
from grafy_core.plugins import NodeRegistration, PluginRegistry
from grafy_core.ports.identity import IdentityUnitOfWorkPort

from grafy_api.catalog_packs import CatalogPolicy
from grafy_api.library.models import LibraryItemResponse
from grafy_api.library.service import LibraryService
from grafy_api.project_contracts import StarterId
from grafy_api.starter_samples import SAMPLE_FILENAME, sample_bytes, sample_sha256
from grafy_api.uploads import UploadService

DOCUMENT_OCR_PACK = "document_ocr"
DOCUMENT_OCR_CONTRACT = ServiceContractKey("ocr.document", 1)
PREFERRED_OCR_PROVIDER = "mistral.ocr.provider"
PNG_TYPE = ("file.png", 1)

SAMPLE_VIEWER_ID = "artifact-viewer-sample"
RESULT_VIEWER_ID = "artifact-viewer-result"
RESULT_LINK_ID = "artifact-viewer-edge-result"
ORIGIN_ID = "origin-sample"
OCR_NODE_ID = "ocr"
ENGINE_NODE_ID = "engine"
TABLE_NODE_ID = "tables"
ENGINE_EDGE_ID = "edge-engine"
MARKDOWN_EDGE_ID = "edge-markdown"

_SAMPLE_POINT = GraphPoint(x=40, y=80)
_OCR_POINT = GraphPoint(x=420, y=80)
_ENGINE_POINT = GraphPoint(x=420, y=400)
_TABLE_POINT = GraphPoint(x=800, y=80)
_TRANSCRIBE_RESULT_POINT = GraphPoint(x=800, y=80)
_EXTRACT_RESULT_POINT = GraphPoint(x=1180, y=80)
_NODE_LAYOUT = GraphNodeLayout(width=300, body_height=180)
_VIEWER_LAYOUT = GraphPresentationViewerLayout(width=300, body_height=220)


STARTER_NAMES = {
    StarterId.TRANSCRIBE_PAGE: "Transcribe a scanned page",
    StarterId.EXTRACT_TABLE: "Extract a table from a scanned register",
}


class StarterUnavailableError(Exception):
    """The Workspace cannot open this starter."""


class SharedCredentialRecord(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def provider_kind(self) -> str: ...


class SharedCredentialListing(Protocol):
    async def list_shared(
        self, workspace_id: UUID, provider_kind: str | None = None
    ) -> Sequence[SharedCredentialRecord]: ...


class SharedBindingWriter(Protocol):
    async def set_shared_binding(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        mode: SharedCredentialBindingMode,
        credential_id: UUID | None,
        actor_user_id: UUID,
        expected_head_sequence: int,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class _ProviderChoice:
    registration: NodeRegistration
    credential: SharedCredentialRecord | None


class StarterService:
    """Seed the bundled scan and open a Project that already reads it."""

    def __init__(
        self,
        *,
        uploads: UploadService,
        library: LibraryService,
        collaboration: CollaborationService,
        credentials: SharedCredentialListing,
        node_secrets: SharedBindingWriter,
        registry: PluginRegistry,
        policy: CatalogPolicy,
        identity_uow_factory: Callable[[], IdentityUnitOfWorkPort],
    ) -> None:
        self._uploads = uploads
        self._library = library
        self._collaboration = collaboration
        self._credentials = credentials
        self._node_secrets = node_secrets
        self._registry = registry
        self._policy = policy
        self._identity_uow_factory = identity_uow_factory

    async def seed_sample(
        self, *, workspace_id: UUID, created_by_user_id: UUID | None
    ) -> LibraryItemResponse:
        """Return the Library root copy of the bundled scan, creating it once."""

        digest = sample_sha256()
        for item in await self._library.list_items(workspace_id):
            artifact = item.artifact
            if (
                artifact.artifact_type == PNG_TYPE[0]
                and artifact.schema_version == PNG_TYPE[1]
                and artifact.sha256 == digest
            ):
                return item
        return await self._persist_sample(workspace_id, created_by_user_id)

    async def create_starter(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        starter_id: StarterId,
    ) -> Project:
        subscribed = await self._subscribed_slugs(workspace_id)
        if not self._document_ocr_ready(subscribed):
            raise StarterUnavailableError(
                "This workspace does not have Document OCR turned on."
            )
        item = await self.seed_sample(
            workspace_id=workspace_id, created_by_user_id=actor.user_id
        )
        choice = await self._choose_provider(workspace_id, subscribed)
        document = starter_document(starter_id, _artifact_ref(item), choice)
        creation = await self._collaboration.create_project(
            actor=actor,
            workspace_id=workspace_id,
            name=STARTER_NAMES[starter_id],
            graph_id=MAIN_GRAPH_ID,
            graph_name=MAIN_GRAPH_NAME,
            graph_document=document,
        )
        if choice is not None and choice.credential is not None:
            secret = choice.registration.secret_inputs[0]
            await self._node_secrets.set_shared_binding(
                workspace_id=workspace_id,
                project_id=creation.project.id,
                graph_id=MAIN_GRAPH_ID,
                node_id=ENGINE_NODE_ID,
                name=secret.name,
                mode=SharedCredentialBindingMode.CREDENTIAL,
                credential_id=choice.credential.id,
                actor_user_id=actor.user_id,
                expected_head_sequence=creation.head.collaboration_sequence,
            )
        return creation.project

    async def _persist_sample(
        self, workspace_id: UUID, created_by_user_id: UUID | None
    ) -> LibraryItemResponse:
        payload = sample_bytes()
        target = await self._uploads.create_upload(
            workspace_id=workspace_id,
            created_by_user_id=created_by_user_id,
            filename=SAMPLE_FILENAME,
            byte_size=len(payload),
            content_type="image/png",
        )
        await self._uploads.store_reserved_bytes(
            workspace_id=workspace_id,
            upload_id=target.upload_id,
            stream=BytesIO(payload),
        )
        completed = await self._uploads.complete_upload(
            workspace_id=workspace_id, upload_id=target.upload_id
        )
        artifact_id = completed.upload.artifact_id
        if artifact_id is None:
            raise StarterUnavailableError(
                "The sample page could not be saved to the Library."
            )
        # save_uploaded promotes without placing, so a new copy stays at the root.
        return await self._library.save_uploaded(
            workspace_id=workspace_id,
            artifact_id=artifact_id,
            original_filename=SAMPLE_FILENAME,
        )

    async def _subscribed_slugs(self, workspace_id: UUID) -> frozenset[str]:
        async with self._identity_uow_factory() as uow:
            slugs = await uow.workspace_packs.list_slugs(workspace_id)
        return frozenset(slugs) | self._policy.always_on_slugs

    def _document_ocr_ready(self, subscribed: frozenset[str]) -> bool:
        return DOCUMENT_OCR_PACK in subscribed and self._policy.is_pack_enabled(
            DOCUMENT_OCR_PACK
        )

    async def _choose_provider(
        self, workspace_id: UUID, subscribed: frozenset[str]
    ) -> _ProviderChoice | None:
        visible = _visible_document_ocr_providers(
            self._registry, self._policy, subscribed
        )
        if not visible:
            return None
        classified: list[_ProviderChoice] = []
        unambiguous: list[_ProviderChoice] = []
        for registration in visible:
            choice = await self._classify_provider(workspace_id, registration)
            classified.append(choice)
            if _is_unambiguous(registration, choice.credential):
                unambiguous.append(choice)
        pool = unambiguous or classified
        return _prefer_mistral(pool)

    async def _classify_provider(
        self, workspace_id: UUID, registration: NodeRegistration
    ) -> _ProviderChoice:
        secrets = registration.secret_inputs
        if len(secrets) != 1:
            return _ProviderChoice(registration, None)
        kind = secrets[0].provider_kind
        matches = [
            row
            for row in await self._credentials.list_shared(workspace_id, kind)
            if row.provider_kind == kind
        ]
        credential = matches[0] if len(matches) == 1 else None
        return _ProviderChoice(registration, credential)


def starter_document(
    starter_id: StarterId,
    artifact_ref: ArtifactRef,
    provider: _ProviderChoice | None,
) -> GraphDocument:
    """The canvas a historian opens: the sample, Document OCR, and its reading."""

    sample = GraphPresentationViewer(
        id=SAMPLE_VIEWER_ID,
        position=_SAMPLE_POINT,
        layout=_VIEWER_LAYOUT,
        artifact_ref=artifact_ref,
    )
    ocr = _builtin_node(OCR_NODE_ID, "ocr.read_document", _OCR_POINT)
    nodes = [ocr]
    edges: list[GraphEdge] = []
    if provider is not None:
        port = _document_ocr_output_port(provider.registration)
        nodes.append(
            _builtin_node(
                ENGINE_NODE_ID,
                provider.registration.node_class.operator_id,
                _ENGINE_POINT,
                provider.registration.node_class.operator_version,
            )
        )
        edges.append(
            GraphEdge(
                id=ENGINE_EDGE_ID,
                from_node=ENGINE_NODE_ID,
                from_port=port,
                to_node=OCR_NODE_ID,
                to_port="engine",
            )
        )
    if starter_id is StarterId.EXTRACT_TABLE:
        nodes.append(
            _builtin_node(TABLE_NODE_ID, "table.extract_from_markdown", _TABLE_POINT)
        )
        edges.append(
            GraphEdge(
                id=MARKDOWN_EDGE_ID,
                from_node=OCR_NODE_ID,
                from_port="markdown",
                to_node=TABLE_NODE_ID,
                to_port="markdown",
            )
        )
        result_source = (TABLE_NODE_ID, "table")
        result_point = _EXTRACT_RESULT_POINT
    else:
        result_source = (OCR_NODE_ID, "markdown")
        result_point = _TRANSCRIBE_RESULT_POINT
    result = GraphPresentationViewer(
        id=RESULT_VIEWER_ID,
        position=result_point,
        layout=_VIEWER_LAYOUT,
    )
    return GraphDocument(
        nodes=tuple(nodes),
        edges=tuple(edges),
        origins=(
            GraphOrigin(
                id=ORIGIN_ID,
                to_node=OCR_NODE_ID,
                to_port="document",
                value=artifact_ref,
                source_card_ids=(SAMPLE_VIEWER_ID,),
                conversion_path=(
                    GraphConversion(
                        id=PNG_FILE_TO_RASTER.id,
                        version=PNG_FILE_TO_RASTER.version,
                    ),
                ),
            ),
        ),
        presentation=GraphPresentationDocument(
            viewers=(sample, result),
            links=(
                GraphPresentationLink(
                    id=RESULT_LINK_ID,
                    source_node_id=result_source[0],
                    source_port_name=result_source[1],
                    target_viewer_id=RESULT_VIEWER_ID,
                ),
            ),
        ),
    )


def _artifact_ref(item: LibraryItemResponse) -> ArtifactRef:
    artifact = item.artifact
    return ArtifactRef(
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        schema_version=artifact.schema_version,
        content_hash=artifact.sha256,
    )


def _builtin_node(
    node_id: str,
    operator_id: str,
    position: GraphPoint,
    operator_version: int = 1,
) -> GraphNode:
    return GraphNode(
        kind="builtin",
        id=node_id,
        operator_id=operator_id,
        operator_version=operator_version,
        position=position,
        layout=_NODE_LAYOUT,
    )


def _visible_document_ocr_providers(
    registry: PluginRegistry,
    policy: CatalogPolicy,
    subscribed: frozenset[str],
) -> tuple[NodeRegistration, ...]:
    visible: list[NodeRegistration] = []
    for registration in registry.nodes:
        if registration.role != "provider":
            continue
        if _document_ocr_output_port_or_none(registration) is None:
            continue
        if policy.is_visible(registration, subscribed):
            visible.append(registration)
    return tuple(visible)


def _document_ocr_output_port(registration: NodeRegistration) -> str:
    port = _document_ocr_output_port_or_none(registration)
    if port is None:
        raise StarterUnavailableError(
            "The selected Document OCR provider has no engine output."
        )
    return port


def _document_ocr_output_port_or_none(registration: NodeRegistration) -> str | None:
    for name, port in registration.node_class.output_contract.ports.items():
        if DOCUMENT_OCR_CONTRACT in port.service_contracts:
            return name
    return None


def _is_unambiguous(
    registration: NodeRegistration, credential: SharedCredentialRecord | None
) -> bool:
    secrets = registration.secret_inputs
    if len(secrets) == 0:
        return True
    return len(secrets) == 1 and credential is not None


def _prefer_mistral(choices: Sequence[_ProviderChoice]) -> _ProviderChoice:
    for choice in choices:
        if choice.registration.node_class.operator_id == PREFERRED_OCR_PROVIDER:
            return choice
    return choices[0]
