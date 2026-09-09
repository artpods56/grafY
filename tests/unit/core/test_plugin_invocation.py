"""Behavioral contracts for the release-pinned Plugin proxy node."""

from dataclasses import dataclass, field
from typing import cast
from uuid import UUID, uuid4

import pytest

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.plugin_releases import (
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginNodeContract,
    PluginPortContract,
    PluginPortDirection,
    PluginRelease,
    PluginReleaseIdentity,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginExecutionPolicy,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.nodes import (
    NodeExecutionContext,
    PortShape,
)
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.plugin_invocation import (
    PluginInvocationError,
    PluginInvocationRequest,
    PluginInvocationResult,
    PluginReleaseNodeConfig,
    PluginReleaseNode,
    PluginReleaseNodeError,
)
from grafy_core.runtime.resolvers import ResolverRegistry


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000861")
TEXT = ArtifactTypeKey("scalar.text", 1)

ProxyNode = PluginReleaseNode[PluginReleaseNodeConfig, NodeInput, NodeOutput]


def _port(
    name: str,
    direction: PluginPortDirection,
    *,
    shape: PortShape = PortShape.ONE,
    required: bool = True,
) -> PluginPortContract:
    return PluginPortContract(
        name=name,
        title=name.title(),
        direction=direction,
        artifact_type=PluginArtifactTypeKey.from_key(TEXT),
        shape=shape,
        accepted_shapes=(shape,),
        required=required,
    )


def _echo_contract() -> PluginNodeContract:
    return PluginNodeContract(
        operator_id="notes.echo",
        operator_version=1,
        title="Echo",
        description="Echoes one text reference.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(_port("text", "input"),),
        outputs=(_port("text", "output"),),
    )


def _manifest(nodes: tuple[PluginNodeContract, ...]) -> PluginCatalogManifest:
    return PluginCatalogManifest(
        slug="notes",
        title="Notes",
        artifact_type_dependencies=(PluginArtifactTypeContract.from_spec(TEXT_VALUE),),
        nodes=nodes,
    )


def _release_from_serialized_contract(
    manifest: PluginCatalogManifest,
    *,
    revision: int,
    workspace_id: UUID = WORKSPACE_ID,
) -> InstalledPluginRelease:
    """Rebuild the release contract from JSON only, as the host would."""
    serialized = manifest.model_dump_json()
    rebuilt = PluginCatalogManifest.model_validate_json(serialized)
    capabilities = PluginCapabilityManifest()
    release = PluginRelease(
        slug=rebuilt.slug,
        revision=revision,
        catalog=rebuilt,
        contract_digest=plugin_contract_digest(rebuilt),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/notes/r{revision}.tar.gz",
        source_digest=f"{revision}" * 64,
        lock_digest="9" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
        published_by_user_id=workspace_id,
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.WORKSPACE,
                workspace_id=workspace_id,
            ),
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            installed_by_user_id=workspace_id,
            installed_by_platform_actor=None,
        ),
    )


@dataclass
class RecordingInvoker:
    outputs: dict[str, ArtifactRef | ArtifactRefSequence] = field(default_factory=dict)
    error: Exception | None = None
    requests: list[PluginInvocationRequest] = field(default_factory=list)

    async def invoke(
        self,
        request: PluginInvocationRequest,
        /,
    ) -> PluginInvocationResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return PluginInvocationResult(outputs=dict(self.outputs))


def _ref(content_hash: str = "a" * 64) -> ArtifactRef:
    return ArtifactRef.from_key(
        artifact_id=uuid4(), key=TEXT, content_hash=content_hash
    )


def _proxy(
    release: InstalledPluginRelease | None = None,
    invoker: RecordingInvoker | None = None,
) -> tuple[ProxyNode, RecordingInvoker]:
    resolved_release = release or _release_from_serialized_contract(
        _manifest((_echo_contract(),)),
        revision=4,
    )
    recording_invoker = invoker or RecordingInvoker()
    node: ProxyNode = PluginReleaseNode(
        resolved_release,
        resolved_release.release.catalog.nodes[0],
        recording_invoker,
    )
    return node, recording_invoker


def _context() -> NodeExecutionContext:
    return NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="echo-1")


def _run_inputs(node: ProxyNode, **values: object) -> NodeInput:
    return node.input_contract.model.model_validate(values)


@pytest.mark.asyncio
async def test_proxy_run_passes_authorized_refs_to_the_invoker_and_back() -> None:
    incoming = _ref()
    outgoing = _ref("b" * 64)
    invoker = RecordingInvoker(outputs={"text": outgoing})
    node, invoker = _proxy(invoker=invoker)
    context = _context()

    result = await node.run(
        context,
        PluginReleaseNodeConfig(),
        _run_inputs(node, text=incoming),
    )

    assert len(invoker.requests) == 1
    request = invoker.requests[0]
    assert request.inputs["text"] is incoming
    assert request.release == PluginReleaseIdentity.from_release(node.release)
    assert request.contract.operator_id == "notes.echo"
    assert request.workspace_id == WORKSPACE_ID
    assert request.progress_context is context
    output_values = cast(dict[str, object], result.model_dump())
    assert output_values["text"] == cast(object, outgoing.model_dump())


@pytest.mark.asyncio
async def test_proxy_preserves_sequence_containers_for_many_ports() -> None:
    item_a = _ref("1" * 64)
    item_b = _ref("2" * 64)
    sequence = ArtifactRefSequence.from_key(key=TEXT, item_refs=[item_a, item_b])

    contract = PluginNodeContract(
        operator_id="notes.join",
        operator_version=1,
        title="Join",
        description="Joins a sequence of texts.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(_port("texts", "input", shape=PortShape.MANY),),
        outputs=(_port("texts", "output", shape=PortShape.MANY),),
    )
    release = _release_from_serialized_contract(_manifest((contract,)), revision=1)
    invoker = RecordingInvoker(outputs={"texts": sequence})
    node: ProxyNode = PluginReleaseNode(release, contract, invoker)

    await node.run(
        _context(),
        PluginReleaseNodeConfig(),
        _run_inputs(node, texts=sequence),
    )

    assert invoker.requests[0].inputs["texts"] is sequence


@pytest.mark.asyncio
async def test_proxy_rejects_non_ref_input_containers() -> None:
    node, _ = _proxy()

    with pytest.raises(
        PluginReleaseNodeError,
        match="expected an ArtifactRef",
    ):
        await node.run(
            _context(),
            PluginReleaseNodeConfig(),
            node.input_contract.model.model_construct(
                text="materialized python string",
            ),
        )


@pytest.mark.asyncio
async def test_proxy_wraps_invoker_failures() -> None:
    invoker = RecordingInvoker(error=RuntimeError("sandbox exploded"))
    node, _ = _proxy(invoker=invoker)

    with pytest.raises(PluginInvocationError, match="sandbox exploded"):
        await node.run(
            _context(),
            PluginReleaseNodeConfig(),
            _run_inputs(node, text=_ref()),
        )


@pytest.mark.asyncio
async def test_proxy_validates_host_minted_outputs_against_the_contract() -> None:
    wrong_type = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=ArtifactTypeKey("scalar.integer", 1),
    )
    node, _ = _proxy(invoker=RecordingInvoker(outputs={"text": wrong_type}))

    with pytest.raises(
        PluginReleaseNodeError,
        match="expected scalar.text@1",
    ):
        await node.run(
            _context(),
            PluginReleaseNodeConfig(),
            _run_inputs(node, text=_ref()),
        )

    unexpected_release = _release_from_serialized_contract(
        _manifest((_echo_contract(),)),
        revision=4,
    )
    extra_invoker = RecordingInvoker(
        outputs={"text": _ref(), "surprise": _ref()},
    )
    node_extra: ProxyNode = PluginReleaseNode(
        unexpected_release,
        unexpected_release.release.catalog.nodes[0],
        extra_invoker,
    )
    with pytest.raises(
        PluginReleaseNodeError,
        match="unexpected outputs",
    ):
        await node_extra.run(
            _context(),
            PluginReleaseNodeConfig(),
            _run_inputs(node_extra, text=_ref()),
        )

    missing_invoker = RecordingInvoker(outputs={})
    node_missing, _ = _proxy(invoker=missing_invoker)
    with pytest.raises(
        PluginReleaseNodeError,
        match="no output for required port",
    ):
        await node_missing.run(
            _context(),
            PluginReleaseNodeConfig(),
            _run_inputs(node_missing, text=_ref()),
        )


def test_proxy_requires_the_contract_to_match_the_pinned_catalog() -> None:
    release = _release_from_serialized_contract(
        _manifest((_echo_contract(),)),
        revision=4,
    )
    other = PluginNodeContract(
        operator_id="notes.echo",
        operator_version=2,
        title="Echo v2",
        description="A different operator version.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(_port("text", "input"),),
        outputs=(_port("text", "output"),),
    )

    with pytest.raises(
        PluginReleaseNodeError,
        match="does not match the serialized catalog",
    ):
        PluginReleaseNode(release, other, RecordingInvoker())


@pytest.mark.asyncio
async def test_derived_input_contract_keeps_refs_unmaterialized() -> None:
    """InputMaterializer must not resolve Plugin ports to Python values."""

    release = _release_from_serialized_contract(
        _manifest((_echo_contract(),)),
        revision=4,
    )
    node, _ = _proxy(release=release)

    ref = _ref()
    values, provenance = await InputMaterializer(ResolverRegistry()).materialize(
        node.input_contract,
        {"text": ref},
        WORKSPACE_ID,
    )

    input_values = cast(dict[str, object], values.model_dump())
    assert input_values["text"] == cast(object, ref.model_dump())
    assert provenance.refs_for("text") == (ref,)
