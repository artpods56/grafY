from grafy_core.file_contracts import CSV_FILE, XLSX_FILE
from grafy_core.plugins import Plugin


TABLES = Plugin(
    slug="table",
    title="Table",
)
TABLES.register_artifact_type_dependency(CSV_FILE)
TABLES.register_artifact_type_dependency(XLSX_FILE)


__all__ = ["TABLES"]
