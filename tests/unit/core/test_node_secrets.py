"""``context.secrets`` as a node sees it: a name, and whatever was bound to it.

The binding is what these tests are about. A node body never says whose credential
it wants or which configuration that credential belongs to -- the runner bound both
when it built the context -- so two nodes of the same operator holding two keys
each read their own, and a node that asks for a credential it never declared meets
a programming error rather than somebody else's secret.
"""

from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest
from pydantic import Field, SecretStr, StrictStr

from grafy_core.artifacts import NodeConfig
from grafy_core.nodes import (
    NodeExecutionContext,
    NodeSecretRequirementError,
    UserFacingNodeError,
    bind_node_secret_config,
    bind_node_secrets,
)
from grafy_core.plugins import NodeSecretInput
from grafy_core.ports.node_secrets import NodeSecretUnavailableError

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000951")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000952")
GRAPH_ID = "scans"

API_KEY = NodeSecretInput(
    name="api_key",
    title="API key",
    description="Write-only bearer credential.",
    config_dependencies=(),
)

ENDPOINT_API_KEY = NodeSecretInput(
    name="api_key",
    title="API key",
    description="Write-only bearer credential for the configured base URL.",
    config_dependencies=("base_url",),
)

DEFAULT_BASE_URL = "https://api.example.test"


class EndpointConfig(NodeConfig):
    base_url: StrictStr = Field(
        default=DEFAULT_BASE_URL,
        description="Origin the key belongs to.",
    )


class RecordingSecrets:
    """A secret store keyed by exactly where a secret belongs.

    A lookup for a binding it does not hold fails the way ``NodeSecretService``
    fails a graph whose secret was never set and whose deployment sets no default.
    """

    def __init__(self, values: Mapping[tuple[str, str], SecretStr]) -> None:
        self.values = dict(values)
        self.lookups: list[dict[str, object]] = []

    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, object],
        actor_user_id: UUID | None = None,
    ) -> SecretStr:
        self.lookups.append(
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "graph_id": graph_id,
                "node_id": node_id,
                "name": name,
                "dependencies": dict(dependencies),
            }
        )
        secret = self.values.get((str(node_id), name))
        if secret is None:
            raise NodeSecretUnavailableError("Required node secret is not configured")
        return secret

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, object],
    ) -> str:
        del workspace_id, project_id, graph_id, node_id, name, dependencies
        return "revision"


def context_for(
    secrets: RecordingSecrets,
    node_id: str,
    *,
    secret_inputs: tuple[NodeSecretInput, ...] = (API_KEY,),
) -> NodeExecutionContext:
    """One node's context, bound the way ``NodeComputationRunner`` binds it."""

    return bind_node_secrets(
        NodeExecutionContext(
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            graph_id=GRAPH_ID,
            node_id=node_id,
        ),
        secrets,
        secret_inputs,
    )


async def test_two_nodes_of_one_operator_each_read_their_own_key() -> None:
    secrets = RecordingSecrets(
        {
            ("scan-a", "api_key"): SecretStr("key-of-a"),
            ("scan-b", "api_key"): SecretStr("key-of-b"),
        }
    )
    first = context_for(secrets, "scan-a")
    second = context_for(secrets, "scan-b")

    assert await first.secrets.require("api_key") == SecretStr("key-of-a")
    assert await second.secrets.require("api_key") == SecretStr("key-of-b")

    # Each lookup carried its own node's identity, not the other's.
    assert [(lookup["graph_id"], lookup["node_id"]) for lookup in secrets.lookups] == [
        (GRAPH_ID, "scan-a"),
        (GRAPH_ID, "scan-b"),
    ]
    assert {lookup["workspace_id"] for lookup in secrets.lookups} == {WORKSPACE_ID}
    assert {lookup["project_id"] for lookup in secrets.lookups} == {PROJECT_ID}


async def test_a_secret_the_node_never_declared_raises_before_any_lookup() -> None:
    secrets = RecordingSecrets({("scan-a", "api_key"): SecretStr("key-of-a")})
    context = context_for(secrets, "scan-a")

    with pytest.raises(
        NodeSecretRequirementError, match="does not declare secret input 'auth_token'"
    ):
        await context.secrets.require("auth_token")

    assert secrets.lookups == []


async def test_a_context_no_one_bound_secrets_on_refuses_every_name() -> None:
    context = NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id=uuid4().hex)

    with pytest.raises(NodeSecretRequirementError, match="does not declare secret"):
        await context.secrets.require("api_key")


async def test_a_declared_secret_that_was_never_set_is_a_user_facing_failure() -> None:
    secrets = RecordingSecrets({})
    context = context_for(secrets, "scan-a")

    with pytest.raises(
        UserFacingNodeError, match="could not resolve its API key"
    ) as exc:
        await context.secrets.require("api_key")

    # The reason stays with the failure rather than in the message a graph sees.
    assert isinstance(exc.value.__cause__, NodeSecretUnavailableError)
    assert secrets.lookups[0]["name"] == "api_key"


async def test_a_secret_dependency_comes_from_the_validated_config() -> None:
    secrets = RecordingSecrets({("scan-a", "api_key"): SecretStr("key-of-a")})
    context = context_for(secrets, "scan-a", secret_inputs=(ENDPOINT_API_KEY,))

    # The saved document names no base URL, so the node's own contract supplies
    # the one its key was stored against.
    await bind_node_secret_config(context, EndpointConfig()).secrets.require("api_key")
    # A saved document that names another origin moves the dependency with it, and
    # so moves the secret.
    pointed_elsewhere = EndpointConfig.model_validate(
        {"base_url": "https://other.test"}
    )
    await bind_node_secret_config(context, pointed_elsewhere).secrets.require("api_key")

    assert [lookup["dependencies"] for lookup in secrets.lookups] == [
        {"base_url": DEFAULT_BASE_URL},
        {"base_url": "https://other.test"},
    ]


async def test_a_secret_dependency_the_config_cannot_supply_is_refused() -> None:
    secrets = RecordingSecrets({("scan-a", "api_key"): SecretStr("key-of-a")})
    context = context_for(secrets, "scan-a", secret_inputs=(ENDPOINT_API_KEY,))

    with pytest.raises(NodeSecretRequirementError, match="base_url"):
        await context.secrets.require("api_key")

    assert secrets.lookups == []
