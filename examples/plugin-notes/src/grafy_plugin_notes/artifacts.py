from typing import cast

from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec, JsonObject

from grafy_plugin_notes.models import TableSummary

TABLE_SUMMARY = ArtifactTypeSpec(
    key=ArtifactTypeKey("notes.table_summary", 1),
    title="Table summary",
    payload_schema=cast(JsonObject, TableSummary.model_json_schema()),
)
