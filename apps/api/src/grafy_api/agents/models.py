"""Which model an Agent talks to, and how this process dials it (ADR 0021, issue #202).

Two choices reach this owner from the Graph document, and one from the deployment:

* `DeploymentAgentModel` — the operator's default endpoint, model and key. The endpoint
  may name a private destination, because an operator grant
  (`GRAFY_EGRESS_TRUSTED_DESTINATIONS`) is what makes a destination dialable, and only
  the operator can widen it.
* `CustomAgentModel` — an endpoint and model whoever configured the Agent chose. The
  document already refused a literal private address and a credential-bearing URL when
  the Agent was saved (`grafy_core.egress.validated_public_destination`); at dial time
  the same pinned public-address transport and the same egress restrictions the LLM
  family uses decide whether the name may be reached at all.

Both produce one `ResolvedAgentModel`, which carries the secret and the transport rule
together so a caller cannot use the endpoint without it. The next unit — the AgentService
turn loop — is the intended consumer: `resolve` gives it a model, and nothing here runs a
turn, opens a connection or stores an event.

`describe` exists because the web needs to show *which* model an Agent will use, and a
route that had to reach into a `ResolvedAgentModel` to do it would be one refactor away
from answering with `api_key`.
"""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

import httpx
from openai import AsyncOpenAI
from pydantic import SecretStr
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from grafy_api.agents.keys import AgentKeyState, AgentKeyUnavailableError
from grafy_core.domain.graph_documents import (
    DeploymentAgentModel,
    GraphAgent,
)
from grafy_core.domain.identity import WorkspaceAccess
from grafy_core.egress import EgressPolicy, PinnedPublicAddressTransport
from grafy_shared.config import AgentsConfig

AgentModelSource = Literal["deployment", "agent"]
"""Whether the endpoint and key came from the deployment or from the Agent itself."""


class AgentModelConfigurationError(RuntimeError):
    """No model can be dialed for this Agent as it and the deployment are configured."""


@dataclass(frozen=True, slots=True)
class ResolvedAgentModel:
    """One endpoint, one model name, one key, and the rule for reaching them."""

    source: AgentModelSource
    model_name: str
    base_url: str
    api_key: SecretStr
    egress_policy: EgressPolicy | None = None
    """``None`` defers to the deployment policy read from the environment, which is how
    a family deep inside an SDK reaches the same authority as one handed a Settings."""

    def build_transport(
        self, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> httpx.AsyncBaseTransport:
        """The pinned transport: resolve first, dial the answer, keep the name.

        Provider SDKs build their own requests, so the pin has to sit underneath them,
        exactly as it does for the LLM family's `base_url`. A caller may pass the inner
        transport it wants pinned — its own connection limits, or a double in a test —
        and gets the same egress decision either way.
        """

        return PinnedPublicAddressTransport(
            policy=self.egress_policy, transport=transport
        )

    def build_openai_client(self) -> AsyncOpenAI:
        """An async client for this model. Whoever opens it closes it."""

        return AsyncOpenAI(
            api_key=self.api_key.get_secret_value(),
            base_url=self.base_url,
            http_client=httpx.AsyncClient(transport=self.build_transport()),
        )

    def build_chat_model(self) -> OpenAIChatModel:
        """The pydantic-ai model the turn loop runs on.

        The client is handed in rather than built by the provider so the pin survives:
        a provider given only a `base_url` would dial whatever DNS says. Whoever calls
        this cannot close what it made, so it is the answer for a caller that owns the
        process; a turn dials through `build_owned_chat_model`.
        """

        return OpenAIChatModel(
            self.model_name,
            provider=OpenAIProvider(openai_client=self.build_openai_client()),
        )

    def build_owned_chat_model(self) -> "OwnedAgentChatModel":
        """A model, and the only way to hand its connection back.

        A turn opens one of these and closes it on every path out of the turn — answered,
        cancelled, failed — because a client nobody closes is a connection pool that outlives
        the conversation it was dialled for, and the key sits inside it the whole time.
        """

        client = self.build_openai_client()
        return OwnedAgentChatModel(
            chat_model=OpenAIChatModel(
                self.model_name, provider=OpenAIProvider(openai_client=client)
            ),
            client=client,
        )


@dataclass(frozen=True, slots=True)
class OwnedAgentChatModel:
    """A dialled model and the client underneath it. `aclose` is idempotent."""

    chat_model: OpenAIChatModel
    client: AsyncOpenAI
    _closed: bool = False

    async def aclose(self) -> None:
        if self._closed:
            return
        object.__setattr__(self, "_closed", True)
        # Closing the SDK client closes the httpx client it was handed, which is the
        # pinned transport too: the whole route to the endpoint goes with it.
        await self.client.close()


@dataclass(frozen=True, slots=True)
class AgentModelDescription:
    """What a surface may say about an Agent's model."""

    source: AgentModelSource
    model_name: str
    base_url: str
    key_configured: bool


class AgentKeyReader(Protocol):
    """What resolution needs from the key owner, and nothing more.

    The resolver never holds the key service whole: it asks for one Agent's sealed key when
    an Agent named its own endpoint, and for a configured/unconfigured answer when a surface
    asks what an Agent will use. `AgentKeyService` is that owner; naming the two methods here
    is what keeps a model choice from reaching a set or a clear.
    """

    async def resolve_key(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> SecretStr: ...

    async def state(
        self,
        *,
        access: WorkspaceAccess,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> AgentKeyState: ...


class AgentModelReader(Protocol):
    """What the turn runtime needs from model resolution, and nothing more.

    A turn resolves one Agent's model to run one turn on it. Naming just `resolve` here is
    what keeps a running conversation from being able to ask the same object what a
    configuration surface would answer, or to reach the key owner behind it.
    """

    async def resolve(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent: GraphAgent,
    ) -> ResolvedAgentModel: ...


class AgentModelResolver:
    def __init__(
        self,
        *,
        settings: AgentsConfig,
        keys: AgentKeyReader,
        egress_policy: EgressPolicy | None = None,
    ) -> None:
        self._settings = settings
        self._keys = keys
        self._egress_policy = egress_policy

    def resolve_deployment_default(self) -> ResolvedAgentModel:
        """The model an Agent gets when it asks for none of its own."""

        settings = self._settings
        missing = settings.incomplete_default()
        model_name = settings.agent_default_model
        base_url = settings.agent_default_base_url
        api_key = settings.agent_default_api_key
        if missing is not None or base_url is None or api_key is None or not model_name:
            raise AgentModelConfigurationError(
                "This deployment has no default Agent model: set "
                + (missing or "GRAFY_AGENT_DEFAULT_MODEL")
            )
        return ResolvedAgentModel(
            source="deployment",
            model_name=model_name,
            base_url=str(base_url),
            api_key=api_key,
            egress_policy=self._egress_policy,
        )

    async def resolve(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent: GraphAgent,
    ) -> ResolvedAgentModel:
        """The model for one Agent, spending its own key when it has one."""

        choice = agent.model
        if isinstance(choice, DeploymentAgentModel):
            return self.resolve_deployment_default()
        try:
            api_key = await self._keys.resolve_key(
                workspace_id=workspace_id,
                project_id=project_id,
                graph_id=graph_id,
                agent_id=agent.id,
            )
        except AgentKeyUnavailableError as exc:
            raise AgentModelConfigurationError(
                f"Agent {agent.id} uses its own endpoint and needs its own key"
            ) from exc
        return ResolvedAgentModel(
            source="agent",
            model_name=choice.model,
            base_url=choice.endpoint,
            api_key=api_key,
            egress_policy=self._egress_policy,
        )

    async def describe(
        self,
        *,
        access: WorkspaceAccess,
        project_id: UUID,
        graph_id: str,
        agent: GraphAgent,
    ) -> AgentModelDescription:
        """Which model this Agent will use, with nothing secret in the answer.

        The caller's access is required because the answer includes whether the Agent's
        own key is in place, and that is a fact about a Project not everyone can read.
        """

        choice = agent.model
        if isinstance(choice, DeploymentAgentModel):
            base_url = self._settings.agent_default_base_url
            return AgentModelDescription(
                source="deployment",
                model_name=self._settings.agent_default_model or "",
                base_url="" if base_url is None else str(base_url),
                key_configured=self._settings.incomplete_default() is None,
            )
        key_state = await self._keys.state(
            access=access,
            project_id=project_id,
            graph_id=graph_id,
            agent_id=agent.id,
        )
        return AgentModelDescription(
            source="agent",
            model_name=choice.model,
            base_url=choice.endpoint,
            key_configured=key_state.configured,
        )


__all__ = [
    "AgentModelConfigurationError",
    "AgentModelReader",
    "OwnedAgentChatModel",
    "AgentModelDescription",
    "AgentModelResolver",
    "AgentModelSource",
    "AgentKeyReader",
    "ResolvedAgentModel",
]
