"""Publication-side rules for HTTP egress contracts and authority diffs."""

import pytest

from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_releases import (
    PluginCatalogManifest,
    PluginNodeContract,
    PluginNodeHttpEgressContract,
)
from grafy_api.plugins.publication.source import PluginPublishingError
from grafy_api.plugins.publication.workflow import (
    render_plugin_capability_diff,
    require_network_contract,
)


def _node(
    *,
    capabilities: tuple[PluginRuntimeCapability, ...] = (),
    http_egress: PluginNodeHttpEgressContract | None = None,
) -> PluginNodeContract:
    return PluginNodeContract(
        operator_id="llm.chat",
        operator_version=1,
        title="Chat",
        description="Calls a provider.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(),
        outputs=(),
        required_capabilities=capabilities,
        http_egress=http_egress,
    )


def _catalog(*nodes: PluginNodeContract) -> PluginCatalogManifest:
    return PluginCatalogManifest(
        slug="external.llm",
        title="LLM",
        nodes=nodes,
    )


def test_publication_requires_a_contract_for_every_egress_node() -> None:
    require_network_contract(
        _catalog(
            _node(
                capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
                http_egress=PluginNodeHttpEgressContract(
                    configured_inputs=("base_url",)
                ),
            )
        )
    )

    with pytest.raises(
        PluginPublishingError,
        match="without an HTTP egress contract",
    ):
        require_network_contract(
            _catalog(
                _node(capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,))
            )
        )

    require_network_contract(
        _catalog(_node())
    )


def test_capability_diff_reports_added_egress_authority() -> None:
    previous = _catalog(_node())
    proposed = _catalog(
        _node(
            capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
            http_egress=PluginNodeHttpEgressContract(
                configured_inputs=("base_url",)
            ),
        )
    )

    changes = render_plugin_capability_diff(previous, proposed)

    joined = " | ".join(changes)
    assert "now requests network.egress" in joined
    assert "now declares HTTP egress" in joined
    assert "configured URL fields 'base_url'" in joined


def test_capability_diff_reports_removed_and_widened_egress_authority() -> None:
    previous = _catalog(
        _node(
            capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
            http_egress=PluginNodeHttpEgressContract(
                configured_inputs=("base_url",)
            ),
        )
    )
    proposed = _catalog(
        _node(
            capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
            http_egress=PluginNodeHttpEgressContract(
                configured_inputs=("base_url", "fallback_url"),
                dynamic_destinations=True,
            ),
        )
    )

    joined = " | ".join(render_plugin_capability_diff(previous, proposed))
    assert "now declares configured URL field 'fallback_url'" in joined
    assert "now requests dynamic destinations" in joined

    stripped = _catalog(
        _node(capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,))
    )
    joined = " | ".join(render_plugin_capability_diff(previous, stripped))
    assert "no longer declares HTTP egress" in joined


def test_capability_diff_reports_new_nodes_and_removed_nodes() -> None:
    proposed = _catalog(
        _node(
            capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
            http_egress=PluginNodeHttpEgressContract(
                configured_inputs=("base_url",)
            ),
        )
    )

    first_publication = render_plugin_capability_diff(None, proposed)
    assert "new node llm.chat@1 requests capabilities" in " | ".join(
        first_publication
    )

    previous_node = PluginNodeContract(
        operator_id="llm.other",
        operator_version=1,
        title="Other",
        description="Another node.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(),
        outputs=(),
        required_capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
    )
    previous = _catalog(previous_node)
    kept = render_plugin_capability_diff(previous, _catalog(previous_node))
    assert kept == ()

    joined = " | ".join(render_plugin_capability_diff(previous, proposed))
    assert "new node llm.chat@1" in joined
    assert "removed node llm.other@1 previously requested: network.egress" in joined