from grafy_core.documents import raster_image_artifact

from grafy_workbench.image.declaration import IMAGES


IMAGES.register(raster_image_artifact())


__all__ = ["IMAGES"]
