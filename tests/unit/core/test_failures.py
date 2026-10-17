from uuid import uuid4

import pytest
from pydantic import ValidationError

from grafy_core.domain.errors import (
    Failure,
    FailureKind,
    FailureSpec,
    NotFoundError,
)
from grafy_core.domain.module_library import ModuleLibraryError


def test_declared_failure_keeps_diagnostics_out_of_public_message() -> None:
    resource_id = str(uuid4())

    error = NotFoundError("Workspace", resource_id)

    assert resource_id in str(error)
    assert error.public_message == "Not found"
    assert error.failure_spec is not None
    assert error.failure_spec.code == "resource.not_found"
    assert error.failure_spec.kind is FailureKind.NOT_FOUND


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("not_namespaced", "Safe message"),
        ("Graph.NotFound", "Safe message"),
        ("graph.not-found", "Safe message"),
        ("graph.not_found", "   "),
        ("graph.not_found", "x" * 201),
    ],
)
def test_failure_spec_rejects_unstable_or_unsafe_values(
    code: str,
    message: str,
) -> None:
    with pytest.raises(ValueError):
        FailureSpec(
            code=code,
            kind=FailureKind.VALIDATION,
            public_message=message,
        )


def test_failure_is_frozen_and_rejects_extra_fields() -> None:
    failure = Failure(
        error_id=uuid4(),
        code="graph.not_found",
        kind=FailureKind.NOT_FOUND,
        message="Not found",
    )

    with pytest.raises(ValidationError):
        Failure.model_validate({**failure.model_dump(), "diagnostic": "secret"})
    with pytest.raises(ValidationError):
        failure.message = "Changed"  # type: ignore[misc]


def test_module_library_validation_is_not_declared_public() -> None:
    error = ModuleLibraryError("Module name contains internal detail")

    assert not hasattr(error, "public_message")
