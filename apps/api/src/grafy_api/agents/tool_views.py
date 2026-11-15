import json
from collections.abc import Callable, Mapping
from uuid import UUID
from grafy_api.agents.toolbox import (
    ModelViews,
    json_media_type,
)
from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
)
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.plugins import PluginRegistry
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.table_storage import load_table_page


MAX_VIEW_CHARS = 20_000


TABLE_VIEW_ROWS = 20


SEQUENCE_VIEW_ITEMS = 5


class ArtifactModelViews(ModelViews):
    """Outputs rendered as text a model can read."""

    def __init__(
        self,
        *,
        registry: PluginRegistry,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
        storage: FileStoragePort,
        workspace_id: UUID,
    ) -> None:
        self._titles = {spec.key: spec.title for spec in registry.artifact_types}
        self._unit_of_work_factory = unit_of_work_factory
        self._storage = storage
        self._workspace_id = workspace_id

    async def render(self, *, outputs: Mapping[str, ArtifactOutputValue]) -> str:
        sections: list[str] = []
        for port, value in outputs.items():
            if isinstance(value, ArtifactRefSequence):
                shown: list[str] = []
                for ref in value.item_refs[:SEQUENCE_VIEW_ITEMS]:
                    async with self._unit_of_work_factory() as uow:
                        artifact = await uow.artifacts.get(
                            self._workspace_id, ref.artifact_id
                        )
                    if artifact is None:
                        rendered = (
                            f"Artifact id: {ref.artifact_id} ({ref.artifact_type})\n"
                            f"[{ref.artifact_type} artifact that is no longer available]"
                        )
                    else:
                        if artifact.artifact_type.startswith("table."):
                            page = await load_table_page(
                                artifact, self._storage, offset=0, limit=TABLE_VIEW_ROWS
                            )
                            header = [
                                column.id
                                if column.title in ("", column.id)
                                else f"{column.id} ({column.title})"
                                for column in page.columns
                            ]
                            lines = [
                                " | ".join(header),
                                " | ".join("---" for _ in header),
                            ]
                            for row in page.rows:
                                lines.append(
                                    " | ".join(
                                        str(row.get(column.id, ""))
                                        for column in page.columns
                                    )
                                )
                            shown_rows = len(page.rows)
                            if page.total_rows > shown_rows:
                                lines.append(
                                    f"(showing {shown_rows} of {page.total_rows} rows)"
                                )
                            body = _clip("\n".join(lines))
                        else:
                            payload = artifact.inline_payload
                            if isinstance(payload, dict):
                                scalar = None
                                if len(payload) == 1:
                                    field, found = next(iter(payload.items()))
                                    if field in {"value", "markdown", "text"}:
                                        if isinstance(found, (str, int, float, bool)):
                                            scalar = str(found)
                                if scalar is not None:
                                    body = _clip(scalar)
                                else:
                                    body = _clip(
                                        json.dumps(
                                            payload,
                                            ensure_ascii=False,
                                            sort_keys=True,
                                            separators=(",", ":"),
                                        )
                                    )
                            elif json_media_type(artifact.content_type):
                                if (
                                    artifact.bucket is None
                                    or artifact.object_key is None
                                ):
                                    body = "[JSON with nothing stored]"
                                else:
                                    limit = MAX_VIEW_CHARS * 4
                                    stream = await self._storage.load(
                                        bucket=artifact.bucket, path=artifact.object_key
                                    )
                                    try:
                                        raw = stream.read(limit + 1)
                                    finally:
                                        stream.close()
                                    truncated = len(raw) > limit
                                    text = raw[:limit].decode("utf-8", errors="replace")
                                    readable = True
                                    if not truncated:
                                        try:
                                            parsed = json.loads(text)
                                        except json.JSONDecodeError:
                                            readable = False
                                        else:
                                            text = json.dumps(
                                                parsed,
                                                ensure_ascii=False,
                                                sort_keys=True,
                                                separators=(",", ":"),
                                            )
                                    if readable:
                                        body = _clip(text)
                                        if truncated and "more characters" not in body:
                                            body += "\n... [the stored JSON is longer than what was read]"
                                    else:
                                        body = "[JSON that could not be read]"
                            else:
                                title = self._titles.get(
                                    ArtifactTypeKey(
                                        artifact.artifact_type, artifact.schema_version
                                    ),
                                    artifact.artifact_type,
                                )
                                size = (
                                    f", {artifact.byte_size} bytes"
                                    if artifact.byte_size
                                    else ""
                                )
                                body = (
                                    f"[{title}{size}; its content is not shown to you]"
                                )
                        rendered = f"Artifact id: {artifact.id} ({artifact.artifact_type})\n{body}"
                    shown.append(rendered)
                more = len(value.item_refs) - len(shown)
                lines = [f"{len(value.item_refs)} items:"]
                lines += ["- " + text.replace("\n", "\n  ") for text in shown]
                if more > 0:
                    lines.append(f"- ... and {more} more not shown")
                rendered = "\n".join(lines)
            else:
                ref = value
                async with self._unit_of_work_factory() as uow:
                    artifact = await uow.artifacts.get(
                        self._workspace_id, ref.artifact_id
                    )
                if artifact is None:
                    rendered = (
                        f"Artifact id: {ref.artifact_id} ({ref.artifact_type})\n"
                        f"[{ref.artifact_type} artifact that is no longer available]"
                    )
                else:
                    if artifact.artifact_type.startswith("table."):
                        page = await load_table_page(
                            artifact, self._storage, offset=0, limit=TABLE_VIEW_ROWS
                        )
                        header = [
                            column.id
                            if column.title in ("", column.id)
                            else f"{column.id} ({column.title})"
                            for column in page.columns
                        ]
                        lines = [" | ".join(header), " | ".join("---" for _ in header)]
                        for row in page.rows:
                            lines.append(
                                " | ".join(
                                    str(row.get(column.id, ""))
                                    for column in page.columns
                                )
                            )
                        shown_rows = len(page.rows)
                        if page.total_rows > shown_rows:
                            lines.append(
                                f"(showing {shown_rows} of {page.total_rows} rows)"
                            )
                        body = _clip("\n".join(lines))
                    else:
                        payload = artifact.inline_payload
                        if isinstance(payload, dict):
                            scalar = None
                            if len(payload) == 1:
                                field, found = next(iter(payload.items()))
                                if field in {"value", "markdown", "text"}:
                                    if isinstance(found, (str, int, float, bool)):
                                        scalar = str(found)
                            if scalar is not None:
                                body = _clip(scalar)
                            else:
                                body = _clip(
                                    json.dumps(
                                        payload,
                                        ensure_ascii=False,
                                        sort_keys=True,
                                        separators=(",", ":"),
                                    )
                                )
                        elif json_media_type(artifact.content_type):
                            if artifact.bucket is None or artifact.object_key is None:
                                body = "[JSON with nothing stored]"
                            else:
                                limit = MAX_VIEW_CHARS * 4
                                stream = await self._storage.load(
                                    bucket=artifact.bucket, path=artifact.object_key
                                )
                                try:
                                    raw = stream.read(limit + 1)
                                finally:
                                    stream.close()
                                truncated = len(raw) > limit
                                text = raw[:limit].decode("utf-8", errors="replace")
                                readable = True
                                if not truncated:
                                    try:
                                        parsed = json.loads(text)
                                    except json.JSONDecodeError:
                                        readable = False
                                    else:
                                        text = json.dumps(
                                            parsed,
                                            ensure_ascii=False,
                                            sort_keys=True,
                                            separators=(",", ":"),
                                        )
                                if readable:
                                    body = _clip(text)
                                    if truncated and "more characters" not in body:
                                        body += "\n... [the stored JSON is longer than what was read]"
                                else:
                                    body = "[JSON that could not be read]"
                        else:
                            title = self._titles.get(
                                ArtifactTypeKey(
                                    artifact.artifact_type, artifact.schema_version
                                ),
                                artifact.artifact_type,
                            )
                            size = (
                                f", {artifact.byte_size} bytes"
                                if artifact.byte_size
                                else ""
                            )
                            body = f"[{title}{size}; its content is not shown to you]"
                    rendered = (
                        f"Artifact id: {artifact.id} ({artifact.artifact_type})\n{body}"
                    )
            sections.append(f"{port}:\n{rendered}")
        return "\n\n".join(sections) if sections else "The tool returned nothing."

    async def render_library_item(
        self, artifact_id: UUID
    ) -> tuple[str, ArtifactRef | None]:
        """One Library artifact by id, as a model reads it, and the ref when it remains."""

        async with self._unit_of_work_factory() as uow:
            artifact = await uow.artifacts.get(self._workspace_id, artifact_id)
        if artifact is None:
            return (
                f"Artifact id: {artifact_id}\n[this Library item is no longer available]",
                None,
            )
        if artifact.artifact_type.startswith("table."):
            page = await load_table_page(
                artifact, self._storage, offset=0, limit=TABLE_VIEW_ROWS
            )
            header = [
                column.id
                if column.title in ("", column.id)
                else f"{column.id} ({column.title})"
                for column in page.columns
            ]
            lines = [" | ".join(header), " | ".join("---" for _ in header)]
            for row in page.rows:
                lines.append(
                    " | ".join(str(row.get(column.id, "")) for column in page.columns)
                )
            shown = len(page.rows)
            if page.total_rows > shown:
                lines.append(f"(showing {shown} of {page.total_rows} rows)")
            body = _clip("\n".join(lines))
        else:
            payload = artifact.inline_payload
            if isinstance(payload, dict):
                scalar = None
                if len(payload) == 1:
                    field, found = next(iter(payload.items()))
                    if field in {"value", "markdown", "text"}:
                        if isinstance(found, (str, int, float, bool)):
                            scalar = str(found)
                if scalar is not None:
                    body = _clip(scalar)
                else:
                    body = _clip(
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
            elif json_media_type(artifact.content_type):
                if artifact.bucket is None or artifact.object_key is None:
                    body = "[JSON with nothing stored]"
                else:
                    limit = MAX_VIEW_CHARS * 4
                    stream = await self._storage.load(
                        bucket=artifact.bucket, path=artifact.object_key
                    )
                    try:
                        raw = stream.read(limit + 1)
                    finally:
                        stream.close()
                    truncated = len(raw) > limit
                    text = raw[:limit].decode("utf-8", errors="replace")
                    readable = True
                    if not truncated:
                        try:
                            parsed = json.loads(text)
                        except json.JSONDecodeError:
                            readable = False
                        else:
                            text = json.dumps(
                                parsed,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                    if readable:
                        body = _clip(text)
                        if truncated and "more characters" not in body:
                            body += (
                                "\n... [the stored JSON is longer than what was read]"
                            )
                    else:
                        body = "[JSON that could not be read]"
            else:
                title = self._titles.get(
                    ArtifactTypeKey(artifact.artifact_type, artifact.schema_version),
                    artifact.artifact_type,
                )
                size = f", {artifact.byte_size} bytes" if artifact.byte_size else ""
                body = f"[{title}{size}; its content is not shown to you]"
        rendered = f"Artifact id: {artifact.id} ({artifact.artifact_type})\n{body}"
        return rendered, artifact.ref()


def _clip(text: str) -> str:
    if len(text) <= MAX_VIEW_CHARS:
        return text
    return (
        text[:MAX_VIEW_CHARS] + f"\n... [{len(text) - MAX_VIEW_CHARS} more characters]"
    )
