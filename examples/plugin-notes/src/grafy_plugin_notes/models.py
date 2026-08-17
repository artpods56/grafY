from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class TableSummary(BaseModel):
    """JSON payload for notes.table_summary@1.

    This is a catalog artifact type because it is persistable JSON. A Pillow
    Image (or any host-unknown Python object) on this model would be illegal
    until this Plugin also shipped a writer and resolver for that storage.
    """

    model_config = ConfigDict(extra="forbid")

    row_count: StrictInt = Field(ge=0)
    column_count: StrictInt = Field(ge=0)
    column_ids: tuple[StrictStr, ...] = ()
