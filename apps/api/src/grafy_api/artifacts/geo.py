import asyncio
from collections.abc import Collection
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from grafy_core.artifact_collections import load_json_collections_page
from grafy_core.artifacts import ArtifactObject, ArtifactRef
from grafy_core.egress import validated_public_destination
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.spatial_contracts import BasemapKind
from grafy_shared.config.tiler import TilerConfig

from grafy_api.artifact_availability import ArtifactAvailability, ArtifactReferenceError
from grafy_api.artifacts.errors import GeoRenderArtifactNotFoundError
from grafy_api.artifacts.geo_tiff import (
    TIFF_ARTIFACT_TYPE,
    GeoTiffInfo,
    load_geo_tiff,
    require_raster_tiler,
    tiff_title,
)
from grafy_api.artifacts.images import ImageProxyError, TilerPort
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
    GeoJsonRenderSourceResponse,
    GeoMapDocumentPayload,
    GeoMapLayerPayload,
    GeoPropertyFieldResponse,
    GeoRasterRenderSourceResponse,
    GeoRasterStyle,
    GeoRenderLayerResponse,
    GeoRenderResponse,
    GeoVectorStyle,
    interaction_values_equal,
)


GEO_FEATURE_COLLECTION_ARTIFACT_TYPE = "geo.feature_collection"
GEO_MAP_LAYER_ARTIFACT_TYPE = "geo.map_layer"
GEO_MAP_DOCUMENT_ARTIFACT_TYPE = "geo.map_document"
GEO_INTERACTION_FEATURE_LIMIT = 250_000
RASTER_SOURCE_TYPES = (TIFF_ARTIFACT_TYPE,)


@dataclass(frozen=True, slots=True)
class _ResolvedRenderLayer:
    """One map layer's rendered layer and footprint."""

    layer: GeoRenderLayerResponse
    bounds: GeoBounds | None


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
    return bounds_union(nested)


def _geometry_bounds(geometry: object) -> GeoBounds | None:
    if not isinstance(geometry, dict):
        return None
    typed_geometry = cast(dict[str, object], geometry)
    if typed_geometry.get("type") == "GeometryCollection":
        geometries = typed_geometry.get("geometries")
        if not isinstance(geometries, list):
            return None
        typed_geometries = cast(list[object], geometries)
        return bounds_union(
            [
                bounds
                for value in typed_geometries
                if (bounds := _geometry_bounds(value)) is not None
            ]
        )
    return _coordinate_bounds(typed_geometry.get("coordinates"))


def bounds_union(
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


def collection_bounds(artifact: ArtifactObject) -> GeoBounds | None:
    """Footprint recorded when a feature collection was written, if it had one."""
    value = artifact.metadata.get("bounds")
    if not isinstance(value, list):
        return None
    items = cast(list[object], value)
    if len(items) != 4:
        return None
    numbers: list[float] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, int | float):
            return None
        numbers.append(float(item))
    west, south, east, north = numbers
    return (west, south, east, north)


def _feature_render_layer(
    artifact: ArtifactObject,
    *,
    layer_id: str,
    title: str,
    visible: bool,
    opacity: float,
    min_zoom: int,
    max_zoom: int,
    style: GeoVectorStyle | GeoCategorizedPointStyle,
) -> GeoRenderLayerResponse:
    """A stored feature collection drawn by the browser from its GeoJSON.

    The descriptor names the collection; the browser fetches the stored
    features when it draws them. Nothing is derived when the collection is
    written.
    """
    # The property columns recorded when the collection was written, so a card
    # linked to the map can offer them as selection fields.
    invalid_fields = (
        f"Feature collection artifact {artifact.id} has invalid "
        "property_fields metadata"
    )
    stored_fields = artifact.metadata.get("property_fields", [])
    if not isinstance(stored_fields, list):
        raise ArtifactContentUnavailableError(invalid_fields)
    try:
        fields = [
            GeoPropertyFieldResponse.model_validate(field)
            for field in cast(list[object], stored_fields)
        ]
    except ValueError as exc:
        raise ArtifactContentUnavailableError(invalid_fields) from exc
    return GeoRenderLayerResponse(
        id=layer_id,
        title=title,
        visible=visible,
        opacity=opacity,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        source=GeoJsonRenderSourceResponse(
            artifact_id=artifact.id,
            data_url=(
                f"/v1/workspaces/{artifact.workspace_id}/artifacts/"
                f"{artifact.id}/geo/features.geojson"
            ),
            bounds=collection_bounds(artifact),
            feature_count=feature_count(artifact),
            fields=fields,
        ),
        style=style,
    )


async def resolve_exact_artifacts(
    availability: ArtifactAvailability,
    refs: list[GeoArtifactRefPayload],
    *,
    expected_type: str | Collection[str],
    context: str,
    workspace_id: UUID,
) -> list[ArtifactObject]:
    allowed_types = (
        [expected_type] if isinstance(expected_type, str) else list(expected_type)
    )
    for ref in refs:
        if ref.artifact_type not in allowed_types or ref.schema_version != 1:
            expected = " or ".join(f"{name}@1" for name in allowed_types)
            raise ArtifactContentUnavailableError(
                f"{context} references {ref.artifact_type}@{ref.schema_version}, "
                f"expected {expected}"
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


async def load_mosaic_infos(
    availability: ArtifactAvailability,
    refs: list[GeoArtifactRefPayload],
    tiler: TilerPort,
    *,
    context: str,
    workspace_id: UUID,
) -> list[GeoTiffInfo]:
    """Footprints of a mosaic's sources, bottom to top, all in one Workspace."""
    artifacts = await resolve_exact_artifacts(
        availability,
        refs,
        expected_type=RASTER_SOURCE_TYPES,
        context=context,
        workspace_id=workspace_id,
    )
    return list(
        await asyncio.gather(
            *(load_geo_tiff(artifact, tiler) for artifact in artifacts)
        )
    )


class ArtifactGeoService:
    """Builds map render descriptors and linked feature queries."""

    def __init__(
        self,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
        *,
        availability: ArtifactAvailability,
        tiler: TilerPort | None = None,
        tiler_config: TilerConfig | None = None,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._availability = availability
        self._tiler = tiler
        self._tiler_config = tiler_config

    async def get(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactObject | None:
        async with self._uow as uow:
            return await uow.artifacts.get(workspace_id, artifact_id)

    async def feature_source_ids(
        self,
        artifact: ArtifactObject,
        *,
        workspace_id: UUID,
    ) -> list[UUID]:
        """Feature collections one geo artifact reads, in draw order."""
        if artifact.artifact_type == GEO_FEATURE_COLLECTION_ARTIFACT_TYPE:
            return [artifact.id]
        if artifact.artifact_type == GEO_MAP_LAYER_ARTIFACT_TYPE:
            layer = GeoMapLayerPayload.model_validate(artifact.inline_payload)
            if layer.source.kind != "feature_collection":
                return []
            _ = await resolve_exact_artifacts(
                self._availability,
                [layer.source.artifact],
                expected_type=GEO_FEATURE_COLLECTION_ARTIFACT_TYPE,
                context=f"Map layer artifact {artifact.id}",
                workspace_id=workspace_id,
            )
            return [layer.source.artifact.artifact_id]
        if artifact.artifact_type == GEO_MAP_DOCUMENT_ARTIFACT_TYPE:
            document = GeoMapDocumentPayload.model_validate(artifact.inline_payload)
            layer_artifacts = await resolve_exact_artifacts(
                self._availability,
                document.layers,
                expected_type=GEO_MAP_LAYER_ARTIFACT_TYPE,
                context=f"Map document artifact {artifact.id}",
                workspace_id=workspace_id,
            )
            ordered: list[UUID] = []
            for layer_artifact in layer_artifacts:
                for source_id in await self.feature_source_ids(
                    layer_artifact,
                    workspace_id=workspace_id,
                ):
                    if source_id not in ordered:
                        ordered.append(source_id)
            return ordered
        return []

    async def query_geo_features(
        self,
        artifact: ArtifactObject,
        rows: list[ArtifactExactMatchRow],
        *,
        workspace_id: UUID,
    ) -> GeoFeatureQueryResponse:
        source_ids = await self.feature_source_ids(
            artifact,
            workspace_id=workspace_id,
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
            bounds=bounds_union(matched_bounds),
            matched_feature_count=matched_feature_count,
            source_artifact_ids=source_ids,
        )

    async def load_combined_geo_render(
        self,
        artifact_ids: list[UUID],
        *,
        workspace_id: UUID,
        basemap: BasemapKind,
    ) -> GeoRenderResponse:
        async with self._uow as uow:
            artifacts = await uow.artifacts.get_many(workspace_id, artifact_ids)
        ordered_artifacts: list[ArtifactObject] = []
        for artifact_id in artifact_ids:
            if (artifact := artifacts.get(artifact_id)) is None:
                raise GeoRenderArtifactNotFoundError(
                    f"Artifact {artifact_id} not found"
                )
            ordered_artifacts.append(artifact)

        layers: list[GeoRenderLayerResponse] = []
        layer_ids: set[str] = set()
        bounds: list[GeoBounds] = []
        for artifact in ordered_artifacts:
            descriptor = await self.load_geo_render(artifact, workspace_id=workspace_id)
            if descriptor.initial_bounds is not None:
                bounds.append(descriptor.initial_bounds)
            for layer in descriptor.layers:
                if layer.id in layer_ids:
                    layer = layer.model_copy(update={"id": f"{layer.id}:{len(layers)}"})
                layer_ids.add(layer.id)
                layers.append(layer)
        return GeoRenderResponse(
            artifact_id=artifact_ids[0],
            kind="map_document",
            basemap=basemap,
            initial_bounds=bounds_union(bounds),
            layers=layers,
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
                name = artifact.metadata.get("source_name")
                feature_layer = _feature_render_layer(
                    artifact,
                    layer_id=str(artifact.id),
                    title=name if isinstance(name, str) and name else "Features",
                    visible=True,
                    opacity=1.0,
                    min_zoom=0,
                    max_zoom=22,
                    style=GeoVectorStyle.default(),
                )
                return GeoRenderResponse(
                    artifact_id=artifact.id,
                    kind="feature_collection",
                    basemap="openstreetmap",
                    initial_bounds=feature_layer.source.bounds,
                    layers=[feature_layer],
                )
            if artifact.artifact_type == TIFF_ARTIFACT_TYPE:
                tiler = require_raster_tiler(self._tiler, self._tiler_config)
                info = await load_geo_tiff(artifact, tiler)
                raster_layer = GeoRenderLayerResponse(
                    id=str(artifact.id),
                    title=tiff_title(artifact),
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
                        bounds=info.bounds,
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
                resolved = await self._resolve_render_layer(
                    artifact,
                    workspace_id=workspace_id,
                )
                layers = [resolved.layer]
                return GeoRenderResponse(
                    artifact_id=artifact.id,
                    kind="map_layer",
                    basemap="openstreetmap",
                    initial_bounds=resolved.bounds,
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
                layer_bounds: list[GeoBounds] = []
                for layer_artifact in layer_artifacts:
                    resolved = await self._resolve_render_layer(
                        layer_artifact,
                        workspace_id=workspace_id,
                    )
                    document_layers.append(resolved.layer)
                    if resolved.bounds is not None:
                        layer_bounds.append(resolved.bounds)
                effective_bounds = document.initial_bounds
                if effective_bounds is None:
                    effective_bounds = bounds_union(layer_bounds)
                return GeoRenderResponse(
                    artifact_id=artifact.id,
                    kind="map_document",
                    basemap=document.basemap,
                    initial_bounds=effective_bounds,
                    layers=document_layers,
                )
        except (ImageProxyError, WorkbenchOperationError):
            raise
        except Exception as exc:
            raise ArtifactContentUnavailableError(
                f"Could not build render descriptor for artifact {artifact.id}"
            ) from exc
        raise WorkbenchOperationError(
            f"Artifact {artifact.id} is not a supported geo artifact"
        )

    async def _resolve_render_layer(
        self,
        layer_artifact: ArtifactObject,
        *,
        workspace_id: UUID,
    ) -> _ResolvedRenderLayer:
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
            rendered = _feature_render_layer(
                source_artifact,
                layer_id=str(layer_artifact.id),
                title=layer.title,
                visible=layer.visible,
                opacity=layer.opacity,
                min_zoom=layer.min_zoom,
                max_zoom=layer.max_zoom,
                style=layer.style,
            )
            return _ResolvedRenderLayer(rendered, rendered.source.bounds)
        if layer.source.kind == "raster_scan":
            source_artifact = (
                await resolve_exact_artifacts(
                    self._availability,
                    [layer.source.artifact],
                    expected_type=RASTER_SOURCE_TYPES,
                    context=f"Map layer artifact {layer_artifact.id}",
                    workspace_id=workspace_id,
                )
            )[0]
            if layer.style.kind != "raster":
                raise ValueError("Raster layer has non-raster style")
            tiler = require_raster_tiler(self._tiler, self._tiler_config)
            bounds = (await load_geo_tiff(source_artifact, tiler)).bounds
            return _ResolvedRenderLayer(
                GeoRenderLayerResponse(
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
                        bounds=bounds,
                    ),
                    style=layer.style,
                ),
                bounds,
            )
        if layer.source.kind == "raster_mosaic":
            if layer.style.kind != "raster":
                raise ValueError("Raster mosaic layer has non-raster style")
            tiler = require_raster_tiler(self._tiler, self._tiler_config)
            infos = await load_mosaic_infos(
                self._availability,
                layer.source.artifacts,
                tiler,
                context=f"Map layer artifact {layer_artifact.id}",
                workspace_id=workspace_id,
            )
            bounds = bounds_union([info.bounds for info in infos])
            assert bounds is not None  # a mosaic has at least one source
            return _ResolvedRenderLayer(
                GeoRenderLayerResponse(
                    id=str(layer_artifact.id),
                    title=layer.title,
                    visible=layer.visible,
                    opacity=layer.opacity,
                    min_zoom=layer.min_zoom,
                    max_zoom=layer.max_zoom,
                    source=GeoRasterRenderSourceResponse(
                        artifact_id=layer_artifact.id,
                        tilejson_url=(
                            f"/v1/workspaces/{layer_artifact.workspace_id}/artifacts/"
                            f"{layer_artifact.id}/geo/raster/tilejson.json"
                        ),
                        bounds=bounds,
                    ),
                    style=layer.style,
                ),
                bounds,
            )
        if layer.style.kind != "raster":
            raise ValueError("WMS layer has non-raster style")
        _ = validated_public_destination(layer.source.url, service_name="WMS")
        return _ResolvedRenderLayer(
            GeoRenderLayerResponse(
                id=str(layer_artifact.id),
                title=layer.title,
                visible=layer.visible,
                opacity=layer.opacity,
                min_zoom=layer.min_zoom,
                max_zoom=layer.max_zoom,
                source=GeoRasterRenderSourceResponse(
                    artifact_id=None,
                    tilejson_url=(
                        f"/v1/workspaces/{layer_artifact.workspace_id}/artifacts/"
                        f"{layer_artifact.id}/geo/raster/tilejson.json"
                    ),
                    bounds=layer.source.bounds,
                    attribution=layer.source.attribution,
                ),
                style=layer.style,
            ),
            layer.source.bounds,
        )


__all__ = [
    "ArtifactGeoService",
    "GEO_FEATURE_COLLECTION_ARTIFACT_TYPE",
    "GEO_INTERACTION_FEATURE_LIMIT",
    "GEO_MAP_DOCUMENT_ARTIFACT_TYPE",
    "GEO_MAP_LAYER_ARTIFACT_TYPE",
    "RASTER_SOURCE_TYPES",
    "bounds_union",
    "collection_bounds",
    "feature_count",
    "load_mosaic_infos",
    "resolve_exact_artifacts",
]
