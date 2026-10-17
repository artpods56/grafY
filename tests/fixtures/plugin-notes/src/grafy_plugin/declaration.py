from grafy_core.plugins import Plugin
from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.table_contracts import TABLE_DATA


PLUGIN = Plugin(slug="notes", title="Notes")
PLUGIN.register_artifact_type_dependency(TABLE_DATA)
PLUGIN.register_artifact_type_dependency(TEXT_VALUE)
