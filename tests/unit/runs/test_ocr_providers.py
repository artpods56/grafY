"""OCR node and provider readers through the Run service and the runner."""

import json
from base64 import b64decode, b64encode
from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path
from typing import ClassVar, final, override
from uuid import UUID, uuid4

import httpx
import pytest
from grafy_api.runs.errors import NodeComputationError
from grafy_api.runs.facts import ApplicationFactsFactory
from grafy_api.runs.node_runner import NodeComputationRunner, NodeComputationRunnerFactory
from grafy_api.runs.service import RunService
from grafy_core.artifact_contracts import (
    IMAGE_REGIONS,
    MARKDOWN,
    TEXT_VALUE,
    ImagePage,
    ImageRegion,
    ImageRegionSet,
    MarkdownValue,
)
from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.contracts.ocr import (
    DocumentOcr,
    DocumentOcrFeature,
    DocumentOcrResult,
    TiffPage,
)
from grafy_core.documents import (
    FILE_ARTIFACTS,
    RASTER_IMAGE_ARTIFACT,
    PdfFile,
    RasterImage,
    TiffFile,
)
from grafy_core.domain.graph_documents import (
    GraphDocument,
    GraphEdge,
    GraphNode,
    GraphOrigin,
    GraphPoint,
)
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.runs import RunStatus, RunTarget
from grafy_core.file_contracts import TIFF_FILE
from grafy_core.kernel.expansion import expand_graph
from grafy_core.kernel.implementation_identity import RegistryImplementationDigests
from grafy_core.kernel.instances import ExpandedGraph
from grafy_core.kernel.memory_results import InMemoryResultStore
from grafy_core.kernel.project import GraphDefinition, ProjectDocument
from grafy_core.kernel.scheduler import ComputationRequest
from grafy_core.kernel.state import InstanceState
from grafy_core.nodes import Node, NodeExecutionContext, UserFacingNodeError
from grafy_core.plugins import (
    NodeSecretInput,
    Plugin,
    PluginRegistry,
    PluginRuntimeContext,
)
from grafy_core.ports.node_secrets import NodeSecretUnavailableError
from grafy_core.runtime.artifact_values import ArtifactValues, inline_model_artifact
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import OutputPersister
from grafy_core.table_contracts import (
    TABLE_DATA,
    Table,
    TableColumn,
    TableValueType,
)
from grafy_plugin_mistral.ocr import (
    API_KEY as MISTRAL_API_KEY,
)
from grafy_plugin_mistral.ocr import (
    MistralOcrConfig,
    MistralOcrInput,
    MistralOcrNode,
    MistralReader,
)
from grafy_storage import LocalFileObjectStore
from grafy_workbench.ocr import OCR
from grafy_workbench.ocr.craft import CRAFT_MODEL
from grafy_workbench.ocr.provider_http import serve_client
from grafy_workbench.ocr.text_regions import TiffTextRegions
from grafy_workbench.table import TABLES
from grafy_workbench.text import TEXT
from PIL import Image
from pydantic import Field, SecretStr

from tests.unit.plugins.test_mistral_ocr import (
    FakeNodeSecrets as MistralFakeSecrets,
)
from tests.unit.plugins.test_mistral_ocr import (
    FakeProvider,
    document_payload,
)
from tests.unit.runs.fakes import (
    PROJECT_ID,
    USER_ID,
    WORKSPACE_ID,
    FakeProjectDocumentSource,
    FakeRunEvents,
    FakeSecretRevisionResolver,
    FakeUnitOfWorkFactory,
)

UV_LOCK = Path(__file__).resolve().parents[3] / "uv.lock"

GRAPH_ID = "main"
PROJECT_KEY = str(PROJECT_ID)
API_KEY = NodeSecretInput(name="api_key", title="API key", config_dependencies=())

FIXTURES = Plugin(slug="test.ocr_fixtures", title="OCR fixtures")
FIXTURES.register_service_contract_dependency(DocumentOcr)
FIXTURES.register_artifact_type_dependency(MARKDOWN)
FIXTURES.register_artifact_type_dependency(TABLE_DATA)
FIXTURES.register_artifact_type_dependency(TEXT_VALUE)
FIXTURES.register(inline_model_artifact(IMAGE_REGIONS, ImageRegionSet))

READ_KEYS: list[str] = []


def _empty_blocks() -> Table:
    return Table(
        columns=[
            TableColumn(id="page", title="page", value_type=TableValueType.INTEGER)
        ],
        rows=[],
    )


def _regions() -> ImageRegionSet:
    return ImageRegionSet(
        pages=[ImagePage(index=0, width=10, height=10)],
        regions=[ImageRegion(page=0, x0=0, y0=0, x1=1, y1=1, kind="text", label="a")],
    )


class FullReader(DocumentOcr):
    features: ClassVar[frozenset[DocumentOcrFeature]] = frozenset(
        {DocumentOcrFeature.BLOCKS, DocumentOcrFeature.REGIONS}
    )

    def __init__(self, *, api_key: SecretStr, label: str = "full") -> None:
        self.api_key = api_key
        self.label = label

    async def read(self, document: RasterImage | PdfFile) -> DocumentOcrResult:
        del document
        READ_KEYS.append(self.api_key.get_secret_value())
        return DocumentOcrResult(
            markdown=MarkdownValue(
                markdown=f"{self.label}:{self.api_key.get_secret_value()}"
            ),
            blocks=_empty_blocks(),
            regions=_regions(),
        )


class BlocksOnlyReader(DocumentOcr):
    features: ClassVar[frozenset[DocumentOcrFeature]] = frozenset({DocumentOcrFeature.BLOCKS})

    def __init__(self, *, api_key: SecretStr) -> None:
        self.api_key = api_key

    async def read(self, document: RasterImage | PdfFile) -> DocumentOcrResult:
        del document
        return DocumentOcrResult(
            markdown=MarkdownValue(markdown="blocks-only"),
            blocks=_empty_blocks(),
            regions=None,
        )


class MissingRegionsReader(DocumentOcr):
    features: ClassVar[frozenset[DocumentOcrFeature]] = frozenset(
        {DocumentOcrFeature.REGIONS}
    )

    async def read(self, document: RasterImage | PdfFile) -> DocumentOcrResult:
        return DocumentOcrResult(markdown=MarkdownValue(markdown="missing regions"))


class UndeclaredRegionsReader(DocumentOcr):
    features: ClassVar[frozenset[DocumentOcrFeature]] = frozenset()

    async def read(self, document: RasterImage | PdfFile) -> DocumentOcrResult:
        return DocumentOcrResult(
            markdown=MarkdownValue(markdown="undeclared regions"),
            regions=_regions(),
        )


class EmptyInput(NodeInput):
    pass


class FullProviderOutput(NodeOutput):
    engine: FullReader


class BlocksProviderOutput(NodeOutput):
    engine: BlocksOnlyReader


class ProviderConfig(NodeConfig):
    label: str = Field(default="shared")


@FIXTURES.node(
    operator_id="test.full_ocr_provider",
    version=1,
    title="Full OCR",
    secret_inputs=(API_KEY,),
    required_capabilities=(PluginRuntimeCapability.NODE_SECRETS,),
)
@final
class FullProvider(Node[ProviderConfig, EmptyInput, FullProviderOutput]):
    """Provide a test node."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: ProviderConfig,
        _inputs: EmptyInput,
        /,
    ) -> FullProviderOutput:
        api_key = await context.secrets.require(API_KEY.name)
        return FullProviderOutput(
            engine=FullReader(api_key=api_key, label=config.label)
        )


@FIXTURES.node(
    operator_id="test.blocks_ocr_provider",
    version=1,
    title="Reducto",
    secret_inputs=(API_KEY,),
    required_capabilities=(PluginRuntimeCapability.NODE_SECRETS,),
)
@final
class BlocksProvider(Node[ProviderConfig, EmptyInput, BlocksProviderOutput]):
    """Provide a test node."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: ProviderConfig,
        _inputs: EmptyInput,
        /,
    ) -> BlocksProviderOutput:
        api_key = await context.secrets.require(API_KEY.name)
        return BlocksProviderOutput(engine=BlocksOnlyReader(api_key=api_key))


class BoxesInput(NodeInput):
    regions: ImageRegionSet = Field(title="Boxes")


class BoxesOutput(NodeOutput):
    text: str


@FIXTURES.node(operator_id="test.draw_boxes", version=1, title="Draw boxes")
@final
class DrawBoxes(Node[NodeConfig, BoxesInput, BoxesOutput]):
    """Provide a test node."""

    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NodeConfig,
        inputs: BoxesInput,
        /,
    ) -> BoxesOutput:
        return BoxesOutput(text=str(len(inputs.regions.regions)))


class RecordingNodeSecrets:
    def __init__(self, keys: Mapping[str, str] | None = None) -> None:
        self.keys: dict[str, str] = dict(keys or {})

    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
        actor_user_id: UUID | None = None,
    ) -> SecretStr:
        del workspace_id, project_id, graph_id, name, dependencies
        key = self.keys.get(str(node_id))
        if key is None:
            raise NodeSecretUnavailableError("Required node secret is not configured")
        return SecretStr(key)

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        del workspace_id, project_id, graph_id, name, dependencies
        return f"revision-{node_id}"


def _node(
    node_id: str,
    operator_id: str,
    *,
    config: Mapping[str, object] | None = None,
) -> GraphNode:
    return GraphNode(
        kind="builtin",
        id=node_id,
        operator_id=operator_id,
        operator_version=1,
        config=dict(config or {}),
        position=GraphPoint(x=0, y=0),
    )


def _edge(
    from_node: str,
    from_port: str,
    to_node: str,
    to_port: str,
) -> GraphEdge:
    return GraphEdge(
        id=f"{from_node}-{from_port}-{to_node}-{to_port}",
        from_node=from_node,
        from_port=from_port,
        to_node=to_node,
        to_port=to_port,
    )


def _expand(
    *nodes: GraphNode,
    edges: Sequence[GraphEdge] = (),
    origins: Sequence[GraphOrigin] = (),
) -> ExpandedGraph:
    document = GraphDocument(
        nodes=tuple(nodes),
        edges=tuple(edges),
        origins=tuple(origins),
    )
    project = ProjectDocument(
        graphs=(GraphDefinition(id=GRAPH_ID, name="Main", document=document),),
    )
    return expand_graph(project, GRAPH_ID, project_id=PROJECT_KEY)


def _png() -> bytes:
    image = Image.new("RGB", (2, 2), color=(1, 2, 3))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _clear_reads() -> None:
    READ_KEYS.clear()


@pytest.fixture
def tiff_windows():
    class Windows:
        calls: list[tuple[UUID, UUID, dict[str, int]]]

        def __init__(self) -> None:
            self.calls = []

        async def __call__(
            self, workspace_id: UUID, artifact_id: UUID, *, page: int
        ) -> TiffPage:
            async def read(*, col: int, row: int, width: int, height: int) -> bytes:
                self.calls.append(
                    (
                        workspace_id,
                        artifact_id,
                        dict(page=page, col=col, row=row, width=width, height=height),
                    )
                )
                return _png()

            return TiffPage(20, 20, read, source_sha256="0" * 64, page=page)

    return Windows()


@pytest.fixture
def harness(tmp_path: Path, tiff_windows):
    uow = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    registry = PluginRegistry()
    registry.install(TEXT)
    registry.install(TABLES)
    registry.install(FIXTURES)
    registry.install(OCR)
    registry.freeze()
    secrets = RecordingNodeSecrets()
    values = ArtifactValues(
        (*registry.artifacts, *FILE_ARTIFACTS, RASTER_IMAGE_ARTIFACT),
        uow=uow,
        storage=storage,
        bucket="artifacts",
        storage_backend="local",
    )
    runtime = NodeRuntime(
        materializer=InputMaterializer(values),
        persister=OutputPersister(values),
    )
    factory = NodeComputationRunnerFactory(
        registry=registry,
        runtime=runtime,
        node_secrets=secrets,
        values=values,
        plugin_context=PluginRuntimeContext(
            workspace=tmp_path,
            storage=storage,
            uow=uow,
            bucket="artifacts",
            values=values,
            open_tiff_page=tiff_windows,
        ),
        max_map_concurrency=2,
    )
    store = InMemoryResultStore()
    runner = factory.for_project(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        store=store,
    )
    return runner, secrets, uow, values, store, registry


async def _write_raster(values: ArtifactValues) -> ArtifactRef:
    from grafy_core.artifact_contracts import RASTER_IMAGE
    from grafy_core.node_context import NodeExecutionContext
    from grafy_core.runtime.materialization import MaterializationProvenance
    from grafy_core.runtime.persistence import ArtifactWriteContext

    return await values.write(
        RASTER_IMAGE.key,
        RasterImage.from_content(_png(), content_type="image/png", filename="page.png"),
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=WORKSPACE_ID, node_id="seed"
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )


def test_features_appear_on_provider_service_outputs() -> None:
    from grafy_api.v1.routes.catalog.models import PortResponse
    from grafy_plugin_mistral.ocr import MistralOcrProviderNode
    from grafy_plugin_reducto.ocr import ReductoOcrProviderNode

    mistral = PortResponse.from_output_port(
        MistralOcrProviderNode.output_contract.ports["engine"]
    )
    reducto = PortResponse.from_output_port(
        ReductoOcrProviderNode.output_contract.ports["engine"]
    )
    assert [entry.model_dump() for entry in mistral.service_features] == [
        {"contract": {"id": "ocr.document", "version": 1}, "features": ["blocks", "regions"]}
    ]
    assert [entry.model_dump() for entry in reducto.service_features] == [
        {"contract": {"id": "ocr.document", "version": 1}, "features": ["blocks"]}
    ]


@pytest.mark.parametrize(
    ("reader", "features", "message"),
    [
        (MissingRegionsReader(), frozenset({"regions"}), "declared regions but returned none"),
        (UndeclaredRegionsReader(), frozenset[str](), "returned regions without declaring it"),
    ],
)
async def test_a_contract_violation_names_the_registered_provider(
    harness: tuple[
        NodeComputationRunner,
        RecordingNodeSecrets,
        InMemoryUnitOfWork,
        ArtifactValues,
        InMemoryResultStore,
        PluginRegistry,
    ],
    reader: DocumentOcr,
    features: frozenset[str],
    message: str,
) -> None:
    from grafy_core.node_ports import ServiceContractKey
    from grafy_core.service_contracts import BoundServiceProvider
    from grafy_workbench.ocr.nodes import OcrNode

    _runner, _secrets, _uow, values, _store, _registry = harness
    runtime = NodeRuntime(
        materializer=InputMaterializer(values),
        persister=OutputPersister(values),
    )
    raster = await _write_raster(values)
    with pytest.raises(UserFacingNodeError, match=f"Registered OCR {message}"):
        await runtime.run_node(
            OcrNode(),
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="ocr"),
            {"document": raster, "engine": reader},
            bound_services={
                "engine": BoundServiceProvider(
                    "Registered OCR", ServiceContractKey("ocr.document", 1), features
                ),
            },
        )


async def test_old_and_new_mistral_nodes_share_a_transcription() -> None:
    payload = document_payload()
    provider = FakeProvider(payload)
    secrets = MistralFakeSecrets(SecretStr("key"))
    context = NodeExecutionContext(
        workspace_id=UUID("00000000-0000-0000-0000-000000000911"),
        project_id=uuid4_safe(),
        graph_id="g",
        node_id="old",
    )
    from grafy_core.nodes import bind_node_secrets

    bound = bind_node_secrets(context, secrets, (MISTRAL_API_KEY,))
    image = RasterImage.from_content(
        _png(), content_type="image/png", filename="page.png"
    )
    old = MistralOcrNode(provider=provider)
    old_out = await old.run(bound, MistralOcrConfig(), MistralOcrInput(image=image))
    reader = MistralReader(
        config=MistralOcrConfig(),
        api_key=SecretStr("key"),
        workspace_id=bound.workspace_id,
        provider=provider,
    )
    new_out = await reader.read(image)
    assert old_out.markdown == new_out.markdown
    assert old_out.markdown.markdown == "# Invoice\n\nTotal 10"


def uuid4_safe() -> UUID:
    return UUID("00000000-0000-0000-0000-000000000912")


async def test_two_providers_each_supply_their_own_key(harness) -> None:
    runner, secrets, uow, values, _store, _registry = harness
    secrets.keys["left-provider"] = "key-left"
    secrets.keys["right-provider"] = "key-right"
    raster = await _write_raster(values)
    graph = _expand(
        _node("left-provider", "test.full_ocr_provider", config={"label": "shared"}),
        _node("right-provider", "test.full_ocr_provider", config={"label": "shared"}),
        _node("left", "ocr.read_document"),
        _node("right", "ocr.read_document"),
        edges=(
            _edge("left-provider", "engine", "left", "engine"),
            _edge("right-provider", "engine", "right", "engine"),
        ),
        origins=(
            GraphOrigin(
                id="o-left",
                to_node="left",
                to_port="document",
                value=raster,
            ),
            GraphOrigin(
                id="o-right",
                to_node="right",
                to_port="document",
                value=raster,
            ),
        ),
    )
    keys = {key.node_id: key for key in graph.instances}
    left = await runner(
        ComputationRequest(
            fingerprint="fp-left",
            instance=graph.instances[keys["left"]],
            upstream_fingerprints={
                keys["left-provider"]: "fp-left-provider",
            },
            service_sources={
                keys["left-provider"]: graph.instances[keys["left-provider"]],
            },
        )
    )
    right = await runner(
        ComputationRequest(
            fingerprint="fp-right",
            instance=graph.instances[keys["right"]],
            upstream_fingerprints={
                keys["right-provider"]: "fp-right-provider",
            },
            service_sources={
                keys["right-provider"]: graph.instances[keys["right-provider"]],
            },
        )
    )
    assert await _markdown(uow, left["markdown"]) == "shared:key-left"
    assert await _markdown(uow, right["markdown"]) == "shared:key-right"
    assert READ_KEYS == ["key-left", "key-right"]


@pytest.mark.parametrize("mapped", [False, True])
async def test_reducto_style_provider_leaves_boxes_unsupported(harness, mapped) -> None:
    runner, secrets, uow, values, store, _registry = harness
    secrets.keys["provider"] = "key"
    raster = await _write_raster(values)
    graph = _expand(
        _node("provider", "test.blocks_ocr_provider"),
        _node("ocr", "ocr.read_document"),
        _node("draw", "test.draw_boxes"),
        edges=(
            _edge("provider", "engine", "ocr", "engine"),
            _edge("ocr", "regions", "draw", "regions"),
        ),
        origins=(
            GraphOrigin(
                id="o-doc",
                to_node="ocr",
                to_port="document",
                value=(
                    ArtifactRefSequence(
                        sequence_id=uuid4(),
                        artifact_type=raster.artifact_type,
                        schema_version=raster.schema_version,
                        item_refs=[raster, raster],
                        ordered=True,
                    )
                    if mapped
                    else raster
                ),
                collection_mode="map" if mapped else "direct",
            ),
        ),
    )
    keys = {key.node_id: key for key in graph.instances}
    ocr_outputs = await runner(
        ComputationRequest(
            fingerprint="fp-ocr",
            instance=graph.instances[keys["ocr"]],
            upstream_fingerprints={keys["provider"]: "fp-provider"},
            service_sources={
                keys["provider"]: graph.instances[keys["provider"]],
            },
        )
    )
    assert "regions" not in ocr_outputs
    assert "markdown" in ocr_outputs
    await store.put_result("fp-ocr", ocr_outputs)
    ref = ocr_outputs["markdown"]
    if mapped:
        assert isinstance(ref, ArtifactRefSequence)
        assert len(ref.item_refs) == 2
        assert ref.metadata["unsupported_outputs"] == {"regions": "Reducto"}
        assert isinstance(ocr_outputs["blocks"], ArtifactRefSequence)
        assert len(ocr_outputs["blocks"].item_refs) == 2
        ref = ref.item_refs[0]
    assert isinstance(ref, ArtifactRef)
    async with uow as unit:
        artifact = await unit.artifacts.get(WORKSPACE_ID, ref.artifact_id)
    assert artifact is not None
    assert artifact.metadata.get("unsupported_outputs") == {"regions": "Reducto"}

    with pytest.raises(NodeComputationError, match="Boxes are not produced by Reducto"):
        await runner(
            ComputationRequest(
                fingerprint="fp-draw",
                instance=graph.instances[keys["draw"]],
                upstream_fingerprints={keys["ocr"]: "fp-ocr"},
                service_sources={},
            )
        )


async def test_an_unfed_reader_plug_is_refused(harness) -> None:
    runner, _secrets, _uow, values, _store, _registry = harness
    raster = await _write_raster(values)
    graph = _expand(
        _node("ocr", "ocr.read_document"),
        origins=(
            GraphOrigin(
                id="o-doc",
                to_node="ocr",
                to_port="document",
                value=raster,
            ),
        ),
    )
    keys = {key.node_id: key for key in graph.instances}
    with pytest.raises(NodeComputationError, match="no incoming connection"):
        await runner(
            ComputationRequest(
                fingerprint="fp-ocr",
                instance=graph.instances[keys["ocr"]],
                upstream_fingerprints={},
                service_sources={},
            )
        )


async def test_a_scan_and_a_pdf_both_reach_the_reader(harness) -> None:
    runner, secrets, uow, values, _store, _registry = harness
    secrets.keys["provider"] = "k"
    from grafy_core.file_contracts import PDF_FILE
    from grafy_core.node_context import NodeExecutionContext
    from grafy_core.runtime.materialization import MaterializationProvenance
    from grafy_core.runtime.persistence import ArtifactWriteContext

    raster = await _write_raster(values)
    pdf = await values.write(
        PDF_FILE.key,
        PdfFile.from_content(
            b"%PDF-1.4 test", content_type="application/pdf", filename="doc.pdf"
        ),
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=WORKSPACE_ID, node_id="seed"
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )
    for label, document in (("scan", raster), ("pdf", pdf)):
        graph = _expand(
            _node("provider", "test.full_ocr_provider", config={"label": label}),
            _node("ocr", "ocr.read_document"),
            edges=(_edge("provider", "engine", "ocr", "engine"),),
            origins=(
                GraphOrigin(
                    id=f"o-{label}",
                    to_node="ocr",
                    to_port="document",
                    value=document,
                ),
            ),
        )
        keys = {key.node_id: key for key in graph.instances}
        outputs = await runner(
            ComputationRequest(
                fingerprint=f"fp-{label}",
                instance=graph.instances[keys["ocr"]],
                upstream_fingerprints={keys["provider"]: f"fp-p-{label}"},
                service_sources={
                    keys["provider"]: graph.instances[keys["provider"]],
                },
            )
        )
        assert await _markdown(uow, outputs["markdown"]) == f"{label}:k"


async def test_run_service_marks_ocr_stale_when_the_provider_changes(
    tmp_path: Path,
) -> None:
    """Provider selection is an edge: swapping it changes the consumer fingerprint."""

    uow_memory = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    registry = PluginRegistry()
    registry.install(TEXT)
    registry.install(TABLES)
    registry.install(FIXTURES)
    registry.install(OCR)
    registry.freeze()
    secrets = RecordingNodeSecrets({"provider": "k1", "other": "k2"})
    values = ArtifactValues(
        (*registry.artifacts, *FILE_ARTIFACTS, RASTER_IMAGE_ARTIFACT),
        uow=uow_memory,
        storage=storage,
        bucket="artifacts",
        storage_backend="local",
    )
    runtime = NodeRuntime(
        materializer=InputMaterializer(values),
        persister=OutputPersister(values),
    )
    runners = NodeComputationRunnerFactory(
        registry=registry,
        runtime=runtime,
        node_secrets=secrets,
        values=values,
        plugin_context=PluginRuntimeContext(
            workspace=tmp_path,
            storage=storage,
            uow=uow_memory,
            bucket="artifacts",
            values=values,
        ),
    )
    stores: dict[UUID, InMemoryResultStore] = {}

    def store_for(workspace_id: UUID) -> InMemoryResultStore:
        return stores.setdefault(workspace_id, InMemoryResultStore())

    raster = await _write_raster(values)
    project = ProjectDocument(
        graphs=(
            GraphDefinition(
                id=GRAPH_ID,
                name="Main",
                document=GraphDocument(
                    nodes=(
                        _node("provider", "test.full_ocr_provider"),
                        _node("ocr", "ocr.read_document"),
                    ),
                    edges=(_edge("provider", "engine", "ocr", "engine"),),
                    origins=(
                        GraphOrigin(
                            id="o-doc",
                            to_node="ocr",
                            to_port="document",
                            value=raster,
                        ),
                    ),
                ),
            ),
        )
    )
    documents = FakeProjectDocumentSource(project)
    events = FakeRunEvents()
    service = RunService(
        documents=documents,
        uow_factory=FakeUnitOfWorkFactory(),
        result_store_factory=store_for,
        facts=ApplicationFactsFactory(
            registry=registry,
            digests=RegistryImplementationDigests(
                {
                    registration.key: (
                        "grafy_workbench.ocr.nodes"
                        if registration.node_class.__module__.startswith("tests.")
                        else registration.node_class.__module__
                    )
                    for registration in registry.nodes
                },
                uv_lock=UV_LOCK,
            ),
            secrets=FakeSecretRevisionResolver({"api_key": "rev-1"}),
        ),
        runners=runners,
        events=events,
        concurrency=2,
        service_operators=registry.service_operators,
    )
    run = await service.start(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        graph_id=GRAPH_ID,
        targets=[RunTarget(node_id="ocr")],
        started_by_user_id=USER_ID,
    )
    finished = await events.until("run_finished", run_id=run.id)
    assert finished.run is not None
    assert finished.run.status is RunStatus.SUCCEEDED

    states = await service.instance_states(
        workspace_id=WORKSPACE_ID, project_id=PROJECT_ID, graph_id=GRAPH_ID
    )
    ocr_state = next(s for s in states if s.key.node_id == "ocr")
    assert ocr_state.state is InstanceState.FRESH
    first_fp = ocr_state.fingerprint

    documents.edit(
        ProjectDocument(
            graphs=(
                GraphDefinition(
                    id=GRAPH_ID,
                    name="Main",
                    document=GraphDocument(
                        nodes=(
                            _node("other", "test.blocks_ocr_provider"),
                            _node("ocr", "ocr.read_document"),
                        ),
                        edges=(_edge("other", "engine", "ocr", "engine"),),
                        origins=(
                            GraphOrigin(
                                id="o-doc",
                                to_node="ocr",
                                to_port="document",
                                value=raster,
                            ),
                        ),
                    ),
                ),
            )
        )
    )
    states = await service.instance_states(
        workspace_id=WORKSPACE_ID, project_id=PROJECT_ID, graph_id=GRAPH_ID
    )
    ocr_state = next(s for s in states if s.key.node_id == "ocr")
    assert ocr_state.state is InstanceState.STALE
    assert ocr_state.fingerprint != first_fp
    await service.close()


async def _markdown(uow: InMemoryUnitOfWork, ref: object) -> str:
    assert isinstance(ref, ArtifactRef)
    async with uow as unit:
        artifact = await unit.artifacts.get(WORKSPACE_ID, ref.artifact_id)
    assert artifact is not None
    payload = artifact.inline_payload
    assert isinstance(payload, dict)
    value = payload["markdown"]
    assert isinstance(value, str)
    return value


@pytest.mark.parametrize("initial_status", [200, 500])
async def test_craft_provider_persists_source_pixel_polygons(
    harness, tiff_windows, monkeypatch: pytest.MonkeyPatch, initial_status: int
) -> None:
    from grafy_core.runtime.materialization import MaterializationProvenance
    from grafy_core.runtime.persistence import ArtifactWriteContext

    runner, secrets, _uow, values, _store, _registry = harness
    secrets.keys["craft"] = "scoped-test-key"
    tiff_bytes = BytesIO()
    Image.new("RGB", (20, 20)).save(tiff_bytes, format="TIFF")
    tiff = await values.write(
        TIFF_FILE.key,
        TiffFile.from_content(
            tiff_bytes.getvalue(), content_type="image/tiff", filename="map.tiff"
        ),
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=WORKSPACE_ID, node_id="seed"
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )

    statuses = iter((initial_status, 200))
    delays: list[float] = []

    async def record_retry(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("grafy_workbench.ocr.provider_http.sleep", record_retry)

    def craft(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/ocr/craft/detect"
        assert request.headers["Authorization"] == "Bearer scoped-test-key"
        assert b64decode(json.loads(request.content)["image_base64"]) == _png()
        status = next(statuses)
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(
            200,
            json={
                "width": 2,
                "height": 2,
                "model": CRAFT_MODEL,
                "polygons": [[[0.0, 0.5], [1.5, 0.0], [2.0, 1.0], [0.5, 1.5]]],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(craft))
    window = {"page": 1, "col": 11, "row": 13, "width": 2, "height": 2}
    graph = _expand(
        _node("craft", "ocr.craft_provider"),
        _node(
            "detect",
            "ocr.detect_tiff_text",
            config={**window, "strategy": "Single crop"},
        ),
        edges=(_edge("craft", "detector", "detect", "detector"),),
        origins=(GraphOrigin(id="scan", to_node="detect", to_port="tiff", value=tiff),),
    )
    keys = {key.node_id: key for key in graph.instances}
    with serve_client(client):
        outputs = await runner(
            ComputationRequest(
                fingerprint="fp-detect",
                instance=graph.instances[keys["detect"]],
                upstream_fingerprints={keys["craft"]: "fp-craft"},
                service_sources={keys["craft"]: graph.instances[keys["craft"]]},
            )
        )
    if initial_status == 500:
        assert len(delays) == 1
        assert 0.25 <= delays[0] <= 0.5
    else:
        assert delays == []
    assert tiff_windows.calls == [(WORKSPACE_ID, tiff.artifact_id, window)]
    output = outputs["regions"]
    assert isinstance(output, ArtifactRef)
    result = await values.resolve(output, WORKSPACE_ID)
    assert isinstance(result, TiffTextRegions)
    assert result.source.artifact_id == tiff.artifact_id
    assert result.window.model_dump() == window
    assert len(result.regions) == 1
    assert result.regions[0].polygon == [
        (11.0, 13.5),
        (12.5, 13.0),
        (13.0, 14.0),
        (11.5, 14.5),
    ]
    assert result.regions[0].text is None


async def test_craft_detector_sends_configured_thresholds_with_each_window():
    from grafy_workbench.ocr.craft import CraftConfig, CraftDetector

    captured: dict[str, object] = {}

    def craft(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"width": 2, "height": 2, "model": CRAFT_MODEL, "polygons": []},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(craft))
    with serve_client(client):
        detector = CraftDetector(
            SecretStr("scoped-test-key"),
            timeout_ms=5_000,
            max_retries=0,
            text_threshold=0.85,
            link_threshold=0.5,
            low_text=0.45,
        )
        regions = await detector.detect(_png(), width=2, height=2)

    assert regions == []
    assert captured == {
        "image_base64": b64encode(_png()).decode("ascii"),
        "text_threshold": 0.85,
        "link_threshold": 0.5,
        "low_text": 0.45,
    }
    assert detector.request_options == {
        "text_threshold": 0.85,
        "link_threshold": 0.5,
        "low_text": 0.45,
    }
    defaults = CraftConfig()
    assert (defaults.text_threshold, defaults.link_threshold, defaults.low_text) == (
        0.7,
        0.4,
        0.4,
    )
