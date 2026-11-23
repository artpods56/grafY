from uuid import UUID

from grafy_api.services.errors import WorkbenchOperationError


class GeoRasterUnavailableError(WorkbenchOperationError):
    """The artifact cannot be rendered as a georeferenced raster."""


class GeoRasterTileNotFoundError(WorkbenchOperationError):
    """A tile outside the rendered range of a raster source was requested."""


class GeoRenderArtifactNotFoundError(WorkbenchOperationError):
    """A requested render artifact is unavailable in the workspace."""


class ArtifactResponseTooLargeError(WorkbenchOperationError):
    def __init__(
        self,
        *,
        artifact_id: UUID,
        byte_size: int,
        max_byte_size: int,
    ) -> None:
        super().__init__(
            f"Artifact {artifact_id} requires a {byte_size}-byte buffered "
            f"response, exceeding the {max_byte_size}-byte response limit"
        )
        self.byte_size = byte_size
        self.max_byte_size = max_byte_size


__all__ = [
    "ArtifactResponseTooLargeError",
    "GeoRasterTileNotFoundError",
    "GeoRasterUnavailableError",
    "GeoRenderArtifactNotFoundError",
]
