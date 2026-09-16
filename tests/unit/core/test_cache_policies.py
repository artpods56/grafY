from grafy_workbench.arithmetic import ARITHMETIC
from grafy_workbench.image import IMAGES
from grafy_core.operators.modules import MODULE_BOUNDARY_REGISTRATIONS
from grafy_workbench.schema import SCHEMAS
from grafy_workbench.sequence import SEQUENCES
from grafy_workbench.text import TEXT
from grafy_core.plugins import NodeCachePolicy


def test_builtin_node_cache_policy_inventory_is_fail_closed() -> None:
    policies = {
        registration.key: registration.cache_policy
        for registration in (
            *IMAGES.nodes,
            *MODULE_BOUNDARY_REGISTRATIONS,
            *SEQUENCES.nodes,
            *ARITHMETIC.nodes,
            *TEXT.nodes,
            *SCHEMAS.nodes,
        )
    }

    assert policies == {
        ("image.decode", 1): NodeCachePolicy.NEVER,
        ("module.input", 1): NodeCachePolicy.NEVER,
        ("module.output", 1): NodeCachePolicy.EXACT,
        ("sequence.collect", 1): NodeCachePolicy.EXACT,
        ("sequence.count", 1): NodeCachePolicy.EXACT,
        ("sequence.slice", 1): NodeCachePolicy.EXACT,
        ("sequence.item_at", 1): NodeCachePolicy.EXACT,
        ("arithmetic.number", 1): NodeCachePolicy.EXACT,
        ("arithmetic.integer_sequence", 1): NodeCachePolicy.EXACT,
        ("arithmetic.add", 1): NodeCachePolicy.EXACT,
        ("arithmetic.subtract", 1): NodeCachePolicy.EXACT,
        ("arithmetic.multiply", 1): NodeCachePolicy.EXACT,
        ("arithmetic.sum", 1): NodeCachePolicy.EXACT,
        ("text.input", 1): NodeCachePolicy.EXACT,
        ("text.as_markdown", 1): NodeCachePolicy.EXACT,
        ("text.split", 1): NodeCachePolicy.EXACT,
        ("text.replace", 1): NodeCachePolicy.EXACT,
        ("text.join", 1): NodeCachePolicy.EXACT,
        ("schema.builder", 1): NodeCachePolicy.EXACT,
    }
