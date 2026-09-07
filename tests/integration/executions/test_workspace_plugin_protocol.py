import subprocess
import sys
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    JsonObject,
    NodeInput,
    NodeOutput,
)
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.domain.plugin_releases import (
    PluginExecutionPolicy,
    PluginRelease,
    PluginReleaseNamespace,
    PluginReleaseScope,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.nodes import NodeExecutionContext
from grafy_core.table_contracts import (
    Table,
    TableColumn,
    TableValueType,
)
from grafy_workbench.table.persistence import TableArtifactWriter
from grafy_core.plugin_inspector import InspectionResult
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_core.runtime.plugin_invocation import (
    PluginInvocationError,
    PluginReleaseNodeConfig,
    PluginReleaseNode,
)
from grafy_storage import LocalFileObjectStore

from grafy_api.plugins.runtime.artifacts import (
    ArtifactBundlePluginInvoker,
    SubprocessPluginGuestRunner,
)


WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000451")


def _plugin_python_path(
    project_root: Path,
    plugin_source: Path | None = None,
) -> str:
    return ":".join(
        [
            str(
                plugin_source
                if plugin_source is not None
                else project_root / "examples" / "plugin-notes" / "src"
            ),
            str(project_root / "libs" / "core" / "src"),
        ]
    )


def _inspect_plugin(
    project_root: Path,
    plugin_source: Path | None = None,
) -> InspectionResult:
    completed = subprocess.run(
        [sys.executable, "-m", "grafy_core.plugin_inspector"],
        check=True,
        capture_output=True,
        env={
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": _plugin_python_path(project_root, plugin_source),
            "PYTHONUTF8": "1",
        },
    )
    return InspectionResult.model_validate_json(completed.stdout)


def _release(
    inspection: InspectionResult,
    *,
    slug: str = "notes",
) -> InstalledPluginRelease:
    release = PluginRelease(
        slug=slug,
        revision=1,
        catalog=inspection.catalog,
        contract_digest=plugin_contract_digest(inspection.catalog),
        capabilities=inspection.capabilities,
        capability_digest=inspection.capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key="plugin-releases/notes/example.tar.gz",
        source_digest="a" * 64,
        lock_digest="b" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
        published_by_user_id=WORKSPACE_ID,
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.WORKSPACE,
                workspace_id=WORKSPACE_ID,
            ),
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            installed_by_user_id=WORKSPACE_ID,
            installed_by_platform_actor=None,
        ),
    )


def _write_empty_sequence_plugin(plugin_source: Path) -> None:
    package = plugin_source / "grafy_plugin"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        """from typing import Annotated

from grafy_core.artifact_contracts import TEXT_VALUE, TextValue
from grafy_core.artifacts import NoConfig, NodeInput, NodeOutput
from grafy_core.nodes import OutPort
from grafy_core.plugins import Plugin


PLUGIN = Plugin(slug="empty-sequence", title="Empty sequence")
PLUGIN.register_artifact_type_dependency(TEXT_VALUE)


class EmptySequenceInput(NodeInput):
    pass


class EmptySequenceOutput(NodeOutput):
    texts: Annotated[list[TextValue], OutPort(TEXT_VALUE)]


@PLUGIN.function_node(
    operator_id="empty-sequence.produce",
    version=1,
    title="Produce empty sequence",
)
async def produce_empty_sequence(
    _config: NoConfig,
    _inputs: EmptySequenceInput,
) -> EmptySequenceOutput:
    return EmptySequenceOutput(texts=[])


@PLUGIN.function_node(
    operator_id="empty-sequence.produce-one",
    version=1,
    title="Produce one-item sequence",
)
async def produce_one_item_sequence(
    _config: NoConfig,
    _inputs: EmptySequenceInput,
) -> EmptySequenceOutput:
    return EmptySequenceOutput(texts=[TextValue(value="only item")])
""",
        encoding="utf-8",
    )


async def _seed_summary(unit_of_work: InMemoryUnitOfWork) -> ArtifactObject:
    payload: JsonObject = {
        "row_count": 2,
        "column_count": 2,
        "column_ids": ["name", "amount"],
    }
    content = b'{"column_count":2,"column_ids":["name","amount"],"row_count":2}'
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="notes.table_summary",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload=payload,
        byte_size=len(content),
        sha256=sha256(content).hexdigest(),
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    return artifact


@pytest.mark.asyncio
async def test_example_plugin_executes_inline_artifacts_through_local_guest(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[3]
    inspection = _inspect_plugin(project_root)
    render_contract = next(
        contract
        for contract in inspection.catalog.nodes
        if contract.operator_id == "notes.summary.render"
    )
    release = _release(inspection)
    unit_of_work = InMemoryUnitOfWork()
    artifact = await _seed_summary(unit_of_work)

    runner = SubprocessPluginGuestRunner(
        (sys.executable, "-m", "grafy_core.runtime.plugin_guest"),
        environment={"PYTHONPATH": _plugin_python_path(project_root)},
    )
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=runner,
        scratch_root=tmp_path,
    )
    node: PluginReleaseNode[
        PluginReleaseNodeConfig,
        NodeInput,
        NodeOutput,
    ] = PluginReleaseNode(release, render_contract, invoker)
    inputs = node.input_contract.model.model_validate({"summary": artifact.ref()})
    config = node.config_contract.model.model_validate({})

    output = await node.run(
        NodeExecutionContext(
            workspace_id=WORKSPACE_ID,
            node_id="render",
            invocation_index=0,
        ),
        config,
        inputs,
    )

    output_values = cast(Mapping[str, object], output.__dict__)
    output_ref = output_values["text"]
    assert isinstance(output_ref, ArtifactRef)
    assert output_ref.artifact_id != artifact.id
    async with unit_of_work as entered:
        persisted = await entered.artifacts.get(
            WORKSPACE_ID,
            output_ref.artifact_id,
        )
    assert persisted is not None
    assert persisted.inline_payload == {"value": "2 rows, 2 columns: name, amount"}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operator_id", "expected_values"),
    [
        ("empty-sequence.produce", []),
        ("empty-sequence.produce-one", ["only item"]),
    ],
)
async def test_workspace_plugin_returns_many_output_through_local_guest(
    tmp_path: Path,
    operator_id: str,
    expected_values: list[str],
) -> None:
    project_root = Path(__file__).resolve().parents[3]
    plugin_source = tmp_path / "plugin-src"
    _write_empty_sequence_plugin(plugin_source)
    inspection = _inspect_plugin(project_root, plugin_source)
    contract = next(
        node for node in inspection.catalog.nodes if node.operator_id == operator_id
    )
    release = _release(inspection, slug="empty-sequence")
    unit_of_work = InMemoryUnitOfWork()
    scratch_root = tmp_path / "scratch"
    runner = SubprocessPluginGuestRunner(
        (sys.executable, "-m", "grafy_core.runtime.plugin_guest"),
        environment={
            "PYTHONPATH": _plugin_python_path(project_root, plugin_source),
        },
    )
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=runner,
        scratch_root=scratch_root,
    )
    node: PluginReleaseNode[
        PluginReleaseNodeConfig,
        NodeInput,
        NodeOutput,
    ] = PluginReleaseNode(release, contract, invoker)

    output = await node.run(
        NodeExecutionContext(
            workspace_id=WORKSPACE_ID,
            node_id=operator_id,
            invocation_index=0,
        ),
        node.config_contract.model.model_validate({}),
        node.input_contract.model.model_validate({}),
    )

    output_ref = cast(Mapping[str, object], output.__dict__)["texts"]
    assert isinstance(output_ref, ArtifactRefSequence)
    assert output_ref.artifact_type == "scalar.text"
    assert output_ref.schema_version == 1
    assert len(output_ref.item_refs) == len(expected_values)
    assert isinstance(output_ref.sequence_id, UUID)
    assert all(
        ref.key() == ArtifactTypeKey("scalar.text", 1) for ref in output_ref.item_refs
    )
    async with unit_of_work as entered:
        artifacts = await entered.artifacts.list_by_type(
            WORKSPACE_ID,
            ArtifactTypeKey("scalar.text", 1),
        )
    assert [artifact.inline_payload for artifact in artifacts] == [
        {"value": value} for value in expected_values
    ]
    assert list(scratch_root.iterdir()) == []


@pytest.mark.asyncio
async def test_example_plugin_summarizes_a_stored_table_then_renders_it(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[3]
    inspection = _inspect_plugin(project_root)
    release = _release(inspection)
    summarize_contract = next(
        contract
        for contract in inspection.catalog.nodes
        if contract.operator_id == "notes.table.summarize"
    )
    render_contract = next(
        contract
        for contract in inspection.catalog.nodes
        if contract.operator_id == "notes.summary.render"
    )
    unit_of_work = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    table = Table(
        columns=[
            TableColumn(
                id="name",
                title="Name",
                value_type=TableValueType.TEXT,
            ),
            TableColumn(
                id="amount",
                title="Amount",
                value_type=TableValueType.INTEGER,
            ),
        ],
        rows=[{"name": f"sample-{index}", "amount": index} for index in range(205)],
    )
    table_ref = await TableArtifactWriter(
        storage=storage,
        uow=unit_of_work,
        bucket="artifacts",
        storage_backend="local",
    ).write(
        table,
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="table-source",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=SubprocessPluginGuestRunner(
            (sys.executable, "-m", "grafy_core.runtime.plugin_guest"),
            environment={"PYTHONPATH": _plugin_python_path(project_root)},
        ),
        scratch_root=tmp_path / "scratch",
        storage=storage,
        bucket="artifacts",
        storage_backend="local",
    )
    summarize_node: PluginReleaseNode[
        PluginReleaseNodeConfig,
        NodeInput,
        NodeOutput,
    ] = PluginReleaseNode(release, summarize_contract, invoker)
    render_node: PluginReleaseNode[
        PluginReleaseNodeConfig,
        NodeInput,
        NodeOutput,
    ] = PluginReleaseNode(release, render_contract, invoker)

    summarized = await summarize_node.run(
        NodeExecutionContext(
            workspace_id=WORKSPACE_ID,
            node_id="summarize",
        ),
        summarize_node.config_contract.model.model_validate({}),
        summarize_node.input_contract.model.model_validate({"table": table_ref}),
    )
    summary_ref = cast(Mapping[str, object], summarized.__dict__)["summary"]
    assert isinstance(summary_ref, ArtifactRef)
    rendered = await render_node.run(
        NodeExecutionContext(
            workspace_id=WORKSPACE_ID,
            node_id="render",
        ),
        render_node.config_contract.model.model_validate({}),
        render_node.input_contract.model.model_validate({"summary": summary_ref}),
    )
    text_ref = cast(Mapping[str, object], rendered.__dict__)["text"]
    assert isinstance(text_ref, ArtifactRef)

    async with unit_of_work as entered:
        summary = await entered.artifacts.get(WORKSPACE_ID, summary_ref.artifact_id)
        text = await entered.artifacts.get(WORKSPACE_ID, text_ref.artifact_id)
    assert summary is not None
    assert summary.inline_payload == {
        "row_count": 205,
        "column_count": 2,
        "column_ids": ["name", "amount"],
    }
    assert text is not None
    assert text.inline_payload == {"value": "205 rows, 2 columns: name, amount"}
    assert list((tmp_path / "scratch").iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["tamper", "undeclared"])
async def test_guest_rejects_tampered_or_undeclared_input_files(
    tmp_path: Path,
    mutation: str,
) -> None:
    project_root = Path(__file__).resolve().parents[3]
    inspection = _inspect_plugin(project_root)
    release = _release(inspection)
    render_contract = next(
        contract
        for contract in inspection.catalog.nodes
        if contract.operator_id == "notes.summary.render"
    )
    unit_of_work = InMemoryUnitOfWork()
    artifact = await _seed_summary(unit_of_work)
    if mutation == "tamper":
        mutate = (
            "path = next((root / 'inputs').rglob('*.json')); "
            "path.chmod(0o600); path.write_text('{}')"
        )
    else:
        mutate = "(root / 'inputs' / 'undeclared.json').write_text('{}')"
    command = (
        "import asyncio, sys; from pathlib import Path; "
        "from grafy_core.runtime.plugin_guest import execute_plugin_invocation; "
        "root = Path(sys.argv[1]); "
        f"{mutate}; "
        "asyncio.run(execute_plugin_invocation("
        "root, system_loader_manifest_path=Path(sys.argv[2])))"
    )
    runner = SubprocessPluginGuestRunner(
        (sys.executable, "-c", command),
        environment={"PYTHONPATH": _plugin_python_path(project_root)},
    )
    invoker = ArtifactBundlePluginInvoker(
        unit_of_work=unit_of_work,
        runner=runner,
        scratch_root=tmp_path,
    )
    node: PluginReleaseNode[
        PluginReleaseNodeConfig,
        NodeInput,
        NodeOutput,
    ] = PluginReleaseNode(release, render_contract, invoker)
    inputs = node.input_contract.model.model_validate({"summary": artifact.ref()})
    config = node.config_contract.model.model_validate({})

    with pytest.raises(PluginInvocationError, match="materialization_failure"):
        await node.run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="render"),
            config,
            inputs,
        )

    async with unit_of_work as entered:
        outputs = await entered.artifacts.list_by_type(
            WORKSPACE_ID,
            ArtifactTypeKey("scalar.text", 1),
        )
    assert outputs == []
    assert list(tmp_path.iterdir()) == []
