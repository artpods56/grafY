import tomllib
from io import BytesIO
from pathlib import Path

from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_workbench.arithmetic import ARITHMETIC
from grafy_workbench.image import IMAGES
from grafy_workbench.schema import SCHEMAS
from grafy_workbench.sequence import SEQUENCES
from grafy_workbench.text import TEXT
from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.storage import SaveFileCommand, StoredFile, StoredObjectInfo
from grafy_core.runtime.persistence import InlineModelOutputWriter
from grafy_core.runtime.resolvers import InlineModelResolver
from grafy_plugin_llm import LLM
from grafy_plugin_llm.artifacts import COMPLETION, CompletionPayload
from grafy_plugin_llm.openai_compatible import OpenAICompatibleNode


class EmptyStorage:
    async def save(self, command: SaveFileCommand) -> StoredFile:
        raise AssertionError(f"Unexpected save to {command.bucket}/{command.path}")

    async def move(
        self,
        bucket: str,
        source_path: str,
        destination_path: str,
    ) -> None:
        raise AssertionError(
            f"Unexpected move in {bucket}: {source_path} to {destination_path}"
        )

    async def load(self, bucket: str, path: str) -> BytesIO:
        raise AssertionError(f"Unexpected load from {bucket}/{path}")

    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        raise AssertionError(f"Unexpected stat for {bucket}/{path}")

    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes:
        raise AssertionError(
            f"Unexpected range load from {bucket}/{path}: {start}:{end_exclusive}"
        )

    async def delete(self, bucket: str, path: str) -> None:
        raise AssertionError(f"Unexpected delete from {bucket}/{path}")


def test_llm_plugin_declares_complete_runtime_contributions(tmp_path: Path) -> None:
    registry = PluginRegistry()
    for builtin in (IMAGES, SEQUENCES, ARITHMETIC, TEXT, SCHEMAS):
        registry.install(builtin)
    registry.install(LLM)
    context = PluginRuntimeContext(
        workspace=tmp_path,
        uploads_dir=tmp_path / "uploads",
        storage=EmptyStorage(),
        uow=InMemoryUnitOfWork(),
        bucket="artifacts",
    )

    assert LLM.slug == "external.llm"
    assert LLM.title == "LLM"
    registry.freeze()

    llm_plugin = next(plugin for plugin in registry.plugins if plugin.slug == LLM.slug)
    assert llm_plugin.title == "LLM"
    completion = next(
        artifact_type
        for artifact_type in registry.artifact_types
        if artifact_type.key == COMPLETION.key
    )
    content_projection = next(
        projection
        for projection in completion.field_projections
        if projection.path == ("content",)
    )
    assert content_projection.target == TEXT_VALUE.key
    assert isinstance(
        registry.build_node("llm.openai_compatible.chat_completion", 1, context),
        OpenAICompatibleNode,
    )
    assert "prompt.message.create" in {
        registration.node_class.operator_id for registration in LLM.nodes
    }

    resolvers = registry.build_resolvers(context)
    writers = registry.build_writers(context)

    llm_resolver = next(
        resolver for resolver in resolvers if resolver.source == COMPLETION.key
    )
    llm_writer = next(
        writer for writer in writers if writer.artifact_type == COMPLETION.key
    )
    assert isinstance(llm_resolver, InlineModelResolver)
    assert llm_resolver.target is CompletionPayload
    assert isinstance(llm_writer, InlineModelOutputWriter)


def test_llm_package_metadata_has_no_ambient_plugin_entry_point() -> None:
    project_root = Path(__file__).parents[3]
    metadata = tomllib.loads(
        (project_root / "plugins" / "llm" / "pyproject.toml").read_text()
    )

    assert metadata["project"]["name"] == "grafy-plugin-llm"
    assert "entry-points" not in metadata["project"]
