import asyncio
import base64
from collections.abc import Iterator
import json
from pathlib import Path
from typing import Annotated, cast, final, override
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import Field, SecretStr, StrictStr

from grafy_core.application.modules import ModuleLibraryService
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.errors import NotFoundError, UserDisabledError
from grafy_core.domain.identity import ActorContext
from grafy_core.domain.modules import GraphModuleReference
from grafy_core.domain.saved_graphs import SavedGraphDocument
from grafy_core.artifacts import (
    InMemoryUnitOfWork,
    NoConfig,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.nodes import InPort, Node, NodeExecutionContext, OutPort
from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.plugins import NodeSecretInput, Plugin
from grafy_core.ports.node_secrets import NodeSecretResolverPort
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from grafy_api.app_state import get_resources
from grafy_api.v1.routes.node_secrets.services import NodeSecretService
from grafy_api.services.composition import (
    build_workbench_components,
)
from tests.support.system_plugins import (
    TEST_SYSTEM_PLUGINS,
    build_selected_system_plugin_deployment,
    pin_selected_system_nodes,
)
from grafy_api.v1.routes.auth.models import WorkspaceCreateRequest
from grafy_api.settings import Settings
from grafy_api.v1.models import (
    ArtifactTypeBindingModel,
    ArtifactTypeKeyResponse,
)
from grafy_api.v1.routes.executions.models import (
    RunEdgeRequest,
    RunNodeRequest,
    RunRequest,
)
from grafy_api.v1.routes.modules.dependencies import module_library_service
from grafy_api.v1.routes.modules.models import (
    ImportModuleReleaseRequest,
    PublishModuleReleaseRequest,
)
from grafy_api.v1.routes.node_secrets.dependencies import node_secret_service
from grafy_api.v1.routes.saved_graphs.dependencies import saved_graph_service
from grafy_api.v1.routes.saved_graphs.models import (
    CheckpointGraphRequest,
    CreateSavedGraphRequest,
    GraphPointModel,
    SavedGraphEdgeModel,
    SavedGraphInputPlugModel,
    SavedGraphNodeModel,
    UpdateSavedGraphRequest,
)

from tests.support.clients import GrafyApi
from tests.support.workbench import workbench_dependency_overrides
from tests.testkit import (
    client_with_overrides,
    create_db_url,
    db,
    seed_shared_workspace,
)

WORKSPACE = "00000000-0000-0000-0000-000000000007"


SECRET_MODULE_PLUGIN = Plugin(
    slug="test.module-secret",
    title="Module secret test",
)
SECRET_MODULE_PLUGIN.register_artifact_type_dependency(TEXT_VALUE)


class SecretGateConfig(NodeConfig):
    base_url: StrictStr = Field(min_length=1)


class SecretGateInput(NodeInput):
    text: Annotated[StrictStr, InPort(TEXT_VALUE)]


class SecretGateOutput(NodeOutput):
    text: Annotated[StrictStr, OutPort(TEXT_VALUE)]


@SECRET_MODULE_PLUGIN.node(
    operator_id="test.module_secret_gate",
    version=1,
    title="Module secret gate",
    factory=lambda context: SecretGateNode(context.node_secrets),
    secret_inputs=(
        NodeSecretInput(
            name="api_key",
            title="API key",
            config_dependencies=("base_url",),
        ),
    ),
    required_capabilities=(PluginRuntimeCapability.NODE_SECRETS,),
)
@final
class SecretGateNode(Node[SecretGateConfig, SecretGateInput, SecretGateOutput]):
    def __init__(self, node_secrets: NodeSecretResolverPort) -> None:
        self._node_secrets = node_secrets

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: SecretGateConfig,
        inputs: SecretGateInput,
        /,
    ) -> SecretGateOutput:
        secret = await self._node_secrets.resolve_secret(
            workspace_id=context.workspace_id,
            graph_id=context.secret_graph_id,
            graph_revision=context.secret_graph_revision,
            node_id=context.node_id,
            name="api_key",
            dependencies={"base_url": config.base_url},
        )
        if secret.get_secret_value() != "module-only-key":
            raise RuntimeError("Module secret did not resolve to the expected value")
        return SecretGateOutput(text=f"{inputs.text} authorized")


class OptionalSuffixInput(NodeInput):
    text: Annotated[StrictStr, InPort(TEXT_VALUE)]
    suffix: Annotated[str | None, InPort(TEXT_VALUE)] = None


class OptionalSuffixOutput(NodeOutput):
    text: Annotated[StrictStr, OutPort(TEXT_VALUE)]


@SECRET_MODULE_PLUGIN.node(
    operator_id="test.module_optional_suffix",
    version=1,
    title="Optional module suffix",
)
@final
class OptionalSuffixNode(Node[NodeConfig, OptionalSuffixInput, OptionalSuffixOutput]):
    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NodeConfig,
        inputs: OptionalSuffixInput,
        /,
    ) -> OptionalSuffixOutput:
        suffix = inputs.suffix if inputs.suffix is not None else ""
        return OptionalSuffixOutput(text=f"{inputs.text}{suffix}")


class ModuleProgressInput(NodeInput):
    text: Annotated[StrictStr, InPort(TEXT_VALUE)]


class ModuleProgressOutput(NodeOutput):
    text: Annotated[StrictStr, OutPort(TEXT_VALUE)]


@SECRET_MODULE_PLUGIN.function_node(
    operator_id="test.module_progress",
    version=1,
    title="Module progress",
)
async def module_progress(
    context: NodeExecutionContext,
    _config: NoConfig,
    inputs: ModuleProgressInput,
) -> ModuleProgressOutput:
    await context.progress("Transforming module text", current=1, total=1)
    return ModuleProgressOutput(text=inputs.text.replace("a", "A"))


@pytest.fixture
def module_client(tmp_path: Path) -> Iterator[TestClient]:
    database_url = create_db_url(tmp_path, "modules.sqlite3")

    async def prepare() -> None:
        async with db(database_url) as database:
            await seed_shared_workspace(database)

    asyncio.run(prepare())
    database = create_database(database_url)
    deployment = build_selected_system_plugin_deployment(
        (*TEST_SYSTEM_PLUGINS, SECRET_MODULE_PLUGIN),
    )
    registry = deployment.registry
    saved_graphs = SavedGraphService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        registry,
    )
    module_library = ModuleLibraryService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        registry,
    )
    node_secrets = NodeSecretService(
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions),
        plugin_registry=registry,
        encryption_key=SecretStr(base64.b64encode(b"m" * 32).decode("ascii")),
    )
    components = build_workbench_components(
        plugin_registry=registry,
        workspace=tmp_path / "workbench",
        unit_of_work=InMemoryUnitOfWork(),
        saved_graphs=saved_graphs,
        module_library=module_library,
        node_secrets=node_secrets,
        plugin_releases=cast(PluginReleaseService, deployment.release_lookup),
    )
    overrides = {
        **workbench_dependency_overrides(components),
        saved_graph_service: lambda: saved_graphs,
        node_secret_service: lambda: node_secrets,
        module_library_service: lambda: module_library,
    }
    with client_with_overrides(
        settings=Settings(
            workspace=tmp_path / "workbench",
            database_url=SecretStr(database_url),
        ),
        overrides=overrides,
    ) as client:
        yield client
    asyncio.run(database.dispose())


def _artifact_binding() -> list[ArtifactTypeBindingModel]:
    return [
        ArtifactTypeBindingModel(
            variable="T",
            artifact_type=ArtifactTypeKeyResponse(id="scalar.text", schema_version=1),
        )
    ]


def _saved_graph_document(
    nodes: list[SavedGraphNodeModel],
    edges: list[SavedGraphEdgeModel] | None = None,
) -> SavedGraphDocument:
    serialized_nodes: list[dict[str, object]] = []
    for node in nodes:
        serialized = node.model_dump(mode="json")
        serialized["plugin_release_pin"] = serialized.pop("plugin_release")
        serialized_nodes.append(serialized)
    effective_edges = [] if edges is None else edges
    return SavedGraphDocument.model_validate(
        {
            "nodes": serialized_nodes,
            "edges": [edge.model_dump(mode="json") for edge in effective_edges],
        }
    )


def _module_graph_payload(
    name: str,
    nodes: list[SavedGraphNodeModel],
    edges: list[SavedGraphEdgeModel],
    expected_revision: int | None = None,
) -> dict[str, object]:
    builtin_operators = {
        registration.key
        for plugin in (*TEST_SYSTEM_PLUGINS, SECRET_MODULE_PLUGIN)
        for registration in plugin.nodes
    }
    pinned_nodes: list[SavedGraphNodeModel] = []
    for node in nodes:
        if (node.operator_id, node.operator_version) in builtin_operators:
            pinned_nodes.append(
                node.model_copy(update={"kind": "builtin", "plugin_release": None})
            )
            continue
        if node.operator_id in {"module.input", "module.output"} or (
            node.operator_id.startswith("graph.module.")
        ):
            pinned_nodes.append(
                node.model_copy(update={"kind": "module", "plugin_release": None})
            )
            continue
        pinned_nodes.append(node)
    document = _saved_graph_document(pinned_nodes, edges)
    if expected_revision is None:
        return CreateSavedGraphRequest(
            name=name,
            document=document,
        ).model_dump(mode="json")
    return UpdateSavedGraphRequest(
        name=name,
        expected_revision=expected_revision,
        document=document,
    ).model_dump(mode="json")


def _system_run_request(
    *,
    nodes: list[RunNodeRequest],
    edges: list[RunEdgeRequest] | None = None,
) -> RunRequest:
    return RunRequest(
        nodes=pin_selected_system_nodes(nodes),
        edges=[] if edges is None else edges,
    )


def _text_module_payload(
    *,
    name: str = "Capitalize A",
    replacement: str = "A",
    input_required: bool = True,
    emit_progress: bool = False,
    expected_revision: int | None = None,
) -> dict[str, object]:
    return _module_graph_payload(
        name=name,
        expected_revision=expected_revision,
        nodes=[
            SavedGraphNodeModel(
                kind="module",
                id="module-input",
                operator_id="module.input",
                operator_version=1,
                config={
                    "public_name": "text",
                    "description": "Text to transform",
                    "required": input_required,
                },
                position=GraphPointModel(x=0, y=0),
                artifact_type_bindings=_artifact_binding(),
            ),
            SavedGraphNodeModel(
                kind="builtin",
                id="replace",
                operator_id=(
                    "test.module_progress" if emit_progress else "text.replace"
                ),
                operator_version=1,
                config=(
                    {} if emit_progress else {"search": "a", "replacement": replacement}
                ),
                position=GraphPointModel(x=240, y=0),
            ),
            SavedGraphNodeModel(
                kind="module",
                id="module-output",
                operator_id="module.output",
                operator_version=1,
                config={
                    "public_name": "result",
                    "description": "Transformed text",
                },
                position=GraphPointModel(x=480, y=0),
                artifact_type_bindings=_artifact_binding(),
            ),
        ],
        edges=[
            SavedGraphEdgeModel(
                id="input-to-replace",
                from_node="module-input",
                from_port="value",
                to_node="replace",
                to_port="text",
            ),
            SavedGraphEdgeModel(
                id="replace-to-output",
                from_node="replace",
                from_port="text",
                to_node="module-output",
                to_port="value",
            ),
        ],
    )


def _nested_map_progress_module_payload() -> dict[str, object]:
    return _module_graph_payload(
        name="Nested map progress",
        nodes=[
            SavedGraphNodeModel(
                kind="module",
                id="module-input",
                operator_id="module.input",
                operator_version=1,
                config={"public_name": "text"},
                position=GraphPointModel(x=0, y=0),
                artifact_type_bindings=_artifact_binding(),
            ),
            SavedGraphNodeModel(
                kind="builtin",
                id="split",
                operator_id="text.split",
                operator_version=1,
                config={"separator": ","},
                position=GraphPointModel(x=240, y=120),
            ),
            SavedGraphNodeModel(
                kind="builtin",
                id="progress",
                operator_id="test.module_progress",
                operator_version=1,
                config={},
                position=GraphPointModel(x=480, y=120),
            ),
            SavedGraphNodeModel(
                kind="module",
                id="module-output",
                operator_id="module.output",
                operator_version=1,
                config={"public_name": "result"},
                position=GraphPointModel(x=480, y=0),
                artifact_type_bindings=_artifact_binding(),
            ),
        ],
        edges=[
            SavedGraphEdgeModel(
                id="input-to-split",
                from_node="module-input",
                from_port="value",
                to_node="split",
                to_port="text",
            ),
            SavedGraphEdgeModel(
                id="split-to-progress",
                from_node="split",
                from_port="parts",
                to_node="progress",
                to_port="text",
                collection_mode="map",
            ),
            SavedGraphEdgeModel(
                id="input-to-output",
                from_node="module-input",
                from_port="value",
                to_node="module-output",
                to_port="value",
            ),
        ],
    )


def _secret_module_payload(
    *,
    name: str = "Secret-bearing module",
    expected_revision: int | None = None,
) -> dict[str, object]:
    return _module_graph_payload(
        name=name,
        expected_revision=expected_revision,
        nodes=[
            SavedGraphNodeModel(
                kind="module",
                id="module-input",
                operator_id="module.input",
                operator_version=1,
                config={"public_name": "text"},
                position=GraphPointModel(x=0, y=0),
                artifact_type_bindings=_artifact_binding(),
            ),
            SavedGraphNodeModel(
                kind="builtin",
                id="secret-gate",
                operator_id="test.module_secret_gate",
                operator_version=1,
                config={"base_url": "https://provider.example/v1"},
                position=GraphPointModel(x=240, y=0),
            ),
            SavedGraphNodeModel(
                kind="module",
                id="module-output",
                operator_id="module.output",
                operator_version=1,
                config={"public_name": "result"},
                position=GraphPointModel(x=480, y=0),
                artifact_type_bindings=_artifact_binding(),
            ),
        ],
        edges=[
            SavedGraphEdgeModel(
                id="input-to-gate",
                from_node="module-input",
                from_port="value",
                to_node="secret-gate",
                to_port="text",
            ),
            SavedGraphEdgeModel(
                id="gate-to-output",
                from_node="secret-gate",
                from_port="text",
                to_node="module-output",
                to_port="value",
            ),
        ],
    )


def _optional_input_module_payload() -> dict[str, object]:
    return _module_graph_payload(
        name="Optional suffix module",
        nodes=[
            SavedGraphNodeModel(
                kind="module",
                id="text-input",
                operator_id="module.input",
                operator_version=1,
                config={"public_name": "text"},
                position=GraphPointModel(x=0, y=0),
                artifact_type_bindings=_artifact_binding(),
            ),
            SavedGraphNodeModel(
                kind="module",
                id="suffix-input",
                operator_id="module.input",
                operator_version=1,
                config={"public_name": "suffix", "required": False},
                position=GraphPointModel(x=0, y=120),
                artifact_type_bindings=_artifact_binding(),
            ),
            SavedGraphNodeModel(
                kind="builtin",
                id="append",
                operator_id="test.module_optional_suffix",
                operator_version=1,
                config={},
                position=GraphPointModel(x=240, y=0),
            ),
            SavedGraphNodeModel(
                kind="builtin",
                id="collect",
                operator_id="sequence.collect",
                operator_version=1,
                config={},
                position=GraphPointModel(x=240, y=160),
                input_plugs=[
                    SavedGraphInputPlugModel(id="active-copy", port="items"),
                    SavedGraphInputPlugModel(id="disabled-copy", port="items"),
                ],
                artifact_type_bindings=_artifact_binding(),
            ),
            SavedGraphNodeModel(
                kind="builtin",
                id="pick",
                operator_id="sequence.item_at",
                operator_version=1,
                config={"index": 0},
                position=GraphPointModel(x=480, y=160),
                artifact_type_bindings=_artifact_binding(),
            ),
            SavedGraphNodeModel(
                kind="module",
                id="module-output",
                operator_id="module.output",
                operator_version=1,
                config={"public_name": "result"},
                position=GraphPointModel(x=480, y=0),
                artifact_type_bindings=_artifact_binding(),
            ),
        ],
        edges=[
            SavedGraphEdgeModel(
                id="text-to-append",
                from_node="text-input",
                from_port="value",
                to_node="append",
                to_port="text",
            ),
            SavedGraphEdgeModel(
                id="suffix-to-append",
                from_node="suffix-input",
                from_port="value",
                to_node="append",
                to_port="suffix",
            ),
            SavedGraphEdgeModel(
                id="text-to-collect",
                from_node="text-input",
                from_port="value",
                to_node="collect",
                to_port="items",
                to_plug="active-copy",
            ),
            SavedGraphEdgeModel(
                id="disabled-text-to-collect",
                enabled=False,
                from_node="text-input",
                from_port="value",
                to_node="collect",
                to_port="items",
                to_plug="disabled-copy",
            ),
            SavedGraphEdgeModel(
                id="collect-to-pick",
                from_node="collect",
                from_port="items",
                to_node="pick",
                to_port="items",
            ),
            SavedGraphEdgeModel(
                id="append-to-output",
                from_node="append",
                from_port="text",
                to_node="module-output",
                to_port="value",
            ),
        ],
    )


def _delegating_module_payload(
    *,
    name: str,
    target_graph_id: str,
    target_revision: int,
    expected_revision: int,
) -> dict[str, object]:
    return _module_graph_payload(
        name=name,
        expected_revision=expected_revision,
        nodes=[
            SavedGraphNodeModel(
                kind="module",
                id="module-input",
                operator_id="module.input",
                operator_version=1,
                config={"public_name": "text"},
                position=GraphPointModel(x=0, y=0),
                artifact_type_bindings=_artifact_binding(),
            ),
            SavedGraphNodeModel(
                kind="module",
                id="delegate",
                operator_id=f"graph.module.{target_graph_id}",
                operator_version=target_revision,
                config={},
                position=GraphPointModel(x=240, y=0),
            ),
            SavedGraphNodeModel(
                kind="module",
                id="module-output",
                operator_id="module.output",
                operator_version=1,
                config={"public_name": "result"},
                position=GraphPointModel(x=480, y=0),
                artifact_type_bindings=_artifact_binding(),
            ),
        ],
        edges=[
            SavedGraphEdgeModel(
                id="input-to-delegate",
                from_node="module-input",
                from_port="value",
                to_node="delegate",
                to_port="text",
            ),
            SavedGraphEdgeModel(
                id="delegate-to-output",
                from_node="delegate",
                from_port="result",
                to_node="module-output",
                to_port="value",
            ),
        ],
    )


def _module_node_run(
    result: dict[str, object],
    node_id: str = "module",
) -> dict[str, object]:
    node_runs = cast(list[dict[str, object]], result["node_runs"])
    return next(run for run in node_runs if run["node_id"] == node_id)


def test_direct_module_mutation_requires_current_workspace_authority(
    module_client: TestClient,
) -> None:
    created = module_client.post(
        f"/v1/workspaces/{WORKSPACE}/graphs",
        json=_text_module_payload(),
    ).json()
    graph_id = UUID(created["id"])
    service = get_resources(cast(FastAPI, module_client.app)).module_library

    with pytest.raises(UserDisabledError):
        asyncio.run(
            service.publish_release(
                actor=ActorContext(user_id=UUID(int=999)),
                workspace_id=UUID(WORKSPACE),
                source_graph_id=graph_id,
            )
        )

    assert asyncio.run(service.get_by_source_graph(UUID(WORKSPACE), graph_id)) is None


def test_saved_graph_module_is_discoverable_and_executes_once(
    module_client: TestClient,
) -> None:
    created = module_client.post(
        f"/v1/workspaces/{WORKSPACE}/graphs",
        json=_text_module_payload(),
    ).json()
    graph_id = created["id"]

    api = GrafyApi(module_client)
    catalog = api.workspace(UUID(WORKSPACE)).catalog
    unpublished = catalog.list_nodes().json()
    assert all(node.get("module_graph_id") != graph_id for node in unpublished["nodes"])

    modules = api.workspace(UUID(WORKSPACE)).modules
    published = modules.publish(
        PublishModuleReleaseRequest(source_graph_id=UUID(graph_id))
    )
    assert published.status_code == 201, published.text

    registry_response = catalog.list_nodes()
    assert registry_response.status_code == 200
    registry = registry_response.json()
    assert {
        "slug": "graph.module",
        "title": "Workspace library",
        "origin": "module",
        "entry_kind": "module",
        "scope": None,
        "plugin_release": None,
        "revision": None,
        "publisher": None,
        "installation_scope": None,
        "runnable": True,
        "non_runnable_reason": None,
        "non_runnable_detail": None,
    } in registry["plugins"]
    module_spec = next(
        node for node in registry["nodes"] if node["module_graph_id"] == graph_id
    )
    assert module_spec["operator_id"] == f"graph.module.{graph_id}"
    assert module_spec["module_graph_revision"] == 1
    assert module_spec["catalog_visible"] is True
    assert module_spec["publication_state"] == "published"
    assert [port["name"] for port in module_spec["inputs"]] == ["text"]
    assert [port["name"] for port in module_spec["outputs"]] == ["result"]
    assert registry["unavailable_modules"] == []

    response = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_system_run_request(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="source",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "a cat"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="module",
                    operator_id=module_spec["operator_id"],
                    operator_version=1,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="source",
                    from_port="text",
                    to_node="module",
                    to_port="text",
                )
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "succeeded"
    module_run = _module_node_run(result)
    output = cast(list[dict[str, object]], module_run["outputs"])[0]
    artifacts = cast(list[dict[str, object]], output["artifacts"])
    assert output["kind"] == "single"
    assert artifacts[0]["text"] == '"A cAt"'
    metadata = cast(dict[str, object], artifacts[0]["metadata"])
    assert metadata["producer_node_id"] == "replace"


def test_execution_events_route_nested_nodes_to_each_module_instance(
    module_client: TestClient,
) -> None:
    created = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
        json=_text_module_payload(emit_progress=True),
    ).json()
    operator_id = f"graph.module.{created['id']}"
    started = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/executions",
        json=_system_run_request(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="source",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "a cat"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="module-one",
                    operator_id=operator_id,
                    operator_version=1,
                    config={},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="module-two",
                    operator_id=operator_id,
                    operator_version=1,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="source",
                    from_port="text",
                    to_node="module-one",
                    to_port="text",
                ),
                RunEdgeRequest(
                    from_node="source",
                    from_port="text",
                    to_node="module-two",
                    to_port="text",
                ),
            ],
        ).model_dump(mode="json"),
    ).json()

    response = module_client.get(
        f"/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/{started['execution_id']}/events"
    )
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    nested_paths = {
        tuple(event["node_path"])
        for event in events
        if event["kind"] == "node.status" and len(event["node_path"]) > 1
    }
    progress_paths = [
        tuple(event["node_path"])
        for event in events
        if event["kind"] == "node.progress"
    ]

    assert response.status_code == 200
    assert nested_paths == {
        ("module-one", "replace"),
        ("module-one", "module-output"),
        ("module-two", "replace"),
        ("module-two", "module-output"),
    }
    assert progress_paths == [
        ("module-one", "replace"),
        ("module-two", "replace"),
    ]


def test_mapped_module_events_keep_the_outer_invocation_identity(
    module_client: TestClient,
) -> None:
    created = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
        json=_text_module_payload(emit_progress=True),
    ).json()
    operator_id = f"graph.module.{created['id']}"
    started = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/executions",
        json=_system_run_request(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="source",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "a|ba|ca"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="split",
                    operator_id="text.split",
                    operator_version=1,
                    config={"separator": "|"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="module",
                    operator_id=operator_id,
                    operator_version=1,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="source",
                    from_port="text",
                    to_node="split",
                    to_port="text",
                ),
                RunEdgeRequest(
                    from_node="split",
                    from_port="parts",
                    to_node="module",
                    to_port="text",
                    collection_mode="map",
                ),
            ],
        ).model_dump(mode="json"),
    ).json()

    response = module_client.get(
        f"/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/{started['execution_id']}/events"
    )
    progress_events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ") and '"kind":"node.progress"' in line
    ]

    assert response.status_code == 200
    assert sorted(
        (
            tuple(event["node_path"]),
            event["invocation_index"],
            tuple(event["invocation_path"]),
        )
        for event in progress_events
    ) == [
        (("module", "replace"), None, (0,)),
        (("module", "replace"), None, (1,)),
        (("module", "replace"), None, (2,)),
    ]


def test_nested_map_events_append_each_local_invocation_index(
    module_client: TestClient,
) -> None:
    created = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
        json=_nested_map_progress_module_payload(),
    ).json()
    started = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/executions",
        json=_system_run_request(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="source",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "a,b|ca,da"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="split",
                    operator_id="text.split",
                    operator_version=1,
                    config={"separator": "|"},
                ),
                RunNodeRequest(
                    kind="module",
                    id="module",
                    operator_id=f"graph.module.{created['id']}",
                    operator_version=1,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="source",
                    from_port="text",
                    to_node="split",
                    to_port="text",
                ),
                RunEdgeRequest(
                    from_node="split",
                    from_port="parts",
                    to_node="module",
                    to_port="text",
                    collection_mode="map",
                ),
            ],
        ).model_dump(mode="json"),
    ).json()

    response = module_client.get(
        f"/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/{started['execution_id']}/events"
    )
    progress_events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ") and '"kind":"node.progress"' in line
    ]

    assert response.status_code == 200
    assert sorted(
        (
            tuple(event["node_path"]),
            event["invocation_index"],
            tuple(event["invocation_path"]),
        )
        for event in progress_events
    ) == [
        (("module", "progress"), 0, (0, 0)),
        (("module", "progress"), 0, (1, 0)),
        (("module", "progress"), 1, (0, 1)),
        (("module", "progress"), 1, (1, 1)),
    ]


def test_module_uses_existing_map_semantics_and_keeps_revision_pinned(
    module_client: TestClient,
) -> None:
    created = module_client.post(
        f"/v1/workspaces/{WORKSPACE}/graphs",
        json=_text_module_payload(),
    ).json()
    graph_id = created["id"]
    operator_id = f"graph.module.{graph_id}"
    api = GrafyApi(module_client)
    modules = api.workspace(UUID(WORKSPACE)).modules
    assert (
        modules.publish(
            PublishModuleReleaseRequest(source_graph_id=UUID(graph_id))
        ).status_code
        == 201
    )

    mapped_response = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_system_run_request(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="source",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "a|ba|ca"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="split",
                    operator_id="text.split",
                    operator_version=1,
                    config={"separator": "|"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="module",
                    operator_id=operator_id,
                    operator_version=1,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="source",
                    from_port="text",
                    to_node="split",
                    to_port="text",
                ),
                RunEdgeRequest(
                    from_node="split",
                    from_port="parts",
                    to_node="module",
                    to_port="text",
                    collection_mode="map",
                ),
            ],
        ).model_dump(mode="json"),
    )
    assert mapped_response.status_code == 200
    mapped_result = mapped_response.json()
    assert mapped_result["status"] == "succeeded"
    mapped_output = cast(
        list[dict[str, object]],
        _module_node_run(mapped_result)["outputs"],
    )[0]
    assert mapped_output["kind"] == "sequence"
    assert [
        artifact["text"]
        for artifact in cast(list[dict[str, object]], mapped_output["artifacts"])
    ] == ['"A"', '"bA"', '"cA"']

    update_payload = _text_module_payload(replacement="X", expected_revision=1)
    updated_response = module_client.put(
        f"/v1/workspaces/{WORKSPACE}/graphs/{graph_id}",
        json=update_payload,
    )
    assert updated_response.status_code == 200
    assert updated_response.json()["revision"] == 2
    assert (
        modules.publish(
            PublishModuleReleaseRequest(source_graph_id=UUID(graph_id), revision=2)
        ).status_code
        == 201
    )

    catalog = api.workspace(UUID(WORKSPACE)).catalog
    registry = catalog.list_nodes().json()
    module_specs = [
        node for node in registry["nodes"] if node["module_graph_id"] == graph_id
    ]
    assert sorted(
        (spec["module_graph_revision"], spec["catalog_visible"])
        for spec in module_specs
    ) == [(1, False), (2, True)]

    pinned_response = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_system_run_request(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="source",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "a"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="module",
                    operator_id=operator_id,
                    operator_version=1,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="source",
                    from_port="text",
                    to_node="module",
                    to_port="text",
                )
            ],
        ).model_dump(mode="json"),
    )
    pinned_output = cast(
        list[dict[str, object]],
        _module_node_run(pinned_response.json())["outputs"],
    )[0]
    pinned_artifacts = cast(list[dict[str, object]], pinned_output["artifacts"])
    assert pinned_artifacts[0]["text"] == '"A"'


def test_nested_module_omits_absent_optional_input_and_disabled_edges(
    module_client: TestClient,
) -> None:
    created = module_client.post(
        f"/v1/workspaces/{WORKSPACE}/graphs",
        json=_optional_input_module_payload(),
    ).json()
    graph_id = created["id"]
    api = GrafyApi(module_client)
    modules = api.workspace(UUID(WORKSPACE)).modules
    assert (
        modules.publish(
            PublishModuleReleaseRequest(source_graph_id=UUID(graph_id))
        ).status_code
        == 201
    )
    catalog = api.workspace(UUID(WORKSPACE)).catalog
    registry = catalog.list_nodes().json()
    module_spec = next(
        node for node in registry["nodes"] if node["module_graph_id"] == graph_id
    )
    assert [(port["name"], port["required"]) for port in module_spec["inputs"]] == [
        ("text", True),
        ("suffix", False),
    ]

    response = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_system_run_request(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="source",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "hello"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="module",
                    operator_id=module_spec["operator_id"],
                    operator_version=module_spec["operator_version"],
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="source",
                    from_port="text",
                    to_node="module",
                    to_port="text",
                )
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "succeeded"
    output = cast(list[dict[str, object]], _module_node_run(result)["outputs"])[0]
    artifacts = cast(list[dict[str, object]], output["artifacts"])
    assert artifacts[0]["text"] == '"hello"'

    supplied_response = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_system_run_request(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="text-source",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "hello"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="suffix-source",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "!"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="module",
                    operator_id=module_spec["operator_id"],
                    operator_version=module_spec["operator_version"],
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="text-source",
                    from_port="text",
                    to_node="module",
                    to_port="text",
                ),
                RunEdgeRequest(
                    from_node="suffix-source",
                    from_port="text",
                    to_node="module",
                    to_port="suffix",
                ),
            ],
        ).model_dump(mode="json"),
    )

    assert supplied_response.status_code == 200
    supplied_result = supplied_response.json()
    assert supplied_result["status"] == "succeeded"
    supplied_output = cast(
        list[dict[str, object]],
        _module_node_run(supplied_result)["outputs"],
    )[0]
    supplied_artifacts = cast(list[dict[str, object]], supplied_output["artifacts"])
    assert supplied_artifacts[0]["text"] == '"hello!"'


def test_module_catalog_rejects_optional_input_targeting_required_input(
    module_client: TestClient,
) -> None:
    created = module_client.post(
        f"/v1/workspaces/{WORKSPACE}/graphs",
        json=_text_module_payload(
            name="Invalid optional input",
            input_required=False,
        ),
    ).json()
    graph_id = created["id"]
    reason = (
        f"Graph module {graph_id} revision 1 optional public input 'text' edge "
        "'input-to-replace' targets required input 'replace'.'text' "
        "(text.replace@1)"
    )

    api = GrafyApi(module_client)
    modules = api.workspace(UUID(WORKSPACE)).modules
    publish = modules.publish(
        PublishModuleReleaseRequest(source_graph_id=UUID(graph_id))
    )
    assert publish.status_code == 422
    assert reason in publish.json()["detail"]

    catalog = api.workspace(UUID(WORKSPACE)).catalog
    registry = catalog.list_nodes().json()
    assert all(node.get("module_graph_id") != graph_id for node in registry["nodes"])
    assert registry["unavailable_modules"] == []

    response = module_client.post(
        f"/v1/workspaces/{WORKSPACE}/runs",
        json=_system_run_request(
            nodes=[
                RunNodeRequest(
                    kind="module",
                    id="module",
                    operator_id=f"graph.module.{graph_id}",
                    operator_version=1,
                    config={},
                )
            ]
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        f"Saved graph {graph_id} revision 1 is not a valid module: {reason}"
    )


def test_module_catalog_reports_invalid_boundary_wiring(
    module_client: TestClient,
) -> None:
    created = module_client.post(
        f"/v1/workspaces/{WORKSPACE}/graphs",
        json=CreateSavedGraphRequest(
            name="Input without output",
            document=_saved_graph_document(
                [
                    SavedGraphNodeModel(
                        kind="module",
                        id="module-input",
                        operator_id="module.input",
                        operator_version=1,
                        config={"public_name": "text"},
                        position=GraphPointModel(x=0, y=0),
                        artifact_type_bindings=_artifact_binding(),
                    )
                ],
            ),
        ).model_dump(mode="json"),
    ).json()
    graph_id = created["id"]

    api = GrafyApi(module_client)
    modules = api.workspace(UUID(WORKSPACE)).modules
    publish = modules.publish(
        PublishModuleReleaseRequest(source_graph_id=UUID(graph_id))
    )
    assert publish.status_code == 422
    assert (
        "Module Input boundary must connect its 'value' output"
        in publish.json()["detail"]
    )

    catalog = api.workspace(UUID(WORKSPACE)).catalog
    registry = catalog.list_nodes().json()
    assert registry["unavailable_modules"] == []
    assert all(node.get("module_graph_id") != graph_id for node in registry["nodes"])


def test_module_catalog_ignores_graphs_without_module_boundaries(
    module_client: TestClient,
) -> None:
    created = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
        json=CreateSavedGraphRequest(
            name="Ordinary workflow",
            document=_saved_graph_document(
                [
                    SavedGraphNodeModel(
                        kind="builtin",
                        id="source",
                        operator_id="text.input",
                        operator_version=1,
                        config={"text": "hello"},
                        position=GraphPointModel(x=0, y=0),
                    )
                ],
            ),
        ).model_dump(mode="json"),
    ).json()
    graph_id = created["id"]

    api = GrafyApi(module_client)
    catalog = api.workspace(UUID(WORKSPACE)).catalog
    registry = catalog.list_nodes().json()
    assert all(
        node["module_graph_id"] != graph_id
        for node in registry["nodes"]
        if node["plugin_slug"] == "graph.module"
    )
    assert all(
        module["graph_id"] != graph_id for module in registry["unavailable_modules"]
    )


def test_graph_module_required_input_is_rejected_by_compiler(
    module_client: TestClient,
) -> None:
    created = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
        json=_optional_input_module_payload(),
    ).json()

    response = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_system_run_request(
            nodes=[
                RunNodeRequest(
                    kind="module",
                    id="module",
                    operator_id=f"graph.module.{created['id']}",
                    operator_version=created["revision"],
                    config={},
                )
            ]
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        f"Node 'module' (graph.module.{created['id']}@1) required input "
        "'text' has no incoming edge"
    )


def test_nested_module_resolves_secret_from_its_own_pinned_graph(
    module_client: TestClient,
) -> None:
    created = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
        json=_secret_module_payload(),
    ).json()
    graph_id = created["id"]
    # Raw dict on purpose: ConfigureNodeSecretRequest redacts its SecretStr
    # value to "**********" in model_dump(mode="json"), so the wire body must
    # carry the plaintext.
    configured = module_client.put(
        f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph_id}/nodes/secret-gate/secrets/api_key",
        json={"value": "module-only-key", "expected_graph_revision": 1},
    )
    assert configured.status_code == 200
    assert configured.json() == {
        "node_id": "secret-gate",
        "name": "api_key",
        "configured": True,
    }

    update_payload = _secret_module_payload(
        name="Renamed secret-bearing module", expected_revision=1
    )
    assert (
        module_client.put(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{graph_id}",
            json=update_payload,
        ).status_code
        == 200
    )

    response = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_system_run_request(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="source",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "request"},
                ),
                RunNodeRequest(
                    kind="module",
                    id="module",
                    operator_id=f"graph.module.{graph_id}",
                    operator_version=1,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="source",
                    from_port="text",
                    to_node="module",
                    to_port="text",
                )
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "succeeded"
    output = cast(
        list[dict[str, object]],
        _module_node_run(result)["outputs"],
    )[0]
    artifacts = cast(list[dict[str, object]], output["artifacts"])
    assert artifacts[0]["text"] == '"request authorized"'
    assert "module-only-key" not in response.text


def test_exact_module_revision_cycle_reports_the_nested_path(
    module_client: TestClient,
) -> None:
    first = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
        json=_text_module_payload(name="First"),
    ).json()
    second = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
        json=_text_module_payload(name="Second"),
    ).json()

    first_update = _delegating_module_payload(
        name="First",
        target_graph_id=second["id"],
        target_revision=2,
        expected_revision=1,
    )
    assert (
        module_client.put(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{first['id']}",
            json=first_update,
        ).status_code
        == 200
    )

    second_update = _delegating_module_payload(
        name="Second",
        target_graph_id=first["id"],
        target_revision=2,
        expected_revision=1,
    )
    assert (
        module_client.put(
            f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{second['id']}",
            json=second_update,
        ).status_code
        == 200
    )

    response = module_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_system_run_request(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="source",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "a"},
                ),
                RunNodeRequest(
                    kind="module",
                    id="module",
                    operator_id=f"graph.module.{first['id']}",
                    operator_version=2,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="source",
                    from_port="text",
                    to_node="module",
                    to_port="text",
                )
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "failed"
    error = cast(str, _module_node_run(result)["error"])
    assert "Graph module cycle detected" in error
    assert f"graph.module.{first['id']}@2" in error
    assert f"graph.module.{second['id']}@2" in error


def test_withdrawn_module_stays_executable_for_pinned_calls(
    module_client: TestClient,
) -> None:
    created = module_client.post(
        f"/v1/workspaces/{WORKSPACE}/graphs",
        json=_text_module_payload(),
    ).json()
    graph_id = created["id"]
    api = GrafyApi(module_client)
    modules = api.workspace(UUID(WORKSPACE)).modules
    published = modules.publish_ok(
        PublishModuleReleaseRequest(source_graph_id=UUID(graph_id))
    )
    module_id = published.id

    withdraw = modules.withdraw_ok(module_id)
    assert withdraw.publication_state == "withdrawn"

    catalog = api.workspace(UUID(WORKSPACE)).catalog
    registry = catalog.list_nodes().json()
    assert all(node.get("module_graph_id") != graph_id for node in registry["nodes"])

    response = module_client.post(
        f"/v1/workspaces/{WORKSPACE}/runs",
        json=_system_run_request(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="source",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "a"},
                ),
                RunNodeRequest(
                    kind="module",
                    id="module",
                    operator_id=f"graph.module.{graph_id}",
                    operator_version=1,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="source",
                    from_port="text",
                    to_node="module",
                    to_port="text",
                )
            ],
        ).model_dump(mode="json"),
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "succeeded"
    output = cast(list[dict[str, object]], _module_node_run(result)["outputs"])[0]
    artifacts = cast(list[dict[str, object]], output["artifacts"])
    assert artifacts[0]["text"] == '"A"'


def test_module_library_resolve_definition_is_the_core_contract(
    module_client: TestClient,
) -> None:
    """The canonical resolver resolves and validates a pinned revision and
    raises NotFoundError for a missing one (core contract)."""

    created = module_client.post(
        f"/v1/workspaces/{WORKSPACE}/graphs",
        json=_text_module_payload(),
    ).json()
    graph_id = UUID(created["id"])
    api = GrafyApi(module_client)
    modules = api.workspace(UUID(WORKSPACE)).modules
    modules.publish(PublishModuleReleaseRequest(source_graph_id=graph_id))

    app = cast(FastAPI, module_client.app)
    module_library = app.dependency_overrides[module_library_service]()

    reference = GraphModuleReference(graph_id=graph_id, revision=1)
    definition = asyncio.run(
        module_library.resolve_definition(
            reference,
            workspace_id=UUID(WORKSPACE),
        )
    )
    assert definition.reference.graph_id == graph_id
    assert definition.reference.revision == 1
    assert definition.name == "Capitalize A"
    assert [port.name for port in definition.input_ports] == ["text"]
    assert [port.name for port in definition.output_ports] == ["result"]

    with pytest.raises(NotFoundError):
        asyncio.run(
            module_library.resolve_definition(
                GraphModuleReference(graph_id=graph_id, revision=999),
                workspace_id=UUID(WORKSPACE),
            )
        )


def test_imported_module_is_already_checkpointed(module_client: TestClient) -> None:
    workspace = GrafyApi(module_client).workspace(UUID(WORKSPACE))
    source = workspace.graphs.create_ok(
        CreateSavedGraphRequest.model_validate(_text_module_payload())
    )
    module = workspace.modules.publish_ok(
        PublishModuleReleaseRequest(source_graph_id=source.id)
    )
    api = GrafyApi(module_client)
    destination = api.workspaces.create_ok(
        WorkspaceCreateRequest(slug="module-import-target", name="Import target")
    )
    target = api.workspace(destination.id)
    imported = target.modules.import_release_ok(
        ImportModuleReleaseRequest(
            source_workspace_id=UUID(WORKSPACE),
            source_module_id=module.id,
            name="Imported module",
        )
    )
    head = target.graphs.get_head_ok(imported.graph_id)
    result = target.graphs.checkpoint_ok(
        imported.graph_id,
        CheckpointGraphRequest(
            expected_room_epoch=head.room_epoch,
            expected_sequence=head.collaboration_sequence,
        ),
    )
    assert result.saved_revision == 1
    assert target.graphs.get_ok(imported.graph_id).revision == 1
    assert result.head.collaboration_sequence == head.collaboration_sequence
