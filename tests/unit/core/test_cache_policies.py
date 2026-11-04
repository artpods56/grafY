from grafy_workbench.image import IMAGES
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
            *VALUE.nodes,
            *TEXT.nodes,
            *SCHEMAS.nodes,
            *ARITHMETIC_TEST_PLUGIN.nodes,
        )
    }

    assert policies == {
        ("value.integer", 1): NodeCachePolicy.EXACT,
        ("test.arithmetic.integer_sequence", 1): NodeCachePolicy.EXACT,
        ("test.arithmetic.add", 1): NodeCachePolicy.EXACT,
        ("test.arithmetic.subtract", 1): NodeCachePolicy.EXACT,
        ("test.arithmetic.multiply", 1): NodeCachePolicy.EXACT,
        ("test.arithmetic.sum", 1): NodeCachePolicy.EXACT,
        ("text.input", 1): NodeCachePolicy.EXACT,
        ("schema.builder", 1): NodeCachePolicy.EXACT,
    }
