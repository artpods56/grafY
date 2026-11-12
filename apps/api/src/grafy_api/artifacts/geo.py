from typing import cast
from uuid import UUID

from grafy_core.artifact_collections import load_json_collections_page
from grafy_core.artifacts import ArtifactObject, ArtifactRef
from grafy_core.egress import validated_public_destination
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.spatial_contracts import GeoVectorStyle as StoredGeoVectorStyle

from grafy_api.artifact_availability import ArtifactAvailability, ArtifactReferenceError
from grafy_api.services.errors import (
    ArtifactContentUnavailableError,
    WorkbenchOperationError,
)

from grafy_api.artifacts.models import (
    ArtifactExactMatchRow,
    GeoArtifactRefPayload,
    GeoBounds,
    GeoCategorizedPointStyle,
    GeoFeatureQueryResponse,
    GeoMapDocumentPayload,
    GeoMapLayerPayload,
    GeoPropertyFieldResponse,
    GeoRasterProjectionMetadata,
    GeoRasterRenderSourceResponse,
    GeoRasterStyle,
    GeoRenderLayerResponse,
    GeoRenderResponse,
    GeoVectorProjectionMetadata,
    GeoVectorRenderSourceResponse,
    GeoVectorStyle,
    interaction_values_equal,
)


GEO_FEATURE_COLLECTION_ARTIFACT_TYPE = "geo.feature_collection"
GEO_RASTER_SCAN_ARTIFACT_TYPE = "geo.raster_scan"
GEO_MAP_LAYER_ARTIFACT_TYPE = "geo.map_layer"
GEO_MAP_DOCUMENT_ARTIFACT_TYPE = "geo.map_document"
GEO_INTERACTION_FEATURE_LIMIT = 250_000


def _coordinate_bounds(coordinates: object) -> GeoBounds | None:
    if not isinstance(coordinates, list):
        return None
    values = cast(list[object], coordinates)
    if (
        len(values) >= 2
        and isinstance(values[0], int | float)
        and not isinstance(values[0], bool)
        and isinstance(values[1], int | float)
        and not isinstance(values[1], bool)
    ):
        longitude = float(values[0])
        latitude = float(values[1])
        return (longitude, latitude, longitude, latitude)
    nested = [
        bounds for value in values if (bounds := _coordinate_bounds(value)) is not None
    ]
    return _bounds_union(nested)


def _geometry_bounds(geometry: object) -> GeoBounds | None:
    if not isinstance(geometry, dict):
        return None
    typed_geometry = cast(dict[str, object], geometry)
    if typed_geometry.get("type") == "GeometryCollection":
        geometries = typed_geometry.get("geometries")
        if not isinstance(geometries, list):
            return None
        typed_geometries = cast(list[object], geometries)
        return _bounds_union(
            [
                bounds
                for value in typed_geometries
                if (bounds := _geometry_bounds(value)) is not None
            ]
        )
    return _coordinate_bounds(typed_geometry.get("coordinates"))


def _bounds_union(
    bounds_values: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float] | None:
    if not bounds_values:
        return None
    return (
        min(bounds[0] for bounds in bounds_values),
        min(bounds[1] for bounds in bounds_values),
        max(bounds[2] for bounds in bounds_values),
        max(bounds[3] for bounds in bounds_values),
    )


def feature_count(artifact: ArtifactObject) -> int:
    count = artifact.metadata.get("feature_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ArtifactContentUnavailableError(
            f"Feature collection artifact {artifact.id} has invalid "
            "feature_count metadata"
        )
    return count


def source_name(artifact: ArtifactObject) -> str:
    name = artifact.metadata.get("source_name")
    if not isinstance(name, str) or name.strip() == "":
        raise ArtifactContentUnavailableError(
            f"Geo source artifact {artifact.id} has invalid source_name metadata"
        )
    return name


async def resolve_exact_artifacts(
    availability: ArtifactAvailability,
    refs: list[GeoArtifactRefPayload],
    *,
    expected_type: str,
    context: str,
    workspace_id: UUID,
) -> list[ArtifactObject]:
    for ref in refs:
        if ref.artifact_type != expected_type or ref.schema_version != 1:
            raise ArtifactContentUnavailableError(
                f"{context} references {ref.artifact_type}@{ref.schema_version}, "
                f"expected {expected_type}@1"
            )
    exact_refs = [
        ArtifactRef(
            artifact_id=ref.artifact_id,
            artifact_type=ref.artifact_type,
            schema_version=ref.schema_version,
            content_hash=ref.content_hash,
        )
        for ref in refs
    ]
    batch = await availability.load(workspace_id, exact_refs)
    try:
        return list(batch.resolve_refs(exact_refs, context=context))
    except ArtifactReferenceError as exc:
        if exc.reason == "missing":
            raise ArtifactContentUnavailableError(str(exc)) from exc
        raise ArtifactContentUnavailableError(
            f"{context} reference for artifact {exc.reference.artifact_id} does not "
            "match the repository artifact"
        ) from exc


class ArtifactGeoService:
    """Builds map render descriptors and linked feature queries."""

    def __init__(
        self,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
        *,
        availability: ArtifactAvailability,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._availability = availability

    async def get(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactObject | None:
        async with self._uow as uow:
            return await uow.artifacts.get(workspace_id, artifact_id)

    async def query_geo_features(
        self,
        artifact: ArtifactObject,
        rows: list[ArtifactExactMatchRow],
        *,
        workspace_id: UUID,
    ) -> GeoFeatureQueryResponse:
        descriptor = await self.load_geo_render(artifact, workspace_id=workspace_id)
        source_ids = list(
            dict.fromkeys(
                layer.source.artifact_id
                for layer in descriptor.layers
                if layer.source.kind == "vector"
            )
        )
        if not source_ids:
            return GeoFeatureQueryResponse(
                artifact_id=artifact.id,
                bounds=None,
                matched_feature_count=0,
                source_artifact_ids=[],
            )
        async with self._uow as uow:
            source_artifacts = await uow.artifacts.get_many(
                workspace_id,
                source_ids,
            )
        total_features = 0
        ordered_sources: list[ArtifactObject] = []
        for source_id in source_ids:
            source_artifact = source_artifacts.get(source_id)
            if (
                source_artifact is None
                or source_artifact.artifact_type != GEO_FEATURE_COLLECTION_ARTIFACT_TYPE
                or source_artifact.schema_version != 1
            ):
                raise ArtifactContentUnavailableError(
                    f"Geo render artifact {artifact.id} references invalid "
                    f"feature source {source_id}"
                )
            total_features += feature_count(source_artifact)
            ordered_sources.append(source_artifact)
        if total_features > GEO_INTERACTION_FEATURE_LIMIT:
            raise WorkbenchOperationError(
                f"Linked map focus supports at most "
                f"{GEO_INTERACTION_FEATURE_LIMIT} source features; artifact "
                f"{artifact.id} resolves to {total_features}"
            )

        matched_bounds: list[GeoBounds] = []
        matched_feature_count = 0
        try:
            for source_artifact in ordered_sources:
                page = await load_json_collections_page(
                    source_artifact,
                    self._storage,
                    offset=0,
                    limit=max(1, feature_count(source_artifact)),
                )
                if len(page.collections) != 1 or page.collections[0].id != "features":
                    raise ValueError(
                        "Geo feature collection manifest must contain one "
                        "'features' collection"
                    )
                for feature in page.collections[0].items:
                    properties = feature.get("properties")
                    typed_properties = (
                        cast(dict[str, object], properties)
                        if isinstance(properties, dict)
                        else None
                    )
                    if typed_properties is None or not any(
                        all(
                            field_name in typed_properties
                            and interaction_values_equal(
                                typed_properties[field_name], expected
                            )
                            for field_name, expected in row.values.items()
                        )
                        for row in rows
                    ):
                        continue
                    matched_feature_count += 1
                    bounds = _geometry_bounds(feature.get("geometry"))
                    if bounds is not None:
                        matched_bounds.append(bounds)
        except (ArtifactContentUnavailableError, WorkbenchOperationError):
            raise
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not query linked features for geo artifact {artifact.id}"
            ) from exc
        return GeoFeatureQueryResponse(
            artifact_id=artifact.id,
            bounds=_bounds_union(matched_bounds),
            matched_feature_count=matched_feature_count,
            source_artifact_ids=source_ids,
        )

    async def load_geo_render(
        self,
        artifact: ArtifactObject,
        *,
        workspace_id: UUID,
    ) -> GeoRenderResponse:
        if artifact.schema_version != 1:
            raise WorkbenchOperationError(
                f"Artifact {artifact.id} is not a supported geo artifact"
            )
        try:
            if artifact.artifact_type == GEO_FEATURE_COLLECTION_ARTIFACT_TYPE:
                layer = self._feature_render_layer(
                    artifact,
                    layer_id=str(artifact.id),
                    title=source_name(artifact),
                    visible=True,
                    opacity=1.0,
                    min_zoom=0,
                    max_zoom=22,
                    style=GeoVectorStyle.model_validate(StoredGeoVectorStyle()),
                )
                layers = [] if layer is None else [layer]
                return GeoRenderResponse(
                    artifact_id=artifact.id,
                    kind="feature_collection",
                    basemap="openstreetmap",
                    initial_bounds=None if layer is None else layer.source.bounds,
                    layers=layers,
                )
            if artifact.artifact_type == GEO_RASTER_SCAN_ARTIFACT_TYPE:
                projection = GeoRasterProjectionMetadata.model_validate(
                    artifact.metadata.get("raster_projection")
                )
                raster_layer = GeoRenderLayerResponse(
                    id=str(artifact.id),
                    title=source_name(artifact),
                    visible=True,
                    opacity=1.0,
                    min_zoom=0,
                    max_zoom=22,
                    source=GeoRasterRenderSourceResponse(
                        artifact_id=artifact.id,
                        tilejson_url=(
                            f"/v1/workspaces/{artifact.workspace_id}/artifacts/"
                            f"{artifact.id}/geo/raster/tilejson.json"
                        ),
                        bounds=projection.bounds,
                    ),
                    style=GeoRasterStyle.default(),
                )
                return GeoRenderResponse(
                    artifact_id=artifact.id,
                    kind="raster_scan",
                    basemap="openstreetmap",
                    initial_bounds=raster_layer.source.bounds,
                    layers=[raster_layer],
                )
            if artifact.artifact_type == GEO_MAP_LAYER_ARTIFACT_TYPE:
                layer = await self._resolve_render_layer(
                    artifact,
                    workspace_id=workspace_id,
                )
                layers = [] if layer is None else [layer]
                return GeoRenderResponse(
                    artifact_id=artifact.id,
                    kind="map_layer",
                    basemap="openstreetmap",
                    initial_bounds=None if layer is None else layer.source.bounds,
                    layers=layers,
                )
            if artifact.artifact_type == GEO_MAP_DOCUMENT_ARTIFACT_TYPE:
                document = GeoMapDocumentPayload.model_validate(artifact.inline_payload)
                layer_artifacts = await resolve_exact_artifacts(
                    self._availability,
                    document.layers,
                    expected_type=GEO_MAP_LAYER_ARTIFACT_TYPE,
                    context=f"Map document artifact {artifact.id}",
                    workspace_id=workspace_id,
                )
                document_layers: list[GeoRenderLayerResponse] = []
                for layer_artifact in layer_artifacts:
                    resolved = await self._resolve_render_layer(
                        layer_artifact,
                        workspace_id=workspace_id,
                    )
                    if resolved is not None:
                        document_layers.append(resolved)
                effective_bounds = document.initial_bounds
                if effective_bounds is None:
                    layer_bounds = [
                        resolved.source.bounds
                        for resolved in document_layers
                        if resolved.source.bounds is not None
                    ]
                    effective_bounds = _bounds_union(layer_bounds)
                return GeoRenderResponse(
                    artifact_id=artifact.id,
                    kind="map_document",
                    basemap=document.basemap,
                    initial_bounds=effective_bounds,
                    layers=document_layers,
                )
        except (ArtifactContentUnavailableError, WorkbenchOperationError):
            raise
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not build render descriptor for artifact {artifact.id}"
            ) from exc
        raise WorkbenchOperationError(
            f"Artifact {artifact.id} is not a supported geo artifact"
        )

    def _feature_render_layer(
        self,
        artifact: ArtifactObject,
        *,
        layer_id: str,
        title: str,
        visible: bool,
        opacity: float,
        min_zoom: int,
        max_zoom: int,
        style: GeoVectorStyle | GeoCategorizedPointStyle,
    ) -> GeoRenderLayerResponse | None:
        projection_value = artifact.metadata.get("vector_projection")
        if projection_value is None and feature_count(artifact) == 0:
            return None
        projection = GeoVectorProjectionMetadata.model_validate(projection_value)
        value = artifact.metadata.get("property_fields", [])
        if not isinstance(value, list):
            raise ArtifactContentUnavailableError(
                f"Geo source artifact {artifact.id} has invalid "
                "property_fields metadata"
            )
        try:
            fields = [
                GeoPropertyFieldResponse.model_validate(field)
                for field in cast(list[object], value)
            ]
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Geo source artifact {artifact.id} has invalid "
                "property_fields metadata"
            ) from exc
        return GeoRenderLayerResponse(
            id=layer_id,
            title=title,
            visible=visible,
            opacity=opacity,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            source=GeoVectorRenderSourceResponse(
                artifact_id=artifact.id,
                archive_url=(
                    f"/v1/workspaces/{artifact.workspace_id}/artifacts/{artifact.id}/geo/vector.pmtiles"
                ),
                source_layer=projection.source_layer,
                bounds=projection.bounds,
                min_zoom=projection.min_zoom,
                max_zoom=projection.max_zoom,
                fields=fields,
            ),
            style=style,
        )

    async def _resolve_render_layer(
        self,
        layer_artifact: ArtifactObject,
        *,
        workspace_id: UUID,
    ) -> GeoRenderLayerResponse | None:
        if (
            layer_artifact.artifact_type != GEO_MAP_LAYER_ARTIFACT_TYPE
            or layer_artifact.schema_version != 1
        ):
            raise ArtifactContentUnavailableError(
                f"Artifact {layer_artifact.id} is not a geo.map_layer@1 artifact"
            )
        layer = GeoMapLayerPayload.model_validate(layer_artifact.inline_payload)
        if layer.source.kind == "feature_collection":
            source_artifact = (
                await resolve_exact_artifacts(
                    self._availability,
                    [layer.source.artifact],
                    expected_type=GEO_FEATURE_COLLECTION_ARTIFACT_TYPE,
                    context=f"Map layer artifact {layer_artifact.id}",
                    workspace_id=workspace_id,
                )
            )[0]
            if layer.style.kind == "raster":
                raise ValueError("Feature collection layer has non-vector style")
            return self._feature_render_layer(
                source_artifact,
                layer_id=str(layer_artifact.id),
                title=layer.title,
                visible=layer.visible,
                opacity=layer.opacity,
                min_zoom=layer.min_zoom,
                max_zoom=layer.max_zoom,
                style=layer.style,
            )
        if layer.source.kind == "raster_scan":
            source_artifact = (
                await resolve_exact_artifacts(
                    self._availability,
                    [layer.source.artifact],
                    expected_type=GEO_RASTER_SCAN_ARTIFACT_TYPE,
                    context=f"Map layer artifact {layer_artifact.id}",
                    workspace_id=workspace_id,
                )
            )[0]
            if layer.style.kind != "raster":
                raise ValueError("Raster scan layer has non-raster style")
            projection = GeoRasterProjectionMetadata.model_validate(
                source_artifact.metadata.get("raster_projection")
            )
            return GeoRenderLayerResponse(
                id=str(layer_artifact.id),
                title=layer.title,
                visible=layer.visible,
                opacity=layer.opacity,
                min_zoom=layer.min_zoom,
                max_zoom=layer.max_zoom,
                source=GeoRasterRenderSourceResponse(
                    artifact_id=source_artifact.id,
                    tilejson_url=(
                        f"/v1/workspaces/{source_artifact.workspace_id}/artifacts/"
                        f"{source_artifact.id}/geo/raster/tilejson.json"
                    ),
                    bounds=projection.bounds,
                ),
                style=layer.style,
            )
        if layer.style.kind != "raster":
            raise ValueError("WMS layer has non-raster style")
        _ = validated_public_destination(layer.source.url, service_name="WMS")
        return GeoRenderLayerResponse(
            id=str(layer_artifact.id),
            title=layer.title,
            visible=layer.visible,
            opacity=layer.opacity,
            min_zoom=layer.min_zoom,
            max_zoom=layer.max_zoom,
            source=GeoRasterRenderSourceResponse(
                artifact_id=None,
                tilejson_url=(
                    f"/v1/workspaces/{layer_artifact.workspace_id}/artifacts/{layer_artifact.id}/geo/raster/tilejson.json"
                ),
                bounds=layer.source.bounds,
                attribution=layer.source.attribution,
            ),
            style=layer.style,
        )


__all__ = [
    "ArtifactGeoService",
    "GEO_FEATURE_COLLECTION_ARTIFACT_TYPE",
    "GEO_INTERACTION_FEATURE_LIMIT",
    "GEO_MAP_DOCUMENT_ARTIFACT_TYPE",
    "GEO_MAP_LAYER_ARTIFACT_TYPE",
    "GEO_RASTER_SCAN_ARTIFACT_TYPE",
    "feature_count",
    "resolve_exact_artifacts",
    "source_name",
]
