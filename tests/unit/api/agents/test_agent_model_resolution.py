"""Model resolution for the two choices an Agent can carry (ADR 0021, issue #202).

Nothing here opens a connection: the resolver's job ends at naming the endpoint, the
model, the key, and the transport rule that reaches them. The egress half is checked where
it can be checked without a network — a name that resolves to a private address is refused
unless the operator granted that destination, whichever of the two choices named it.
"""

from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from grafy_api.agents.keys import AgentKeyState, AgentKeyUnavailableError
from grafy_api.agents.models import (
    AgentModelConfigurationError,
    AgentModelResolver,
    ResolvedAgentModel,
)
from grafy_core import egress as egress_module
from grafy_core.domain.graph_documents import (
    CustomAgentModel,
    DeploymentAgentModel,
    GraphAgent,
)
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceAccess,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_core.egress import EgressPolicy
from grafy_shared.config import AgentsConfig

WORKSPACE = UUID(int=601)
PROJECT = UUID(int=602)
AUTHOR = UUID(int=603)
GRAPH_ID = "main"
AGENT_ID = "research"
DEPLOYMENT_KEY = "deployment-agent-key-value"
AGENT_KEY = "the-agent-owns-this-key"
CUSTOM = CustomAgentModel(endpoint="https://models.example/v1", model="gpt-5-mini")


def deployment_config(**overrides: object) -> AgentsConfig:
    values: dict[str, object] = {
        "_env_file": None,
        "agent_default_base_url": "https://models.internal:11434/v1",
        "agent_default_model": "llama-4",
        "agent_default_api_key": SecretStr(DEPLOYMENT_KEY),
    }
    values.update(overrides)
    return AgentsConfig(**values)  # pyright: ignore[reportCallIssue]


def viewer_access() -> WorkspaceAccess:
    return WorkspaceAccess(
        actor=ActorContext(user_id=AUTHOR),
        workspace_id=WORKSPACE,
        membership=WorkspaceMembership(
            workspace_id=WORKSPACE, user_id=AUTHOR, role=WorkspaceRole.VIEWER
        ),
    )


def agent(model: object = DeploymentAgentModel()) -> GraphAgent:
    return GraphAgent(id=AGENT_ID, name="Research", model=model)  # type: ignore[arg-type]


class StubKeyService:
    """The one part of the key owner the resolver talks to."""

    def __init__(self, key: SecretStr | None = SecretStr(AGENT_KEY)) -> None:
        self._key = key
        self.resolve_calls: list[tuple[str, str, str]] = []

    async def resolve_key(
        self, *, workspace_id: UUID, project_id: UUID, graph_id: str, agent_id: str
    ) -> SecretStr:
        self.resolve_calls.append((str(project_id), graph_id, agent_id))
        if self._key is None:
            raise AgentKeyUnavailableError(f"Agent {agent_id} has no configured model key")
        return self._key

    async def state(
        self,
        *,
        access: WorkspaceAccess,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> AgentKeyState:
        return AgentKeyState(agent_id=agent_id, configured=self._key is not None)


async def test_the_deployment_default_is_the_answer_an_agent_gets_when_it_asks_for_none() -> None:
    keys = StubKeyService()
    resolver = AgentModelResolver(
        settings=deployment_config(),
        keys=keys,
        egress_policy=EgressPolicy.from_destinations(["models.internal:11434"]),
    )

    resolved = await resolver.resolve(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent=agent(),
    )

    assert resolved.source == "deployment"
    assert resolved.model_name == "llama-4"
    assert resolved.base_url == "https://models.internal:11434/v1"
    assert resolved.api_key.get_secret_value() == DEPLOYMENT_KEY
    # The deployment's own credential is never looked up as an Agent secret.
    assert keys.resolve_calls == []
    assert DEPLOYMENT_KEY not in repr(resolved)


async def test_an_agent_that_chose_its_own_endpoint_spends_its_own_key() -> None:
    keys = StubKeyService()
    resolver = AgentModelResolver(settings=deployment_config(), keys=keys)

    resolved = await resolver.resolve(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent=agent(CUSTOM),
    )

    assert resolved.source == "agent"
    assert resolved.model_name == "gpt-5-mini"
    assert resolved.base_url == "https://models.example/v1"
    assert resolved.api_key.get_secret_value() == AGENT_KEY
    assert keys.resolve_calls == [(str(PROJECT), GRAPH_ID, AGENT_ID)]
    assert AGENT_KEY not in repr(resolved)


async def test_an_agent_on_its_own_endpoint_without_a_key_cannot_be_run() -> None:
    """The failure names the missing thing and does not offer the deployment's key instead.

    Falling back to the deployment credential would send this historian's prompt to an
    endpoint the deployment never agreed to, under a key whose owner the prompt has no
    business reaching.
    """

    resolver = AgentModelResolver(
        settings=deployment_config(), keys=StubKeyService(None)
    )

    with pytest.raises(AgentModelConfigurationError, match="needs its own key") as error:
        await resolver.resolve(
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            graph_id=GRAPH_ID,
            agent=agent(CUSTOM),
        )
    assert DEPLOYMENT_KEY not in str(error.value)
    assert AGENT_KEY not in str(error.value)


@pytest.mark.parametrize(
    ("overrides", "variable"),
    [
        ({"agent_default_model": None}, "GRAFY_AGENT_DEFAULT_MODEL"),
        ({"agent_default_base_url": None}, "GRAFY_AGENT_DEFAULT_BASE_URL"),
        ({"agent_default_api_key": None}, "GRAFY_AGENT_DEFAULT_API_KEY"),
    ],
)
async def test_a_half_a_default_refuses_to_answer_and_says_what_is_missing(
    overrides: dict[str, object], variable: str
) -> None:
    keys = StubKeyService()
    resolver = AgentModelResolver(
        settings=deployment_config(**overrides), keys=keys
    )

    with pytest.raises(AgentModelConfigurationError, match=variable):
        await resolver.resolve(
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            graph_id=GRAPH_ID,
            agent=agent(),
        )
    assert keys.resolve_calls == []


async def test_description_says_which_model_without_saying_what_the_key_is() -> None:
    resolver = AgentModelResolver(
        settings=deployment_config(), keys=StubKeyService()
    )

    described = await resolver.describe(
        access=viewer_access(),
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent=agent(CUSTOM),
    )
    assert described.source == "agent"
    assert described.model_name == "gpt-5-mini"
    assert described.base_url == "https://models.example/v1"
    assert described.key_configured is True
    assert not hasattr(described, "api_key")

    deployment_side = await resolver.describe(
        access=viewer_access(),
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent=agent(),
    )
    assert deployment_side.source == "deployment"
    assert deployment_side.model_name == "llama-4"
    assert DEPLOYMENT_KEY not in repr(deployment_side)


async def test_the_resolved_model_dials_the_pinned_transport_with_the_deployment_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A private answer is refused, and accepted only where the operator granted it.

    Both choices land here: the deployment's own endpoint may be private because the
    operator named it, and an Agent's endpoint goes through the same guard an LLM node's
    `base_url` does.
    """

    async def resolves_to_private(
        host: str, port: int, timeout_seconds: float
    ) -> list[Any]:
        del host, port, timeout_seconds
        return [(2, 1, 6, "", ("10.0.0.8", 443))]

    monkeypatch.setattr(egress_module, "_lookup", resolves_to_private)

    class Recorder:
        def __init__(self) -> None:
            self.seen: list[httpx.Request] = []

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.seen.append(request)
            return httpx.Response(200, json={"ok": True})

        async def aclose(self) -> None:
            return None

    ungranted = ResolvedAgentModel(
        source="agent",
        model_name="gpt-5-mini",
        base_url="https://models.internal/v1",
        api_key=SecretStr(AGENT_KEY),
        egress_policy=EgressPolicy.from_destinations([]),
    )
    refused = Recorder()
    transport = ungranted.build_transport(transport=refused)
    request = httpx.Request("POST", "https://models.internal/v1/chat/completions")

    with pytest.raises(egress_module.EgressRejectedError, match="non-public address"):
        await transport.handle_async_request(request)
    assert refused.seen == []

    granted = ResolvedAgentModel(
        source="deployment",
        model_name="llama-4",
        base_url="https://models.internal/v1",
        api_key=SecretStr(DEPLOYMENT_KEY),
        egress_policy=EgressPolicy.from_destinations(["models.internal"]),
    )
    dialled_into = Recorder()
    transport = granted.build_transport(transport=dialled_into)
    response = await transport.handle_async_request(request)

    assert response.status_code == 200
    dialled = dialled_into.seen[0]
    # The address is what gets dialed; the name is what the service and its certificate
    # were issued for.
    assert dialled.url.host == "10.0.0.8"
    assert dialled.headers["host"] == "models.internal"
    assert dialled.extensions["sni_hostname"] == "models.internal"
    await transport.aclose()


def test_the_chat_model_carries_the_resolved_endpoint_and_name() -> None:
    """The turn loop's entry point: one call, and the pin is inside it."""

    resolved = ResolvedAgentModel(
        source="deployment",
        model_name="llama-4",
        base_url="https://models.internal:11434/v1",
        api_key=SecretStr(DEPLOYMENT_KEY),
        egress_policy=EgressPolicy.from_destinations(["models.internal:11434"]),
    )

    model = resolved.build_chat_model()

    assert model.model_name == "llama-4"
    assert str(model.provider.client.base_url) == "https://models.internal:11434/v1/"
    assert DEPLOYMENT_KEY not in repr(model)
