"""GIS producer input contracts."""

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBytes,
    StrictStr,
    field_validator,
)


class GeoRasterScan(BaseModel):
    """A georeferenced GeoTIFF upload normalized to COG during persistence."""

    model_config = ConfigDict(extra="forbid")

    content: StrictBytes = Field(min_length=1)
    filename: StrictStr = Field(min_length=1, max_length=1_024)
    source_name: StrictStr = Field(min_length=1, max_length=1_024)

    @field_validator("filename", "source_name")
    @classmethod
    def validate_non_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("values must not have surrounding whitespace")
        return value
