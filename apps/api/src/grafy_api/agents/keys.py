"""Write-only per-Agent model credentials (ADR 0021, issue #202).

An Agent may be given an endpoint and key of its own by whoever can configure it, and
everyone who can send to that Agent then uses them. Two consequences shape this owner:

* **The value is write-only.** There is one read path, `resolve_key`, and it exists for
  the model resolver inside the process. No state, log line or return value on the
  configuration surface carries key material — only `AgentKeyState(configured=...)`.
* **Permission is `edit_project`, not `manage_secrets`.** Placing and configuring an
  Agent is a canvas edit, so its key follows the canvas permission (ADR 0021). Unlike a
  node secret, it does not need a separate secret-management role.

`access` is taken as an argument rather than trusted implicitly: a route above resolves
the caller's Workspace access (role ∩ PAT scope ∩ capability) and hands it down, and this
owner re-checks `edit_project` on it. The route must declare the same capability, because
a service re-check consults the role only and a scoped token would otherwise slip under
it — the rule `tests/unit/architecture/test_capability_declarations.py` enforces for the
core application services applies here too.

The seal binds the row to where the Agent sits. A ciphertext copied beside another
Agent's coordinates fails to authenticate rather than leaking a credential, and a row
written under a different deployment key reports itself unconfigured instead of failing
at the first send.
"""

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from grafy_api.credential_keys import (
    MAX_SEALED_CREDENTIAL_BYTES,
    CredentialKeyConfigurationError,
    resolve_credential_encryption_key,
)
from grafy_core.domain.agent_keys import AGENT_KEY_AAD_VERSION, EncryptedAgentKey
from grafy_core.domain.collaboration import ProjectHead
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.identity import WorkspaceAccess, WorkspaceCapability
from grafy_core.kernel.project import GraphDefinition, ProjectDocumentError
from grafy_core.ports.agent_keys import AgentKeyUnitOfWorkPort

logger = logging.getLogger(__name__)


class AgentKeyConfigurationError(RuntimeError):
    """This deployment cannot seal or unseal Agent keys as configured."""


class AgentKeyValueError(ValueError):
    """The submitted key is not something worth sealing."""


class AgentKeyDeclarationError(LookupError):
    """The named Agent is not on the named Graph."""


class AgentKeyUnavailableError(RuntimeError):
    """No usable key is configured for this Agent on this server."""


@dataclass(frozen=True, slots=True)
class AgentKeyState:
    """What the configuration surface may say about one Agent's key."""

    agent_id: str
    configured: bool


class AgentKeyService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], AgentKeyUnitOfWorkPort],
        encryption_key: SecretStr | None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._encryption_key = encryption_key

    async def state(
        self,
        *,
        access: WorkspaceAccess,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> AgentKeyState:
        """Whether this Agent has a key this server can use. Never the key itself."""

        access.require(WorkspaceCapability.VIEW_PROJECT)
        async with self._unit_of_work_factory() as unit_of_work:
            head = await self._head(unit_of_work, access.workspace_id, project_id)
            self._agent(head, graph_id, agent_id)
            stored = await unit_of_work.agent_keys.get(
                access.workspace_id, project_id, graph_id, agent_id
            )
        active_key_id = self._active_key_id()
        return AgentKeyState(
            agent_id=agent_id,
            configured=(
                stored is not None
                and active_key_id is not None
                and stored.key_id == active_key_id
            ),
        )

    async def set_key(
        self,
        *,
        access: WorkspaceAccess,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
        value: SecretStr,
    ) -> AgentKeyState:
        """Seal `value` as this Agent's key. The plaintext never leaves this method."""

        access.require(WorkspaceCapability.EDIT_PROJECT)
        plaintext = self._validated_plaintext(value)
        key, key_id = self._resolved_encryption_key()
        async with self._unit_of_work_factory() as unit_of_work:
            head = await self._head(unit_of_work, access.workspace_id, project_id)
            self._agent(head, graph_id, agent_id)
            nonce = os.urandom(12)
            aad = self._additional_authenticated_data(
                workspace_id=access.workspace_id,
                project_id=project_id,
                graph_id=graph_id,
                agent_id=agent_id,
            )
            now = datetime.now(UTC)
            sealed = EncryptedAgentKey(
                workspace_id=access.workspace_id,
                project_id=project_id,
                graph_id=graph_id,
                agent_id=agent_id,
                key_id=key_id,
                aad_version=AGENT_KEY_AAD_VERSION,
                nonce=nonce,
                ciphertext=AESGCM(key).encrypt(nonce, plaintext, aad),
                set_by_user_id=access.actor.user_id,
                created_at=now,
                updated_at=now,
            )
            await unit_of_work.agent_keys.upsert(sealed)
            await unit_of_work.commit()
        logger.info(
            "agent_key_configured workspace_id=%s project_id=%s graph_id=%s agent_id=%s",
            access.workspace_id,
            project_id,
            graph_id,
            agent_id,
        )
        return AgentKeyState(agent_id=agent_id, configured=True)

    async def clear_key(
        self,
        *,
        access: WorkspaceAccess,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> AgentKeyState:
        """Drop this Agent's own key. Clearing does not read what it held."""

        access.require(WorkspaceCapability.EDIT_PROJECT)
        async with self._unit_of_work_factory() as unit_of_work:
            head = await self._head(unit_of_work, access.workspace_id, project_id)
            self._agent(head, graph_id, agent_id)
            await unit_of_work.agent_keys.remove(
                access.workspace_id, project_id, graph_id, agent_id
            )
            await unit_of_work.commit()
        logger.info(
            "agent_key_cleared workspace_id=%s project_id=%s graph_id=%s agent_id=%s",
            access.workspace_id,
            project_id,
            graph_id,
            agent_id,
        )
        return AgentKeyState(agent_id=agent_id, configured=False)

    async def resolve_key(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> SecretStr:
        """Unseal the Agent's own key for the process that will dial with it.

        Called by `grafy_api.agents.models`, not by a route: a key is spent on one
        request to the endpoint its Agent names and is never returned to a caller that
        asked for it over HTTP.
        """

        async with self._unit_of_work_factory() as unit_of_work:
            head = await self._head(unit_of_work, workspace_id, project_id)
            self._agent(head, graph_id, agent_id)
            stored = await unit_of_work.agent_keys.get(
                workspace_id, project_id, graph_id, agent_id
            )
        if stored is None:
            raise AgentKeyUnavailableError(
                f"Agent {agent_id} has no configured model key"
            )
        key, key_id = self._resolved_encryption_key()
        if stored.key_id != key_id:
            raise AgentKeyUnavailableError(
                "Configured Agent key cannot be decrypted by this server"
            )
        aad = self._additional_authenticated_data(
            workspace_id=workspace_id,
            project_id=project_id,
            graph_id=stored.graph_id,
            agent_id=stored.agent_id,
        )
        try:
            plaintext = AESGCM(key).decrypt(stored.nonce, stored.ciphertext, aad)
        except (InvalidTag, ValueError) as exc:
            # One message for every reason a row will not open: whether a row exists,
            # belongs elsewhere, or was sealed for another binding must not be
            # distinguishable from here.
            raise AgentKeyUnavailableError(
                "Configured Agent key cannot be decrypted by this server"
            ) from exc
        try:
            return SecretStr(plaintext.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise AgentKeyUnavailableError(
                "Configured Agent key contains invalid encoded data"
            ) from exc

    @staticmethod
    def _validated_plaintext(value: SecretStr) -> bytes:
        text = value.get_secret_value()
        if text.strip() == "":
            raise AgentKeyValueError("Agent key must not be empty")
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_SEALED_CREDENTIAL_BYTES:
            raise AgentKeyValueError(
                "Agent key must not exceed "
                f"{MAX_SEALED_CREDENTIAL_BYTES} UTF-8 bytes"
            )
        return encoded

    @staticmethod
    def _additional_authenticated_data(
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> bytes:
        return json.dumps(
            {
                "version": AGENT_KEY_AAD_VERSION,
                "workspace_id": str(workspace_id),
                "project_id": str(project_id),
                "graph_id": graph_id,
                "agent_id": agent_id,
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    async def _head(
        unit_of_work: AgentKeyUnitOfWorkPort,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectHead:
        head = await unit_of_work.collaboration.get_head(workspace_id, project_id)
        if head is None:
            raise NotFoundError("Project", str(project_id))
        return head

    @staticmethod
    def _agent(head: ProjectHead, graph_id: str, agent_id: str) -> None:
        """A key belongs to an Agent that is on the canvas, at the current head."""

        try:
            graph: GraphDefinition = head.document.get_graph(graph_id)
        except ProjectDocumentError as exc:
            raise NotFoundError("Graph", graph_id) from exc
        if not any(agent.id == agent_id for agent in graph.document.agents):
            raise AgentKeyDeclarationError(
                f"Agent {agent_id!r} is not on graph {graph.id}"
            )

    def _resolved_encryption_key(self) -> tuple[bytes, str]:
        try:
            return resolve_credential_encryption_key(self._encryption_key)
        except CredentialKeyConfigurationError as exc:
            raise AgentKeyConfigurationError(str(exc)) from exc

    def _active_key_id(self) -> str | None:
        try:
            _, key_id = self._resolved_encryption_key()
        except AgentKeyConfigurationError:
            return None
        return key_id


__all__ = [
    "AgentKeyConfigurationError",
    "AgentKeyDeclarationError",
    "AgentKeyService",
    "AgentKeyState",
    "AgentKeyUnavailableError",
    "AgentKeyValueError",
]
