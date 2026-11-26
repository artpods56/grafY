"""Artifacts: author JSON ones, and read raw text, tables, images and geo data."""

from typing import Annotated, Any, Final
from uuid import UUID

from pydantic import Field

from grafy_api.mcp.context import EDIT, READ, dump, grafy, tool

_MAX_TEXT_BYTES: Final = 256 * 1024

type MatchRows = Annotated[
    list[dict[str, str | int | float | bool]],
    Field(
        min_length=1,
        max_length=50,
        description="Keep rows equal to any one of these {column_id: value}",
    ),
]


async def list_authorable_artifact_types() -> list[dict[str, object]]:
    """List JSON artifact types and payload schemas accepted by create_artifact."""
    async with grafy() as (client, workspace_id):
        catalog = await client.catalog.get(workspace_id)
    return [spec for spec in catalog.artifact_types if spec.get("authorable") is True]


async def create_artifact(
    artifact_type: str,
    payload: dict[str, object],
    schema_version: Annotated[int, Field(ge=1)] = 1,
    derived_from_artifact_id: UUID | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Create an immutable artifact from JSON. Use its hash in author_graph cards.

    Pass the bare type id (for example scalar.text) and its schema version here.
    Pass id@version and the returned content_hash when placing it on a graph.
    """
    async with grafy() as (client, workspace_id):
        return dump(
            await client.artifacts.create_artifact(
                workspace_id,
                artifact_type=artifact_type,
                schema_version=schema_version,
                payload=payload,
                derived_from_artifact_id=derived_from_artifact_id,
                title=title,
            )
        )


async def read_artifact_text(
    artifact_id: UUID,
    max_bytes: Annotated[int, Field(ge=1, le=_MAX_TEXT_BYTES)] = 64 * 1024,
) -> dict[str, Any]:
    """The stored bytes of a text-like artifact (JSON, CSV, text), as UTF-8."""
    async with grafy() as (client, workspace_id):
        content = await client.artifacts.content(workspace_id, artifact_id)
    return {
        "text": content[:max_bytes].decode("utf-8", errors="replace"),
        "byte_size": len(content),
        "truncated": len(content) > max_bytes,
    }


async def get_table_schema(artifact_id: UUID) -> dict[str, Any]:
    """A table artifact's columns (id, title, value type) and row count."""
    async with grafy() as (client, workspace_id):
        return dump(await client.artifacts.table_schema(workspace_id, artifact_id))


async def read_table_page(
    artifact_id: UUID,
    offset: Annotated[int, Field(ge=0)] = 0,
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
    column_ids: list[str] | None = None,
) -> dict[str, Any]:
    """A window of table rows; long cells come back truncated."""
    async with grafy() as (client, workspace_id):
        page = await client.artifacts.table_page(
            workspace_id,
            artifact_id,
            offset=offset,
            limit=limit,
            column_ids=column_ids,
        )
    return dump(page)


async def query_table(
    artifact_id: UUID,
    match_rows: MatchRows,
    offset: Annotated[int, Field(ge=0)] = 0,
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    """Table rows that exactly match one of the given key rows."""
    async with grafy() as (client, workspace_id):
        page = await client.artifacts.table_query(
            workspace_id,
            artifact_id,
            filter_rows=match_rows,
            offset=offset,
            limit=limit,
        )
    return dump(page)


async def get_geo_render(artifact_id: UUID) -> dict[str, Any]:
    """A geo artifact's render descriptor: layers, bounds, basemap."""
    async with grafy() as (client, workspace_id):
        return dump(await client.artifacts.geo_render(workspace_id, artifact_id))


async def query_geo_features(
    artifact_id: UUID,
    match_rows: Annotated[
        list[dict[str, str | int | float | bool]],
        Field(
            min_length=1,
            max_length=50,
            description="Features whose properties equal any one of these rows",
        ),
    ],
) -> dict[str, Any]:
    """How many features match, and their combined bounds."""
    async with grafy() as (client, workspace_id):
        matched = await client.artifacts.geo_query(
            workspace_id, artifact_id, match_rows
        )
    return dump(matched)


async def read_table_cell(
    artifact_id: UUID, row_index: Annotated[int, Field(ge=0)], column_id: str
) -> dict[str, Any]:
    """One whole table cell, for a value `read_table_page` truncated."""
    async with grafy() as (client, workspace_id):
        cell = await client.artifacts.table_cell(
            workspace_id, artifact_id, row_index=row_index, column_id=column_id
        )
    return dump(cell)


async def get_image_info(
    artifact_id: UUID, page: Annotated[int, Field(ge=0)] = 0
) -> dict[str, Any]:
    """An image artifact's size, pages and format."""
    async with grafy() as (client, workspace_id):
        return dump(
            await client.artifacts.image_info(workspace_id, artifact_id, page=page)
        )


TOOLS: Final = (
    tool(list_authorable_artifact_types, READ, tags={"artifacts", "authoring"}),
    tool(create_artifact, EDIT, tags={"artifacts", "authoring"}),
    tool(read_artifact_text, READ, tags={"artifacts"}),
    tool(get_table_schema, READ, tags={"artifacts", "tables"}),
    tool(read_table_page, READ, tags={"artifacts", "tables"}),
    tool(query_table, READ, tags={"artifacts", "tables"}),
    tool(get_geo_render, READ, tags={"artifacts", "geo"}),
    tool(query_geo_features, READ, tags={"artifacts", "geo"}),
    tool(read_table_cell, READ, tags={"artifacts", "tables"}),
    tool(get_image_info, READ, tags={"artifacts", "images"}),
)
