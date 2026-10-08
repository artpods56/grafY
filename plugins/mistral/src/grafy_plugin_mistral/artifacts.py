from typing import Annotated, Literal, Self, cast
from uuid import UUID

from mistralai.client.models.ocrresponse import OCRResponse
from mistralai.client.models.ocrtableobject import OCRTableObject
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    TypeAdapter,
    model_validator,
)

from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec, JsonObject
from grafy_core.schema_contracts import (
    parse_json_schema,
    validate_json_schema_value,
)


class OcrWordConfidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: StrictStr
    confidence: float
    start_index: int = Field(ge=0)


class OcrBlockConfidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    average_content_confidence_score: float | None = None
    minimum_content_confidence_score: float | None = None
    block_type_confidence_score: float | None = None


class OcrPageConfidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    average_page_confidence_score: float
    minimum_page_confidence_score: float
    word_confidence_scores: list[OcrWordConfidence] = Field(
        default_factory=list[OcrWordConfidence]
    )


class _OcrContentBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_left_x: int
    top_left_y: int
    bottom_right_x: int
    bottom_right_y: int
    content: StrictStr
    confidence_scores: OcrBlockConfidence | None = None


class OcrAsideTextBlock(_OcrContentBlock):
    type: Literal["aside_text"]


class OcrCaptionBlock(_OcrContentBlock):
    type: Literal["caption"]


class OcrCodeBlock(_OcrContentBlock):
    type: Literal["code"]


class OcrEquationBlock(_OcrContentBlock):
    type: Literal["equation"]


class OcrFooterBlock(_OcrContentBlock):
    type: Literal["footer"]


class OcrHeaderBlock(_OcrContentBlock):
    type: Literal["header"]


class OcrListBlock(_OcrContentBlock):
    type: Literal["list"]


class OcrReferencesBlock(_OcrContentBlock):
    type: Literal["references"]


class OcrSignatureBlock(_OcrContentBlock):
    type: Literal["signature"]


class OcrTextBlock(_OcrContentBlock):
    type: Literal["text"]


class OcrTitleBlock(_OcrContentBlock):
    type: Literal["title"]


class OcrImageBlock(_OcrContentBlock):
    type: Literal["image"]
    image_id: StrictStr = Field(min_length=1)


class OcrTableBlock(_OcrContentBlock):
    type: Literal["table"]
    table_id: StrictStr | None = None


OcrBlock = Annotated[
    OcrAsideTextBlock
    | OcrCaptionBlock
    | OcrCodeBlock
    | OcrEquationBlock
    | OcrFooterBlock
    | OcrHeaderBlock
    | OcrImageBlock
    | OcrListBlock
    | OcrReferencesBlock
    | OcrSignatureBlock
    | OcrTableBlock
    | OcrTextBlock
    | OcrTitleBlock,
    Field(discriminator="type"),
]


class OcrImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(min_length=1)
    top_left_x: int | None
    top_left_y: int | None
    bottom_right_x: int | None
    bottom_right_y: int | None
    image_base64: StrictStr | None = None
    image_annotation: JsonObject | None = None


class OcrTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(min_length=1)
    content: StrictStr
    format: Literal["markdown", "html"]
    word_confidence_scores: list[OcrWordConfidence] = Field(
        default_factory=list[OcrWordConfidence]
    )

    @classmethod
    def from_sdk(cls, table: OCRTableObject) -> Self:
        data = table.model_dump(mode="json", by_alias=True)
        if data.get("word_confidence_scores") is None:
            data["word_confidence_scores"] = []
        return cls.model_validate(data)


class OcrPageDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dpi: int = Field(ge=0)
    height: int = Field(ge=0)
    width: int = Field(ge=0)


class OcrPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    markdown: StrictStr
    images: list[OcrImage]
    dimensions: OcrPageDimensions | None
    tables: list[OcrTable] = Field(default_factory=list[OcrTable])
    hyperlinks: list[StrictStr] = Field(default_factory=list)
    header: StrictStr | None = None
    footer: StrictStr | None = None
    confidence_scores: OcrPageConfidence | None = None
    blocks: list[OcrBlock] | None = None


class OcrDocumentPayload(BaseModel):
    """Mistral OCR result safe for artifact persistence."""

    model_config = ConfigDict(extra="forbid")

    markdown: StrictStr = Field(
        description="Page markdown joined in response order.",
    )
    pages: list[OcrPage] = Field(min_length=1)
    model: StrictStr = Field(min_length=1)
    base_url: StrictStr = Field(min_length=1)
    document_kind: Literal["document_url", "image_url"]
    source_image_artifact_id: UUID | None = None
    pages_processed: int = Field(ge=0)
    doc_size_bytes: int | None = Field(default=None, ge=0)
    document_annotation: JsonObject | None = None
    document_annotation_schema: StrictStr | None = None
    document_annotation_schema_name: StrictStr | None = Field(
        default=None,
        min_length=1,
    )
    bbox_annotation_schema: StrictStr | None = None
    bbox_annotation_schema_name: StrictStr | None = Field(
        default=None,
        min_length=1,
    )
    table_format: Literal["markdown", "html"] | None = None
    include_image_base64: bool
    include_blocks: bool

    @classmethod
    def from_sdk(
        cls,
        response: OCRResponse,
        *,
        base_url: str,
        document_kind: Literal["document_url", "image_url"],
        source_image_artifact_id: UUID | None,
        table_format: Literal["markdown", "html"] | None,
        include_image_base64: bool,
        include_blocks: bool,
        document_annotation_schema: str | None,
        document_annotation_schema_name: str,
        bbox_annotation_schema: str | None,
        bbox_annotation_schema_name: str,
    ) -> Self:
        pages: list[OcrPage] = []
        for sdk_page in response.pages:
            page_data = sdk_page.model_dump(mode="json", by_alias=True)
            images: list[OcrImage] = []
            for sdk_image in sdk_page.images:
                image_data = sdk_image.model_dump(mode="json", by_alias=True)
                if not include_image_base64:
                    image_data["image_base64"] = None
                image_data["image_annotation"] = _annotation_value(
                    sdk_image.image_annotation,
                    schema=bbox_annotation_schema,
                )
                images.append(OcrImage.model_validate(image_data))
            page_data["images"] = images
            page_data["tables"] = [
                OcrTable.from_sdk(table) for table in sdk_page.tables or []
            ]
            page_data["hyperlinks"] = sdk_page.hyperlinks or []
            page_data["blocks"] = page_data.get("blocks") if include_blocks else None
            pages.append(OcrPage.model_validate(page_data))
        doc_size = response.usage_info.doc_size_bytes
        return cls(
            markdown="\n\n".join(page.markdown for page in pages),
            pages=pages,
            model=response.model,
            base_url=base_url,
            document_kind=document_kind,
            source_image_artifact_id=source_image_artifact_id,
            pages_processed=response.usage_info.pages_processed,
            doc_size_bytes=doc_size if isinstance(doc_size, int) else None,
            document_annotation=_annotation_value(
                response.document_annotation, schema=document_annotation_schema
            ),
            document_annotation_schema=document_annotation_schema,
            document_annotation_schema_name=(
                document_annotation_schema_name
                if document_annotation_schema is not None
                else None
            ),
            bbox_annotation_schema=bbox_annotation_schema,
            bbox_annotation_schema_name=(
                bbox_annotation_schema_name
                if bbox_annotation_schema is not None
                else None
            ),
            table_format=table_format,
            include_image_base64=include_image_base64,
            include_blocks=include_blocks,
        )

    @model_validator(mode="after")
    def validate_annotations(self) -> Self:
        document_schema = self.document_annotation_schema
        document_name = self.document_annotation_schema_name
        document_value = self.document_annotation
        if document_schema is None:
            if document_value is not None or document_name is not None:
                raise ValueError("Document annotation metadata requires a JSON Schema")
        elif document_value is None or document_name is None:
            raise ValueError(
                "A document annotation JSON Schema requires the annotation value"
            )
        else:
            _ = parse_json_schema(
                document_schema,
                context=f"document annotation schema {document_name!r}",
            )
            _ = validate_json_schema_value(document_schema, document_value)

        bbox_schema = self.bbox_annotation_schema
        bbox_name = self.bbox_annotation_schema_name
        if bbox_schema is None:
            if bbox_name is not None:
                raise ValueError("Bounding-box annotation metadata requires a schema")
            annotated = any(
                image.image_annotation is not None
                for page in self.pages
                for image in page.images
            )
            if annotated:
                raise ValueError(
                    "Image annotations require a bounding-box annotation schema"
                )
            return self
        if bbox_name is None:
            raise ValueError("A bounding-box annotation schema requires its name")
        _ = parse_json_schema(
            bbox_schema,
            context=f"bounding-box annotation schema {bbox_name!r}",
        )
        for page in self.pages:
            for image in page.images:
                annotation = image.image_annotation
                if annotation is None:
                    raise ValueError(
                        f"Extracted image {image.id!r} on page {page.index} "
                        "is missing its bounding-box annotation"
                    )
                _ = validate_json_schema_value(bbox_schema, annotation)
        return self


def _annotation_value(raw: object, *, schema: str | None) -> JsonObject | None:
    if schema is None or raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("Requested annotation was missing or was not JSON text")
    value = TypeAdapter(JsonObject).validate_json(raw)
    return validate_json_schema_value(schema, value)


OCR_DOCUMENT = ArtifactTypeSpec(
    key=ArtifactTypeKey("mistral.ocr.document", 1),
    title="Mistral OCR document",
    payload_schema=cast(JsonObject, OcrDocumentPayload.model_json_schema()),
)
