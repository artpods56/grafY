"""Node secrets: the API keys a provider node (OCR, LLM, ...) runs with.

A secret value passed to `set_node_secret` goes to the API, is encrypted at rest and
is never returned by any tool; statuses only say whether a value is configured. The
token needs the `manage_secrets` scope, like the Workbench's secret panel.
"""

from typing import Annotated, Any, Final, Literal
from uuid import UUID

from grafy_core.domain.credentials import (
    SharedCredentialBindingMode,
    UserCredentialOverrideMode,
)
from pydantic import Field, SecretStr

from grafy_api.mcp.context import DESTRUCTIVE, IDEMPOTENT_EDIT, READ, dump, grafy, tool


async def get_node_secrets(project_id: UUID, graph_id: str) -> dict[str, Any]:
    """Which secrets each node of a Graph needs and how each is resolved
    (node value, shared credential, personal credential, deployment default)."""
    async with grafy() as (client, workspace_id):
        return dump(
            await client.projects.secret_status(
                workspace_id, project_id, graph_id=graph_id
            )
        )


async def set_node_secret(
    project_id: UUID,
    graph_id: str,
    node_id: str,
    secret_name: str,
    value: Annotated[str, Field(min_length=1, description="Never echoed back")],
) -> dict[str, Any]:
    """Store a secret value on one node, encrypted. Only its status is returned."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        status = await client.projects.configure_secret(
            workspace_id,
            project_id,
            graph_id=graph_id,
            node_id=node_id,
            secret_name=secret_name,
            value=SecretStr(value),
            head=head,
        )
    return dump(status)


async def delete_node_secret(
    project_id: UUID, graph_id: str, node_id: str, secret_name: str
) -> dict[str, Any]:
    """Remove a node's stored secret value."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        await client.projects.delete_secret(
            workspace_id,
            project_id,
            graph_id=graph_id,
            node_id=node_id,
            secret_name=secret_name,
            head=head,
        )
    return {"deleted": secret_name, "node_id": node_id}


async def bind_node_secret(
    project_id: UUID,
    graph_id: str,
    node_id: str,
    secret_name: str,
    mode: Annotated[
        SharedCredentialBindingMode | Literal["none"],
        Field(
            description=(
                "credential: a shared Workspace credential (give credential_id); "
                "personal: each member's own; deployment_default; none: unbind"
            )
        ),
    ],
    credential_id: UUID | None = None,
) -> dict[str, Any]:
    """Point a node's secret at a shared credential instead of a stored value."""
    async with grafy() as (client, workspace_id):
        head = await client.projects.head(workspace_id, project_id)
        detail = await client.projects.set_secret_shared_binding(
            workspace_id,
            project_id,
            graph_id=graph_id,
            node_id=node_id,
            secret_name=secret_name,
            mode=mode,
            head=head,
            credential_id=credential_id,
        )
    return dump(detail)


async def choose_personal_secret(
    project_id: UUID,
    graph_id: str,
    node_id: str,
    secret_name: str,
    mode: Annotated[
        UserCredentialOverrideMode | Literal["none"],
        Field(
            description=(
                "credential: one of your personal credentials (credential_id); "
                "shared; deployment_default; none: clear your choice"
            )
        ),
    ],
    credential_id: UUID | None = None,
) -> dict[str, Any]:
    """Choose, for yourself only, which credential a node's secret uses when you
    run it."""
    async with grafy() as (client, workspace_id):
        detail = await client.projects.set_secret_personal_selection(
            workspace_id,
            project_id,
            graph_id=graph_id,
            node_id=node_id,
            secret_name=secret_name,
            mode=mode,
            credential_id=credential_id,
        )
    return dump(detail)


async def verify_node_secret(
    project_id: UUID,
    graph_id: str,
    node_id: str,
    secret_name: str,
) -> dict[str, Any]:
    """Ask the provider whether the secret the node would run with is accepted."""
    async with grafy() as (client, workspace_id):
        verification = await client.projects.verify_secret(
            workspace_id,
            project_id,
            graph_id=graph_id,
            node_id=node_id,
            secret_name=secret_name,
        )
    return dump(verification)


TOOLS: Final = (
    tool(get_node_secrets, READ, tags={"secrets"}),
    tool(set_node_secret, IDEMPOTENT_EDIT, tags={"secrets"}),
    tool(delete_node_secret, DESTRUCTIVE, tags={"secrets"}),
    tool(bind_node_secret, IDEMPOTENT_EDIT, tags={"secrets"}),
    tool(choose_personal_secret, IDEMPOTENT_EDIT, tags={"secrets"}),
    tool(verify_node_secret, READ, tags={"secrets"}),
)
