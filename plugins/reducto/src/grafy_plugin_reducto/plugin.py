from grafy_core.artifact_contracts import MARKDOWN, MarkdownValue
from grafy_core.runtime.persistence import InlineModelOutputWriter

from grafy_plugin_reducto import ocr
from grafy_plugin_reducto.declaration import REDUCTO

_NODE_MODULES = (ocr,)

REDUCTO.register_writer(
    lambda context: InlineModelOutputWriter(
        artifact_type=MARKDOWN.key, model=MarkdownValue, uow=context.uow
    )
)

__all__ = ["REDUCTO"]
