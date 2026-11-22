from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field, replace
from typing import TYPE_CHECKING, Final, Protocol
from uuid import UUID

from pydantic import BaseModel, SecretStr

from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.ports.node_secrets import (
    NodeSecretResolverPort,
    UnavailableNodeSecretResolver,
)

if TYPE_CHECKING:
    from grafy_core.plugins import NodeSecretInput


MAX_NODE_PROGRESS_MESSAGE_LENGTH: Final = 1_000
MAX_NODE_PROGRESS_COUNTER: Final = 9_007_199_254_740_991
MAX_NODE_ERROR_MESSAGE_LENGTH: Final = 1_000


class UserFacingNodeError(RuntimeError):
    """An operator failure whose bounded message is safe to show to graph users.

    Raising this exception is an explicit assertion by Plugin code that the
    message contains no credentials, prompts, provider response bodies, or other
    sensitive runtime state. Unknown exceptions remain private implementation
    failures and cross runtime adapters only as a generic error.
    """

    def __init__(self, message: str) -> None:
        normalized = message.strip()
        if normalized == "":
            raise ValueError("User-facing node error message must not be blank")
        if len(normalized) > MAX_NODE_ERROR_MESSAGE_LENGTH:
            raise ValueError(
                "User-facing node error message must be at most "
                f"{MAX_NODE_ERROR_MESSAGE_LENGTH} characters"
            )
        super().__init__(normalized)


class NodeProgressReporter(Protocol):
    """Host boundary for ephemeral, user-visible node progress."""

    async def report_progress(
        self,
        context: "NodeExecutionContext",
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None: ...


class NodeSecretRequirementError(RuntimeError):
    """A node used ``context.secrets`` in a way its own declaration does not allow.

    The declaration is the whole authority a node has over its credentials, so
    asking for an undeclared name, or for one whose configuration dependency this
    run was never given, is a programming error rather than a state a graph author
    can correct.
    """


@dataclass(frozen=True, slots=True)
class NodeSecrets:
    """The credentials of exactly one node, bound when its context was built.

    A node only ever names a secret. Where that secret lives -- the Workspace,
    Project and Graph it belongs to, the node that holds it, and the configuration
    values it was declared against -- comes from the binding the runner made, so a
    node cannot reach another node's credential and cannot mis-state the
    configuration its own credential belongs to.
    """

    resolver: NodeSecretResolverPort = dataclass_field(
        default_factory=UnavailableNodeSecretResolver
    )
    workspace_id: UUID | None = None
    project_id: UUID | None = None
    graph_id: str | None = None
    node_id: str | None = None
    secret_inputs: Sequence["NodeSecretInput"] = ()
    config_values: Mapping[str, JsonValue] = dataclass_field(
        default_factory=dict[str, JsonValue],
        repr=False,
    )

    actor_user_id: UUID | None = None

    async def require(self, name: str) -> SecretStr:
        """Read one secret this node declared.

        A name the node did not declare raises immediately. A declared secret that
        neither the graph nor the deployment carries is a state of the graph, so it
        surfaces as the user-facing failure the node would have raised itself.
        """

        declaration: NodeSecretInput | None = None
        for candidate in self.secret_inputs:
            if candidate.name == name:
                declaration = candidate
                break
        if declaration is None:
            raise NodeSecretRequirementError(
                f"Node {self.node_id!r} does not declare secret input {name!r}"
            )
        workspace_id = self.workspace_id
        if workspace_id is None:
            raise NodeSecretRequirementError(
                f"Node {self.node_id!r} secrets were never bound to a Workspace"
            )
        try:
            dependencies = {
                dependency: self.config_values[dependency]
                for dependency in declaration.config_dependencies
            }
        except KeyError as exc:
            raise NodeSecretRequirementError(
                f"Node {self.node_id!r} secret {name!r} dependency {exc.args[0]!r} "
                "is not in the node's configuration"
            ) from exc
        try:
            return await self.resolver.resolve_secret(
                workspace_id=workspace_id,
                project_id=self.project_id,
                graph_id=self.graph_id,
                node_id=self.node_id,
                name=name,
                dependencies=dependencies,
                actor_user_id=self.actor_user_id,
            )
        except Exception as exc:
            raise UserFacingNodeError(
                f"Node {self.node_id!r} could not resolve its {declaration.title}"
            ) from exc


@dataclass(frozen=True, slots=True)
class NodeExecutionContext:
    """Where one node instance runs, in Project vocabulary (ADR 0020).

    ``graph_id`` and ``node_id`` name the instance inside the Graph it belongs to,
    ``call_path`` the call nodes entered to reach that Graph, and ``fingerprint``
    the digest its result is stored under. An operator that needs a stable
    identity of its own has that fingerprint, not a per-run identifier: runs are
    demands for fresh results and never own one.
    """

    workspace_id: UUID
    project_id: UUID | None = None
    graph_id: str | None = None
    node_id: str | None = None
    call_path: tuple[str, ...] = ()
    fingerprint: str | None = None
    invocation_index: int | None = None
    invocation_path: tuple[int, ...] = ()
    artifact_type_bindings: Mapping[str, ArtifactTypeKey] = dataclass_field(
        default_factory=dict[str, ArtifactTypeKey],
        repr=False,
        compare=False,
    )
    progress_reporter: NodeProgressReporter | None = dataclass_field(
        default=None,
        repr=False,
        compare=False,
    )
    # A context nobody bound secrets onto declares none, so any name a node
    # asks it for is refused as the programming error it is.
    secrets: NodeSecrets = dataclass_field(
        default_factory=NodeSecrets,
        repr=False,
        compare=False,
    )
    # Notes a node attaches to its own computation (for example unsupported
    # optional outputs). Merged into the metadata written with the result.
    output_metadata: dict[str, object] = dataclass_field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    actor_user_id: UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "call_path", tuple(self.call_path))
        object.__setattr__(self, "invocation_path", tuple(self.invocation_path))

    async def progress(
        self,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        """Publish bounded progress text without exposing node inputs or config."""

        normalized_message = message.strip()
        if normalized_message == "":
            raise ValueError("Node progress message must not be blank")
        if len(normalized_message) > MAX_NODE_PROGRESS_MESSAGE_LENGTH:
            raise ValueError(
                "Node progress message must be at most "
                f"{MAX_NODE_PROGRESS_MESSAGE_LENGTH} characters"
            )
        if current is not None and current < 0:
            raise ValueError("Node progress current value must not be negative")
        if current is not None and current > MAX_NODE_PROGRESS_COUNTER:
            raise ValueError(
                "Node progress current value must not exceed "
                f"{MAX_NODE_PROGRESS_COUNTER}"
            )
        if total is not None and total < 0:
            raise ValueError("Node progress total value must not be negative")
        if total is not None and total > MAX_NODE_PROGRESS_COUNTER:
            raise ValueError(
                f"Node progress total value must not exceed {MAX_NODE_PROGRESS_COUNTER}"
            )
        if current is not None and total is not None and current > total:
            raise ValueError("Node progress current value must not exceed total")

        reporter = self.progress_reporter
        if reporter is None:
            return
        try:
            await reporter.report_progress(
                self,
                normalized_message,
                current=current,
                total=total,
            )
        except Exception:
            # User-visible reporting is best-effort. Reporter failures must not
            # turn a successful node action into a failed graph execution.
            return


def bind_node_secrets(
    context: NodeExecutionContext,
    resolver: NodeSecretResolverPort,
    secret_inputs: Sequence["NodeSecretInput"],
) -> NodeExecutionContext:
    """Bind one node's own credentials onto the context it runs with.

    The runner calls this for the node it is about to execute: the identity that
    says whose secret this is comes from the context and the operator's own
    declaration, never from the node body.
    """

    return replace(
        context,
        secrets=NodeSecrets(
            resolver=resolver,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            graph_id=context.graph_id,
            node_id=context.node_id,
            secret_inputs=secret_inputs,
            actor_user_id=context.actor_user_id,
        ),
    )


def bind_node_secret_config(
    context: NodeExecutionContext,
    config: BaseModel,
) -> NodeExecutionContext:
    """Hand a node's secrets the configuration their dependencies read from.

    A secret may name any configuration field as its dependency, including one the
    graph document omits and the node's own contract supplies a default for, so the
    validated model is the only place those values can come from. A node that
    declares no secrets keeps the context it was handed.
    """

    secrets = context.secrets
    if not secrets.secret_inputs:
        return context
    return replace(
        context,
        secrets=replace(secrets, config_values=config.model_dump(mode="json")),
    )
