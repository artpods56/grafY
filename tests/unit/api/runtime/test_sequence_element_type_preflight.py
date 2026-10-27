"""Sequence element mismatches fail before registered provider execution (#84)."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from grafy_api.execution.compiler import GraphCompiler
from grafy_api.execution.errors import ArtifactTypeMismatchError
from grafy_api.execution.requests import RunRequest
from grafy_api.services.composition import build_workbench_components
from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey, ArtifactTypeSpec
from grafy_core.canonical_conversions import CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY
from grafy_core.plugins import Plugin, PluginRuntimeContext
from grafy_core.prompt_contracts import PROMPT_MESSAGE
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.invocation import InvocationMode
from grafy_plugin_llm.plugin import LLM
from grafy_storage import LocalFileObjectStore
from tests.support.system_plugins import (
    TEST_SYSTEM_PLUGINS,
    build_explicit_plugin_registry,
)

WORKSPACE_ID = UUID(int=884)
LEGACY_MESSAGES = Plugin(slug="test.prompt-v1", title="Historical prompt contract")
LEGACY_MESSAGES.register_artifact_type(
    ArtifactTypeSpec(
        key=ArtifactTypeKey("prompt.message", 1),
        title="Prompt message v1",
        bundle=PROMPT_MESSAGE.bundle,
    )
)


def _request(element: ArtifactTypeKey) -> RunRequest:
    return RunRequest.model_validate(
        {
            "nodes": [
                {
                    "id": "collect",
                    "kind": "builtin",
                    "operator_id": "test.sequence.collect",
                    "operator_version": 1,
                    "input_plugs": [{"id": "item", "port": "items"}],
                    "artifact_type_bindings": [
                        {
                            "variable": "T",
                            "artifact_type": {
                                "id": element.id,
                                "schema_version": element.schema_version,
                            },
                        }
                    ],
                },
                {
                    "id": "chat",
                    "kind": "builtin",
                    "operator_id": "llm.openai_compatible.chat_completion",
                    "operator_version": 1,
                    "config": {"model": "test-model"},
                },
            ],
            "edges": [
                {
                    "from_node": "collect",
                    "from_port": "items",
                    "to_node": "chat",
                    "to_port": "messages",
                }
            ],
            "origins": [
                {
                    "to_node": "collect",
                    "to_port": "items",
                    "to_plug": "item",
                    "value": ArtifactRef.from_key(
                        artifact_id=uuid4(), key=element
                    ).model_dump(),
                }
            ],
        }
    )


@pytest.mark.parametrize(
    "element", [ArtifactTypeKey("scalar.text", 1), ArtifactTypeKey("prompt.message", 1)]
)
async def test_compile_rejects_mismatched_sequence_element_before_provider_execution(
    tmp_path: Path,
    element: ArtifactTypeKey,
) -> None:
    registry = build_explicit_plugin_registry(
        (*TEST_SYSTEM_PLUGINS, LLM, LEGACY_MESSAGES)
    )
    components = build_workbench_components(
        plugin_registry=registry, workspace=tmp_path
    )
    compiler = GraphCompiler(
        plugin_registry=registry,
        plugin_context=PluginRuntimeContext(
            workspace=tmp_path,
            storage=LocalFileObjectStore(tmp_path / "objects"),
            uow=InMemoryUnitOfWork(),
            bucket="artifacts",
        ),
        module_library=None,
        canonical_artifact_conversions=CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY,
        build_digest="a" * 64,
    )
    try:
        with pytest.raises(ArtifactTypeMismatchError) as mismatch:
            await compiler.compile(
                _request(element), components.run_graph, workspace_id=WORKSPACE_ID
            )
        assert mismatch.value.node_id == "chat"
        assert mismatch.value.port == "messages"
        assert mismatch.value.expected == (ArtifactTypeKey("prompt.message", 2),)
        assert mismatch.value.received == element
        assert "prompt.message@2" in str(mismatch.value)
        assert f"{element.id}@{element.schema_version}" in str(mismatch.value)
    finally:
        await components.artifacts.close()


async def test_compile_accepts_matching_sequence_for_registered_provider(
    tmp_path: Path,
) -> None:
    registry = build_explicit_plugin_registry((*TEST_SYSTEM_PLUGINS, LLM))
    components = build_workbench_components(
        plugin_registry=registry, workspace=tmp_path
    )
    compiler = GraphCompiler(
        plugin_registry=registry,
        plugin_context=PluginRuntimeContext(
            workspace=tmp_path,
            storage=LocalFileObjectStore(tmp_path / "objects"),
            uow=InMemoryUnitOfWork(),
            bucket="artifacts",
        ),
        module_library=None,
        canonical_artifact_conversions=CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY,
        build_digest="a" * 64,
    )
    try:
        plan = await compiler.compile(
            _request(ArtifactTypeKey("prompt.message", 2)),
            components.run_graph,
            workspace_id=WORKSPACE_ID,
        )
        assert [node.request.id for node in plan.nodes] == ["collect", "chat"]
        assert plan.nodes[1].invocation.mode is InvocationMode.ONCE
        assert plan.nodes[1].registration is not None
        assert plan.nodes[1].registration.plugin_slug == "external.llm"
    finally:
        await components.artifacts.close()
