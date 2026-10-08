from grafy_core.artifact_contracts import RASTER_IMAGE

from grafy_workbench.image.declaration import IMAGES


IMAGES.register_artifact_type(RASTER_IMAGE)


__all__ = ["IMAGES"]
