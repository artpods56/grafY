"""Private response shapes used to normalize absent SDK fields."""

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr


class OcrBlockConfidence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    average_content_confidence_score: float | None = None
    minimum_content_confidence_score: float | None = None
    block_type_confidence_score: float | None = None


class OcrPageConfidence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    average_page_confidence_score: float
    minimum_page_confidence_score: float


class _OcrContentBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

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
    model_config = ConfigDict(extra="ignore")

    id: StrictStr = Field(min_length=1)
    top_left_x: int | None = None
    top_left_y: int | None = None
    bottom_right_x: int | None = None
    bottom_right_y: int | None = None
    image_base64: StrictStr | None = None


class OcrTable(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: StrictStr = Field(min_length=1)
    content: StrictStr
    format: Literal["markdown", "html"]


class OcrPageDimensions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dpi: int = Field(ge=0)
    height: int = Field(ge=0)
    width: int = Field(ge=0)


class OcrPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int = Field(ge=0)
    markdown: StrictStr
    images: list[OcrImage]
    dimensions: OcrPageDimensions | None = None
    tables: list[OcrTable] | None = None
    confidence_scores: OcrPageConfidence | None = None
    blocks: list[OcrBlock] | None = None
