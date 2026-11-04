from grafy_core.artifact_contracts import INTEGER_VALUE
from grafy_core.plugins import Plugin


SEQUENCES = Plugin(
    slug="sequence",
    title="Sequence",
)
SEQUENCES.register_artifact_type_dependency(INTEGER_VALUE)
