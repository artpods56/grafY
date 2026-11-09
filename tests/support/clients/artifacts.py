from __future__ import annotations

from typing import Mapping
from uuid import UUID

from httpx import Response
from starlette.testclient import TestClient

from grafy_api.v1.routes.artifacts.models import GeoFeatureQueryRequest
from tests.support.clients._http import _request


class ArtifactsApi:
    """Workbench artifacts scoped to one workspace.

    Covers the geo render/query/vector/raster and raw content/download
    endpoints under
    ``/v1/workspaces/{workspace_id}/artifacts``.
    """

    __slots__ = ("_client", "_workspace_id")

    def __init__(self, client: TestClient, workspace_id: UUID) -> None:
        self._client = client
        self._workspace_id = workspace_id

    # -- geo -----------------------------------------------------------------

    def geo_render(
        self, artifact_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/artifacts/{artifact_id}/geo/render",
            headers=headers,
        )

    def query_geo_features(
        self,
        artifact_id: UUID,
        payload: GeoFeatureQueryRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return _request(
            self._client,
            "POST",
            f"/v1/workspaces/{self._workspace_id}/artifacts/{artifact_id}/geo/query",
            payload=payload,
            headers=headers,
        )

    def geo_vector_pmtiles(
        self, source_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        """Stream the binary pmtiles archive (``Range`` via ``headers``)."""

        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}"
            f"/artifacts/{source_id}/geo/vector.pmtiles",
            headers=headers,
        )

    def geo_exact_feature(
        self,
        source_id: UUID,
        feature_index: int,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}"
            f"/artifacts/{source_id}/geo/features/{feature_index}",
            headers=headers,
        )

    def raster_tilejson(
        self, source_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}"
            f"/artifacts/{source_id}/geo/raster/tilejson.json",
            headers=headers,
        )

    def raster_tile(
        self,
        source_id: UUID,
        z: int,
        x: int,
        y: int,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Fetch one PNG tile; the response has no JSON model."""

        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}"
            f"/artifacts/{source_id}/geo/raster/{z}/{x}/{y}.png",
            headers=headers,
        )

    # -- content -------------------------------------------------------------

    def content(
        self, artifact_id: UUID, *, headers: Mapping[str, str] | None = None
    ) -> Response:
        """Stream the stored artifact content; the body may be non-JSON."""

        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/artifacts/{artifact_id}/content",
            headers=headers,
        )

    def download(
        self,
        artifact_id: UUID,
        *,
        format: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Stream an export; ``Content-Disposition`` carries the filename."""

        params = {"format": format} if format is not None else None
        return self._client.get(
            f"/v1/workspaces/{self._workspace_id}/artifacts/{artifact_id}/download",
            params=params,
            headers=headers,
        )
