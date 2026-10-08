from grafy_core.artifacts import Artifact
from grafy_core.runtime.persistence import InlineModelOutputWriter
from grafy_core.runtime.resolvers import InlineModelResolver

from grafy_plugin_mistral import ocr
from grafy_plugin_mistral.artifacts import OCR_DOCUMENT, OcrDocumentPayload
from grafy_plugin_mistral.declaration import MISTRAL


_NODE_MODULES = (ocr,)

MISTRAL.register(
    Artifact(
        spec=OCR_DOCUMENT,
        resolver=lambda context: InlineModelResolver(
            source=OCR_DOCUMENT.key,
            target=OcrDocumentPayload,
            uow=context.uow,
        ),
        writer=lambda context: InlineModelOutputWriter(
            artifact_type=OCR_DOCUMENT.key,
            model=OcrDocumentPayload,
            uow=context.uow,
        ),
    )
)


__all__ = ["MISTRAL"]
