from grafy_core.artifact_contracts import (
    IMAGE_REGIONS,
    MARKDOWN,
    ImageRegionSet,
    MarkdownValue,
)
from grafy_core.runtime.persistence import InlineModelOutputWriter

from grafy_plugin_mistral import ocr
from grafy_plugin_mistral.declaration import MISTRAL

_NODE_MODULES = (ocr,)

MISTRAL.register_writer(
    lambda context: InlineModelOutputWriter(
        artifact_type=IMAGE_REGIONS.key, model=ImageRegionSet, uow=context.uow
    )
)
MISTRAL.register_writer(
    lambda context: InlineModelOutputWriter(
        artifact_type=MARKDOWN.key, model=MarkdownValue, uow=context.uow
    )
)

__all__ = ["MISTRAL"]
