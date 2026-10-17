from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class TableSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_count: StrictInt = Field(ge=0)
    column_count: StrictInt = Field(ge=0)
    column_ids: tuple[StrictStr, ...] = ()
