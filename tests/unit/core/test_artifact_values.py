"""Declarations load and store one Python class per artifact type."""

from typing import cast
from uuid import UUID, uuid4

import pytest
from pydantic import AnyHttpUrl

from grafy_core.artifact_contracts import (
    HTML_PAGE,
    IMAGE_REGIONS,
    INTEGER_VALUE,
    MARKDOWN,
    TEXT_VALUE,
    HtmlPage,
    HtmlPageSource,
    ImagePage,
    ImageRegionSet,
    IntegerValuePayload,
    MarkdownValue,
    TextValuePayload,
)
from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactTypeKey,
    ArtifactTypeSpec,
)
from grafy_core.nodes import NodeExecutionContext
from grafy_core.plugins import Plugin, PluginRegistry
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.prompt_contracts import PROMPT_MESSAGE, PromptMessage, PromptMessageRole
from grafy_core.runtime.artifact_values import (
    ArtifactValues,
    inline_model_artifact,
    scalar_artifact,
)
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_core.runtime.resolvers import ArtifactContractError
from grafy_core.schema_contracts import JSON_SCHEMA
from grafy_core.spatial_contracts import (
    GeoMapDocument,
    GeoMapLayer,
    GeoRasterStyle,
    GeoWmsSource,
)
from grafy_plugin_gis.artifacts import (
    GEO_FEATURE_COLLECTION,
    GEO_MAP_DOCUMENT,
    GEO_MAP_LAYER,
    GEO_RASTER_SCAN,
)
from grafy_plugin_gis.declaration import GIS
from grafy_plugin_image.declaration import IMAGES
from grafy_plugin_llm.artifacts import COMPLETION, CompletionPayload
from grafy_plugin_llm.declaration import LLM
from grafy_workbench.schema import SCHEMAS
from grafy_workbench.schema.values import JsonSchemaText
from grafy_workbench.text import TEXT
from grafy_workbench.value import VALUE

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


class _GuardUnitOfWork:
    async def __aenter__(self) -> "_GuardUnitOfWork":
        raise AssertionError("unit of work entered")

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _context(node_id: str) -> ArtifactWriteContext:
    return ArtifactWriteContext(
        node_context=NodeExecutionContext(
            workspace_id=WORKSPACE_ID,
            node_id=node_id,
        ),
        provenance=MaterializationProvenance(refs_by_input={}),
    )


def test_a_second_declaration_of_the_same_key_raises() -> None:
    with pytest.raises(ValueError, match=r"text\.markdown@1"):
        _ = ArtifactValues(
            (
                inline_model_artifact(MARKDOWN, MarkdownValue),
                inline_model_artifact(MARKDOWN, MarkdownValue),
            ),
            uow=cast(UnitOfWorkPort, _GuardUnitOfWork()),
            storage=cast(FileStoragePort, object()),
            bucket="artifacts",
            storage_backend="local",
        )


def test_one_value_class_cannot_declare_two_artifact_types() -> None:
    other = ArtifactTypeSpec(
        key=ArtifactTypeKey("text.other", 1),
        title="Other",
        payload_schema={"type": "object"},
    )
    with pytest.raises(ValueError, match=r"text\.markdown@1") as raised:
        _ = ArtifactValues(
            (
                inline_model_artifact(MARKDOWN, MarkdownValue),
                inline_model_artifact(other, MarkdownValue),
            ),
            uow=cast(UnitOfWorkPort, _GuardUnitOfWork()),
            storage=cast(FileStoragePort, object()),
            bucket="artifacts",
            storage_backend="local",
        )
    assert "text.other@1" in str(raised.value)


def test_installed_registry_keeps_the_declaration_snapshot() -> None:
    plugin = Plugin(slug="snapshot.declarations", title="Snapshot")
    plugin.register(inline_model_artifact(MARKDOWN, MarkdownValue))
    registry = PluginRegistry()
    registry.install(plugin)
    plugin.register(inline_model_artifact(HTML_PAGE, HtmlPage))

    assert [artifact.spec.key for artifact in registry.artifacts] == [MARKDOWN.key]


@pytest.mark.asyncio
async def test_writing_the_wrong_class_fails_before_the_unit_of_work() -> None:
    values = ArtifactValues(
        (scalar_artifact(TEXT_VALUE, str, TextValuePayload),),
        uow=cast(UnitOfWorkPort, _GuardUnitOfWork()),
        storage=cast(FileStoragePort, object()),
        bucket="artifacts",
        storage_backend="local",
    )

    with pytest.raises(TypeError, match=r"scalar\.text@1") as raised:
        _ = await values.write(
            TEXT_VALUE.key,
            MarkdownValue(markdown="no"),
            _context("text"),
        )

    message = str(raised.value)
    assert "MarkdownValue" in message
    assert "builtins.str" in message


@pytest.mark.asyncio
async def test_missing_inline_payload_is_a_contract_error() -> None:
    uow = InMemoryUnitOfWork()
    values = ArtifactValues(
        TEXT.artifacts,
        uow=uow,
        storage=cast(FileStoragePort, object()),
        bucket="artifacts",
        storage_backend="local",
    )
    ref = await values.write(
        MARKDOWN.key,
        MarkdownValue(markdown="hello"),
        _context("markdown"),
    )
    async with uow as entered:
        artifact = await entered.artifacts.get(WORKSPACE_ID, ref.artifact_id)
        assert artifact is not None
        artifact.inline_payload = None
        await entered.commit()

    with pytest.raises(ArtifactContractError, match="inline JSON payload"):
        _ = await values.resolve(ref, WORKSPACE_ID)


@pytest.mark.asyncio
async def test_inline_and_scalar_declarations_round_trip() -> None:
    registry = PluginRegistry()
    for family in (VALUE, TEXT, SCHEMAS, IMAGES, LLM, GIS):
        registry.install(family)
    registry.freeze()
    assert {artifact.spec.key for artifact in GIS.artifacts} == {
        GEO_MAP_LAYER.key,
        GEO_MAP_DOCUMENT.key,
    }
    assert GEO_FEATURE_COLLECTION.key not in {
        artifact.spec.key for artifact in registry.artifacts
    }
    assert GEO_RASTER_SCAN.key not in {
        artifact.spec.key for artifact in registry.artifacts
    }

    uow = InMemoryUnitOfWork()
    values = ArtifactValues(
        registry.artifacts,
        uow=uow,
        storage=cast(FileStoragePort, object()),
        bucket="artifacts",
        storage_backend="local",
    )
    layer = GeoMapLayer(
        title="Layer",
        source=GeoWmsSource(
            url=AnyHttpUrl("https://example.com/wms"),
            layer="public:layer",
            bounds=(-180.0, -85.0, 180.0, 85.0),
            attribution="Example",
        ),
        style=GeoRasterStyle(),
    )
    samples: tuple[tuple[ArtifactTypeKey, object], ...] = (
        (INTEGER_VALUE.key, -42),
        (TEXT_VALUE.key, "hello"),
        (JSON_SCHEMA.key, JsonSchemaText(value='{"type":"object"}')),
        (MARKDOWN.key, MarkdownValue(markdown="hello")),
        (
            HTML_PAGE.key,
            HtmlPage(
                html="<p>{{baptisms}}</p>",
                sources={
                    "baptisms": HtmlPageSource(
                        artifact_id=UUID("00000000-0000-0000-0000-000000000043"),
                        artifact_type="scalar.text",
                        schema_version=1,
                    )
                },
            ),
        ),
        (
            IMAGE_REGIONS.key,
            ImageRegionSet(
                pages=[ImagePage(index=0, width=8, height=8)],
                regions=[],
            ),
        ),
        (
            PROMPT_MESSAGE.key,
            PromptMessage(role=PromptMessageRole.USER, text="hi"),
        ),
        (
            COMPLETION.key,
            CompletionPayload(
                content="ok",
                model="m",
                base_url="https://example.com",
                message_count=1,
            ),
        ),
        (GEO_MAP_LAYER.key, layer),
        (
            GEO_MAP_DOCUMENT.key,
            GeoMapDocument(
                layers=[
                    ArtifactRef.from_key(artifact_id=uuid4(), key=GEO_MAP_LAYER.key)
                ]
            ),
        ),
    )

    for key, value in samples:
        ref = await values.write(key, value, _context("round-trip"))
        assert await values.resolve(ref, WORKSPACE_ID) == value
        async with uow as entered:
            stored = await entered.artifacts.get(WORKSPACE_ID, ref.artifact_id)
        assert stored is not None
        assert stored.storage_backend == "inline"


def test_scalar_helpers_are_not_the_schema_declaration() -> None:
    text = scalar_artifact(TEXT_VALUE, str, TextValuePayload)
    number = scalar_artifact(INTEGER_VALUE, int, IntegerValuePayload)
    assert text.value_type is str
    assert number.value_type is int
