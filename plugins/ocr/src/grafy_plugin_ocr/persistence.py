import json
from hashlib import sha256
from typing import cast, final, override

from grafy_core.artifacts import ArtifactObject, ArtifactRef, JsonObject
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.runtime.persistence import (
    ArtifactOutputWriter,
    ArtifactWriteContext,
)

from grafy_plugin_ocr.artifacts import OCR_PAGE_RESULT
from grafy_plugin_ocr.tesseract import OcrPagePayload, SimpleOcrResult


@final
class OcrPageResultOutputWriter(ArtifactOutputWriter):
    artifact_type = OCR_PAGE_RESULT.key

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        engine: str = "tesseract",
    ) -> None:
        self._uow = uow
        self._engine = engine

    @override
    async def write(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        payload = self._payload_from_value(value, context)
        payload_json = payload.model_dump(mode="json")
        payload_bytes = json.dumps(
            payload_json,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        artifact = ArtifactObject(
            workspace_id=context.node_context.workspace_id,
            artifact_type=self.artifact_type.id,
            schema_version=self.artifact_type.schema_version,
            content_type="application/json",
            storage_backend="inline",
            inline_payload=cast(JsonObject, payload_json),
            sha256=sha256(payload_bytes).hexdigest(),
            metadata={
                "source_image_artifact_id": str(payload.image_artifact_id),
                "sequence_index": payload.sequence_index,
                "engine": payload.engine,
            },
        )
        async with self._uow as uow:
            await uow.artifacts.add(artifact)
            await uow.commit()
        return artifact.ref()

    def _payload_from_value(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> OcrPagePayload:
        if isinstance(value, OcrPagePayload):
            return value

        result = SimpleOcrResult.model_validate(value)
        source_refs = context.provenance.refs_for("pages")
        effective_item_index = (
            context.item_index if context.item_index is not None else 0
        )
        if effective_item_index >= len(source_refs):
            raise RuntimeError("OCR output does not have a matching source page ref")

        source_ref = source_refs[effective_item_index]
        return OcrPagePayload(
            image_artifact_id=source_ref.artifact_id,
            sequence_index=effective_item_index,
            engine=self._engine,
            text=result.text,
        )
