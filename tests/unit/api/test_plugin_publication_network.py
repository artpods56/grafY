"""Publication-side rules for the HTTP egress contract guard."""

import pytest

from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_releases import (
    PluginCatalogManifest,
    PluginNodeContract,
    PluginNodeHttpEgressContract,
)
from grafy_api.plugins.publication.source import PluginPublishingError
from grafy_api.plugins.publication.workflow import require_network_contract


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
            _catalog(_node(capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,)))
        )

    require_network_contract(_catalog(_node()))
