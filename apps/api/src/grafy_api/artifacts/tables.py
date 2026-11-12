import json
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID, uuid5

from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.artifacts import ArtifactObject, ArtifactRef, JsonObject
from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.table_storage import load_table_artifact, load_table_page
from grafy_core.table_contracts import TABLE_DATA, TablePage, TableValue

from grafy_api.services.errors import (
    ArtifactContentUnavailableError,
    WorkbenchOperationError,
)

from grafy_api.artifacts.models import (
    TableExactMatchGroup,
    interaction_values_equal,
)


TABLE_INTERACTION_ROW_LIMIT = 250_000
_TABLE_CELL_ARTIFACT_NAMESPACE = UUID("3f0c1d7e-9a64-4b52-8c1e-7d2a6e5f4b10")


@dataclass(frozen=True, slots=True)
class TableQueryPage:
    page: TablePage
    row_indices: list[int]
    highlighted_row_indices: list[int]


def _table_row_matches_group(
    row: dict[str, TableValue],
    group: TableExactMatchGroup,
) -> bool:
    return any(
        all(
            interaction_values_equal(row[field_name], expected)
            for field_name, expected in candidate.values.items()
        )
        for candidate in group.rows
    )


class ArtifactTableService:
    def __init__(self, uow: UnitOfWorkPort, storage: FileStoragePort) -> None:
        self._uow = uow
        self._storage = storage

    async def get(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactObject | None:
        async with self._uow as uow:
            return await uow.artifacts.get(workspace_id, artifact_id)

    async def load_table_page(
        self,
        artifact: ArtifactObject,
        *,
        offset: int,
        limit: int,
    ) -> TablePage:
        if (
            artifact.artifact_type != TABLE_DATA.key.id
            or artifact.schema_version != TABLE_DATA.key.schema_version
        ):
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} is not a table.data@1 artifact"
            )
        try:
            return await load_table_page(
                artifact,
                self._storage,
                offset=offset,
                limit=limit,
            )
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not load table page at offset {offset} for artifact "
                f"{artifact.id}"
            ) from exc

    async def load_table_cell(
        self,
        artifact: ArtifactObject,
        *,
        row_index: int,
        column_id: str,
    ) -> TableValue:
        page = await self.load_table_page(artifact, offset=row_index, limit=1)
        if row_index >= page.total_rows:
            raise WorkbenchOperationError(
                f"Table artifact {artifact.id} has no row {row_index}"
            )
        column_ids = {column.id for column in page.columns}
        if column_id not in column_ids:
            raise WorkbenchOperationError(
                f"Table artifact {artifact.id} has no column {column_id!r}"
            )
        return page.rows[0][column_id]

    async def text_artifacts_for_column(
        self,
        artifact: ArtifactObject,
        *,
        column_id: str,
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[int, ArtifactRef | None]], int]:
        """Each row's text in one column as an artifact of its own, for dragging out.

        A row of a table is not an artifact, and a drag has to carry one from its very
        first moment, so the rows a person is about to choose from are made ready as a
        page. The id comes from the source, the cell and its content: asking again makes
        nothing new, and the artifact can say truthfully which table it was taken from.
        """
        page = await self.load_table_page(artifact, offset=offset, limit=limit)
        if column_id not in {column.id for column in page.columns}:
            raise WorkbenchOperationError(
                f"Table artifact {artifact.id} has no column {column_id!r}"
            )
        cells: list[tuple[int, ArtifactObject | None]] = []
        for index, row in enumerate(page.rows):
            value = row.get(column_id)
            cell: ArtifactObject | None = None
            if isinstance(value, str) and value:
                payload: JsonObject = {"value": value}
                content = json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                digest = sha256(content).hexdigest()
                cell = ArtifactObject(
                    id=uuid5(
                        _TABLE_CELL_ARTIFACT_NAMESPACE,
                        f"{artifact.id}:{offset + index}:{column_id}:{digest}",
                    ),
                    workspace_id=artifact.workspace_id,
                    artifact_type=TEXT_VALUE.key.id,
                    schema_version=TEXT_VALUE.key.schema_version,
                    content_type="application/json",
                    storage_backend="inline",
                    inline_payload=payload,
                    byte_size=len(content),
                    sha256=digest,
                    metadata={
                        "written_by": "table_cell",
                        "source_artifact_id": str(artifact.id),
                        "row_index": offset + index,
                        "column_id": column_id,
                    },
                )
            cells.append((offset + index, cell))
        wanted = {cell.id: cell for _, cell in cells if cell is not None}
        # Two people opening the same list race to write the same rows. The loser's
        # rows are already there, identical, so one look again settles it.
        for last_attempt in (False, True):
            async with self._uow as uow:
                existing = await uow.artifacts.get_many(
                    artifact.workspace_id, list(wanted)
                )
                try:
                    for cell_id, cell in wanted.items():
                        if cell_id not in existing:
                            await uow.artifacts.add(cell)
                    await uow.commit()
                    break
                except ObjectAlreadyExistsError:
                    await uow.rollback()
                    if last_attempt:
                        raise
        return (
            [(index, None if cell is None else cell.ref()) for index, cell in cells],
            page.total_rows,
        )

    async def load_table_query_page(
        self,
        artifact: ArtifactObject,
        *,
        filter_groups: list[TableExactMatchGroup],
        highlight_groups: list[TableExactMatchGroup],
        offset: int,
        limit: int,
    ) -> TableQueryPage:
        if (
            artifact.artifact_type != TABLE_DATA.key.id
            or artifact.schema_version != TABLE_DATA.key.schema_version
        ):
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} is not a table.data@1 artifact"
            )
        row_count = artifact.metadata.get("row_count")
        if (
            not isinstance(row_count, int)
            or isinstance(row_count, bool)
            or row_count < 0
        ):
            raise ArtifactContentUnavailableError(
                f"Table artifact {artifact.id} has invalid row_count metadata"
            )
        if row_count > TABLE_INTERACTION_ROW_LIMIT:
            raise WorkbenchOperationError(
                f"Linked table filtering supports at most "
                f"{TABLE_INTERACTION_ROW_LIMIT} rows; artifact {artifact.id} "
                f"contains {row_count}"
            )
        try:
            table = await load_table_artifact(artifact, self._storage)
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not load table artifact {artifact.id} for linked filtering"
            ) from exc

        column_ids = {column.id for column in table.columns}
        requested_fields = {
            field_name
            for group in [*filter_groups, *highlight_groups]
            for candidate in group.rows
            for field_name in candidate.values
        }
        missing_fields = sorted(requested_fields - column_ids)
        if missing_fields:
            raise WorkbenchOperationError(
                f"Table artifact {artifact.id} has no linked field(s) "
                f"{missing_fields!r}"
            )

        matched: list[tuple[int, dict[str, TableValue]]] = []
        highlighted_indices: set[int] = set()
        for row_index, row in enumerate(table.rows):
            if filter_groups and not all(
                _table_row_matches_group(row, group) for group in filter_groups
            ):
                continue
            matched.append((row_index, row))
            if highlight_groups and any(
                _table_row_matches_group(row, group) for group in highlight_groups
            ):
                highlighted_indices.add(row_index)

        effective_offset = min(offset, len(matched))
        selected = matched[effective_offset : effective_offset + limit]
        selected_indices = [row_index for row_index, _ in selected]
        return TableQueryPage(
            page=TablePage(
                columns=table.columns,
                rows=[row for _, row in selected],
                offset=effective_offset,
                total_rows=len(matched),
            ),
            row_indices=selected_indices,
            highlighted_row_indices=[
                row_index
                for row_index in selected_indices
                if row_index in highlighted_indices
            ],
        )


__all__ = [
    "ArtifactTableService",
    "TABLE_INTERACTION_ROW_LIMIT",
    "TableQueryPage",
]
