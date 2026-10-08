from grafy_workbench.image import IMAGES
from grafy_core.operators.modules import MODULE_BOUNDARY_REGISTRATIONS
from grafy_workbench.schema import SCHEMAS
from grafy_workbench.text import TEXT
from grafy_workbench.value import VALUE
from grafy_core.plugins import NodeCachePolicy

from tests.support.scenarios.arithmetic import ARITHMETIC_TEST_PLUGIN


def test_builtin_node_cache_policy_inventory_is_fail_closed() -> None:
    policies = {
        registration.key: registration.cache_policy
        for registration in (
            *IMAGES.nodes,
            *MODULE_BOUNDARY_REGISTRATIONS,
            *VALUE.nodes,
            *TEXT.nodes,
            *SCHEMAS.nodes,
            *ARITHMETIC_TEST_PLUGIN.nodes,
        )
    }

    assert policies == {
        ("module.input", 1): NodeCachePolicy.NEVER,
        ("module.output", 1): NodeCachePolicy.EXACT,
        ("value.integer", 1): NodeCachePolicy.EXACT,
        ("test.arithmetic.integer_sequence", 1): NodeCachePolicy.EXACT,
        ("test.arithmetic.add", 1): NodeCachePolicy.EXACT,
        ("test.arithmetic.subtract", 1): NodeCachePolicy.EXACT,
        ("test.arithmetic.multiply", 1): NodeCachePolicy.EXACT,
        ("test.arithmetic.sum", 1): NodeCachePolicy.EXACT,
        ("text.input", 1): NodeCachePolicy.EXACT,
        ("text.as_markdown", 1): NodeCachePolicy.EXACT,
        ("text.split", 1): NodeCachePolicy.EXACT,
        ("text.replace", 1): NodeCachePolicy.EXACT,
        ("text.join", 1): NodeCachePolicy.EXACT,
        ("schema.builder", 1): NodeCachePolicy.EXACT,
    }
