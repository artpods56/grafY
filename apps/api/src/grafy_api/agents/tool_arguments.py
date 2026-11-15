import json
from collections.abc import Callable, Mapping
from hashlib import sha256
from typing import cast
from uuid import UUID, uuid5
from grafy_api.agents.toolbox import (
    ArgumentArtifacts,
    JsonType,
)
from grafy_core.artifact_contracts import HTML_PAGE, HtmlPage, HtmlPageSource
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactTypeKey,
)
from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.plugins import PluginRegistry
from grafy_core.ports.artifacts import UnitOfWorkPort


ARGUMENT_ARTIFACT_NAMESPACE = UUID("6d7f4d10-1a2b-4c3d-8e4f-5a6b7c8d9e01")


class ContentAddressedArguments(ArgumentArtifacts):
    """Model-written values as inline artifacts, one artifact per distinct content."""

    def __init__(
        self,
        *,
        registry: PluginRegistry,
        unit_of_work_factory: Callable[[], UnitOfWorkPort],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._json_types: dict[ArtifactTypeKey, JsonType] = {}
        for spec in registry.artifact_types:
            if spec.materialized_json_type not in ("string", "integer"):
                continue
            properties = spec.payload_schema.get("properties")
            if not isinstance(properties, dict) or set(properties) != {"value"}:
                continue
            self._json_types[spec.key] = (
                "string" if spec.materialized_json_type == "string" else "integer"
            )

    def json_type(self, key: ArtifactTypeKey) -> JsonType | None:
        return self._json_types.get(key)

    async def ref_for(
        self,
        *,
        workspace_id: UUID,
        key: ArtifactTypeKey,
        value: str | int,
    ) -> ArtifactRef:
        payload: dict[str, object] = {"value": value}
        content = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        digest = sha256(content).hexdigest()
        artifact_id = uuid5(
            ARGUMENT_ARTIFACT_NAMESPACE,
            f"{workspace_id}:{key.id}@{key.schema_version}:{digest}",
        )
        async with self._unit_of_work_factory() as unit_of_work:
            existing = await unit_of_work.artifacts.get(workspace_id, artifact_id)
            if existing is not None:
                return existing.ref()
            artifact = ArtifactObject(
                id=artifact_id,
                workspace_id=workspace_id,
                artifact_type=key.id,
                schema_version=key.schema_version,
                content_type="application/json",
                storage_backend="inline",
                inline_payload=payload,
                byte_size=len(content),
                sha256=digest,
                metadata={"written_by": "agent_tool_call"},
            )
            try:
                await unit_of_work.artifacts.add(artifact)
                await unit_of_work.commit()
            except ObjectAlreadyExistsError:
                # Two identical calls wrote at once. The id is the content's, so the one
                # that lost the race holds exactly what the winner stored.
                await unit_of_work.rollback()
        return artifact.ref()

    async def page_for(
        self,
        *,
        workspace_id: UUID,
        html: str,
        sources: Mapping[str, ArtifactRef],
    ) -> ArtifactRef:
        page = HtmlPage(
            html=html,
            sources={
                name: HtmlPageSource(
                    artifact_id=ref.artifact_id,
                    artifact_type=ref.artifact_type,
                    schema_version=ref.schema_version,
                )
                for name, ref in sources.items()
            },
        )
        key = HTML_PAGE.key
        payload = cast(dict[str, object], page.model_dump(mode="json"))
        content = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        digest = sha256(content).hexdigest()
        artifact_id = uuid5(
            ARGUMENT_ARTIFACT_NAMESPACE,
            f"{workspace_id}:{key.id}@{key.schema_version}:{digest}",
        )
        async with self._unit_of_work_factory() as unit_of_work:
            existing = await unit_of_work.artifacts.get(workspace_id, artifact_id)
            if existing is not None:
                return existing.ref()
            artifact = ArtifactObject(
                id=artifact_id,
                workspace_id=workspace_id,
                artifact_type=key.id,
                schema_version=key.schema_version,
                content_type="application/json",
                storage_backend="inline",
                inline_payload=payload,
                byte_size=len(content),
                sha256=digest,
                metadata={"written_by": "agent_tool_call"},
            )
            try:
                await unit_of_work.artifacts.add(artifact)
                await unit_of_work.commit()
            except ObjectAlreadyExistsError:
                # Two identical calls wrote at once. The id is the content's, so the one
                # that lost the race holds exactly what the winner stored.
                await unit_of_work.rollback()
        return artifact.ref()

    async def get_artifact(
        self, *, workspace_id: UUID, artifact_id: UUID
    ) -> ArtifactObject | None:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.artifacts.get(workspace_id, artifact_id)
