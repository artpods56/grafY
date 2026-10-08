from grafy_core.artifact_contracts import INTEGER_VALUE, MARKDOWN, TEXT_VALUE
from grafy_core.plugins import Plugin
from grafy_core.table_contracts import TABLE_DATA


PYTHON = Plugin(
    slug="external.python",
    title="Python",
)

# The artifact types a Python node may name in its annotations. A port type the
# release does not declare is refused at Apply.
PORT_ARTIFACT_TYPES = (TEXT_VALUE, INTEGER_VALUE, MARKDOWN, TABLE_DATA)

for _artifact_type in PORT_ARTIFACT_TYPES:
    PYTHON.register_artifact_type_dependency(_artifact_type)
