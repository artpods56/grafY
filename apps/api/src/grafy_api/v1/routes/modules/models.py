from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field

from grafy_core.domain.module_library import (
    Module,
    ModulePublicationState,
    ModuleRelease,
)
from grafy_core.domain.modules import GraphModuleDefinition, GraphModulePort

from grafy_api.v1.models import ApiResponse, ArtifactTypeKeyResponse


class ModulePortResponse(ApiResponse):
    name: str
    direction: str
    artifact_type: ArtifactTypeKeyResponse
    required: bool
    description: str | None = None

    @classmethod
    def from_port(cls, port: GraphModulePort, *, direction: str) -> Self:
        return cls(
            name=port.name,
            direction=direction,
            artifact_type=ArtifactTypeKeyResponse.from_key(port.artifact_type),
            required=port.required,
            description=port.description,
        )


class ModuleReleaseResponse(ApiResponse):
    revision: int = Field(ge=1, strict=True)
    source_graph_id: UUID
    published_at: datetime
    is_current_library_release: bool = False

    @classmethod
    def from_release(
        cls,
        release: ModuleRelease,
        *,
        current_library_release: int | None,
    ) -> Self:
        return cls(
            revision=release.revision,
            source_graph_id=release.source_graph_id,
            published_at=release.published_at,
            is_current_library_release=release.revision == current_library_release,
        )


class ModuleResponse(ApiResponse):
    id: UUID
    workspace_id: UUID
    source_graph_id: UUID
    name: str
    description: str | None = None
    publication_state: ModulePublicationState
    current_library_release: int | None = Field(default=None, ge=1)
    created_at: datetime
    updated_at: datetime
    releases: list[ModuleReleaseResponse] = Field(default_factory=list)
    inputs: list[ModulePortResponse] = Field(default_factory=list)
    outputs: list[ModulePortResponse] = Field(default_factory=list)

    @classmethod
    def from_module(
        cls,
        module: Module,
        *,
        releases: list[ModuleRelease] | None = None,
        definition: GraphModuleDefinition | None = None,
    ) -> Self:
        release_rows = releases or []
        return cls(
            id=module.id,
            workspace_id=module.workspace_id,
            source_graph_id=module.source_graph_id,
            name=module.name,
            description=module.description,
            publication_state=module.publication_state,
            current_library_release=module.current_library_release,
            created_at=module.created_at,
            updated_at=module.updated_at,
            releases=[
                ModuleReleaseResponse.from_release(
                    release,
                    current_library_release=module.current_library_release,
                )
                for release in release_rows
            ],
            inputs=[
                ModulePortResponse.from_port(port, direction="input")
                for port in (definition.input_ports if definition is not None else ())
            ],
            outputs=[
                ModulePortResponse.from_port(port, direction="output")
                for port in (definition.output_ports if definition is not None else ())
            ],
        )


class ModuleListResponse(ApiResponse):
    modules: list[ModuleResponse]


class PublishModuleReleaseRequest(ApiResponse):
    source_graph_id: UUID
    revision: int | None = Field(default=None, ge=1, strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)


__all__ = [
    "ModuleListResponse",
    "ModuleReleaseResponse",
    "ModuleResponse",
    "PublishModuleReleaseRequest",
]
