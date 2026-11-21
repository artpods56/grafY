from grafy_core.artifact_contracts import MARKDOWN
from grafy_core.plugins import Plugin


TABLES = Plugin(slug="table", title="Table")
TABLES.register_artifact_type_dependency(MARKDOWN)
