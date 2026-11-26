"""The Workspace Library: files and saved results a user keeps across Projects."""

import base64
import binascii
from typing import Annotated, Any, Final
from uuid import UUID

from fastmcp.exceptions import ToolError
from pydantic import Field

from grafy_api.mcp.context import (
    DESTRUCTIVE,
    EDIT,
    IDEMPOTENT_EDIT,
    READ,
    dump,
    grafy,
    tool,
)

_MAX_INLINE_UPLOAD_BYTES: Final = 2 * 1024 * 1024


async def list_library() -> list[dict[str, Any]]:
    """Artifacts saved in the Workspace Library."""
    async with grafy() as (client, workspace_id):
        return [dump(item) for item in await client.library.list(workspace_id)]


async def upload_file(
    filename: Annotated[
        str, Field(description="The extension decides the file format")
    ],
    content_base64: str,
    save_to_library: bool = True,
) -> dict[str, Any]:
    """Upload a small file (up to 2 MiB) and get its typed artifact reference.

    Only a deployment whose API receives upload bytes serves this tool. Where the
    API hands out signed object-storage URLs instead, the bytes cannot be sent from
    inside the API process and the tool reports that; use the staged upload API over
    HTTP. Larger files go through that API in every deployment (`grafy_client`
    uploads stream a file of any size the deployment accepts).
    """
    try:
        content = base64.b64decode(content_base64, validate=True)
    except binascii.Error as exc:
        raise ToolError("content_base64 is not valid base64") from exc
    if len(content) > _MAX_INLINE_UPLOAD_BYTES:
        raise ToolError("Inline uploads are limited to 2 MiB")
    async with grafy() as (client, workspace_id):
        upload = await client.uploads.upload(workspace_id, content, filename=filename)
        content_hash: str | None = None
        saved = False
        if save_to_library and upload.artifact_id is not None:
            item = await client.library.save_from_upload(
                workspace_id,
                artifact_id=upload.artifact_id,
                original_filename=upload.filename,
            )
            content_hash = item.artifact.sha256
            saved = True
    return {
        **dump(upload),
        "content_hash": content_hash,
        "saved_to_library": saved,
    }


async def save_result_to_library(
    project_id: UUID,
    graph_id: str,
    node_id: str,
    output_port: str,
    name: str,
    call_path: list[str] | None = None,
    item_index: Annotated[
        int | None,
        Field(ge=0, description="Save one item of a list output instead of all"),
    ] = None,
) -> dict[str, Any]:
    """Keep a node's current result in the Library, so other Projects can use it
    and it survives the Project's next Run."""
    async with grafy() as (client, workspace_id):
        result = await client.runs.instance_result(
            workspace_id,
            project_id,
            graph_id=graph_id,
            node_id=node_id,
            call_path=call_path or [],
        )
        if result.result_fingerprint is None:
            raise ToolError(f"Node {node_id!r} has no result yet; run it first")
        item = await client.library.save_from_instance(
            workspace_id,
            project_id=project_id,
            graph_id=graph_id,
            node_id=node_id,
            result_fingerprint=result.result_fingerprint,
            output_port=output_port,
            name=name,
            call_path=tuple(call_path or []),
            item_index=item_index,
        )
    return dump(item)


async def delete_library_item(artifact_id: UUID) -> dict[str, Any]:
    """Remove an artifact from the Library. Graphs that use it keep their exact
    reference and show it as missing."""
    async with grafy() as (client, workspace_id):
        await client.library.delete(workspace_id, artifact_id)
    return {"deleted": str(artifact_id)}


async def list_library_folders() -> list[dict[str, Any]]:
    """Your Library folders (a tree; folders belong to you, not the Workspace)."""
    async with grafy() as (client, workspace_id):
        return [dump(item) for item in await client.library.list_folders(workspace_id)]


async def create_library_folder(
    name: str, parent_id: UUID | None = None
) -> dict[str, Any]:
    """Create a Library folder, at the top or inside another folder."""
    async with grafy() as (client, workspace_id):
        return dump(
            await client.library.create_folder(
                workspace_id, name=name, parent_id=parent_id
            )
        )


async def rename_library_folder(folder_id: UUID, name: str) -> dict[str, Any]:
    """Rename a Library folder."""
    async with grafy() as (client, workspace_id):
        return dump(
            await client.library.rename_folder(workspace_id, folder_id, name=name)
        )


async def move_library_folder(
    folder_id: UUID,
    parent_id: Annotated[UUID | None, Field(description="null moves it to the top")],
) -> dict[str, Any]:
    """Move a Library folder under another folder, or to the top."""
    async with grafy() as (client, workspace_id):
        return dump(
            await client.library.move_folder(
                workspace_id, folder_id, parent_id=parent_id
            )
        )


async def delete_library_folder(folder_id: UUID) -> dict[str, Any]:
    """Delete a Library folder; its artifacts stay in the Library, unfiled."""
    async with grafy() as (client, workspace_id):
        await client.library.delete_folder(workspace_id, folder_id)
    return {"deleted": str(folder_id)}


async def file_library_items(
    artifact_ids: Annotated[list[UUID], Field(min_length=1)],
    folder_id: Annotated[UUID | None, Field(description="null for unfiled")],
) -> dict[str, Any]:
    """Put Library artifacts in a folder, or take them out of folders."""
    async with grafy() as (client, workspace_id):
        await client.library.move_artifacts(
            workspace_id, artifact_ids=artifact_ids, folder_id=folder_id
        )
    return {"moved": [str(artifact_id) for artifact_id in artifact_ids]}


TOOLS: Final = (
    tool(list_library, READ, tags={"library"}),
    tool(upload_file, EDIT, tags={"library"}),
    tool(save_result_to_library, EDIT, tags={"library"}),
    tool(delete_library_item, DESTRUCTIVE, tags={"library"}),
    tool(list_library_folders, READ, tags={"library", "folders"}),
    tool(create_library_folder, EDIT, tags={"library", "folders"}),
    tool(rename_library_folder, IDEMPOTENT_EDIT, tags={"library", "folders"}),
    tool(move_library_folder, IDEMPOTENT_EDIT, tags={"library", "folders"}),
    tool(delete_library_folder, DESTRUCTIVE, tags={"library", "folders"}),
    tool(file_library_items, IDEMPOTENT_EDIT, tags={"library", "folders"}),
)
