from typing import cast

import pytest

from grafy_core.artifact_contracts import INTEGER_VALUE, TEXT_VALUE
from grafy_core.canonical_conversions import (
    CANONICAL_ARTIFACT_CONVERSIONS,
    CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY,
    INTEGER_TO_TEXT,
)


def test_integer_to_text_is_an_exact_deployment_owned_conversion() -> None:
    assert CANONICAL_ARTIFACT_CONVERSIONS == (INTEGER_TO_TEXT,)
    assert CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY == {
        INTEGER_TO_TEXT.key: INTEGER_TO_TEXT
    }
    assert INTEGER_TO_TEXT.key.id == "builtin.scalar.integer_to_text"
    assert INTEGER_TO_TEXT.key.version == 1
    assert INTEGER_TO_TEXT.source == INTEGER_VALUE.key
    assert INTEGER_TO_TEXT.target == TEXT_VALUE.key
    assert INTEGER_TO_TEXT.source_type is int
    assert INTEGER_TO_TEXT.target_type is str
    assert INTEGER_TO_TEXT.title == "As text"
    assert INTEGER_TO_TEXT.convert(42) == "42"


def test_canonical_conversion_registry_is_immutable() -> None:
    mutable_view = cast(dict[object, object], CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY)

    with pytest.raises(TypeError):
        mutable_view[INTEGER_TO_TEXT.key] = INTEGER_TO_TEXT
