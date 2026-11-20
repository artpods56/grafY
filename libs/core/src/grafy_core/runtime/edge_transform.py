"""One incoming edge's projection and conversion, applied to a loaded value.

The edge resolver keeps the stored ref. This describes how that ref becomes the
value a port receives, and it raises with the same failure text the resolver
used when it still wrote the converted artifact.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from pydantic import BaseModel

from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.conversions import Conversion
from grafy_core.domain.errors import NotFoundError
from grafy_core.runtime.resolvers import ArtifactContractError

if TYPE_CHECKING:
    from grafy_core.runtime.artifact_values import ArtifactValues


class EdgeTransformError(RuntimeError):
    """A projection or conversion failed. The message is the failure text."""


@dataclass(frozen=True, slots=True)
class EdgeTransform:
    """How one edge turns a stored ref into the value a port receives.

    ``delivered`` is the artifact type after the projection and the conversion
    chain. ``label`` is the connection name used in a failure message.
    """

    projection_path: tuple[str, ...] | None
    conversions: tuple[Conversion[Any, Any], ...]
    delivered: ArtifactTypeKey
    label: str

    @property
    def rewrites(self) -> bool:
        return self.projection_path is not None or len(self.conversions) > 0


async def apply_edge_transform(
    values: "ArtifactValues",
    ref: ArtifactRef,
    transform: EdgeTransform,
    workspace_id: UUID,
    *,
    item_index: int | None,
) -> object:
    """Load ``ref`` and run ``transform``. The ref's own row is unchanged."""

    item_context = "" if item_index is None else f" at sequence item {item_index}"
    try:
        loaded = await values.resolve(ref, workspace_id)
    except Exception as exc:
        raise _load_error(exc, ref, transform, item_context) from exc
    if transform.projection_path is not None:
        loaded = _project(loaded, transform.projection_path, ref)
    return await _convert(loaded, ref, transform, item_context)


def _load_error(
    exc: Exception,
    ref: ArtifactRef,
    transform: EdgeTransform,
    item_context: str,
) -> EdgeTransformError:
    path = transform.projection_path
    if path is not None:
        if isinstance(exc, NotFoundError):
            return EdgeTransformError(
                f"Cannot project missing source artifact {ref.artifact_id} for "
                f"{transform.label}"
            )
        text = str(exc)
        if isinstance(exc, ArtifactContractError) and "different artifact ref" in text:
            return EdgeTransformError(
                f"Cannot project source artifact {ref.artifact_id}: repository "
                "ref does not match the value the connection carries"
            )
        if "inline JSON payload" in text:
            return EdgeTransformError(
                f"Cannot project {'.'.join(path)!r} from artifact "
                f"{ref.artifact_id}: source has no inline JSON payload"
            )
        return EdgeTransformError(
            f"Cannot project {'.'.join(path)!r} from artifact {ref.artifact_id}"
        )
    return EdgeTransformError(
        f"Failed to resolve artifact {ref.artifact_id}{item_context} for "
        f"the conversion path on {transform.label}"
    )


def _project(
    value: object,
    path: tuple[str, ...],
    ref: ArtifactRef,
) -> object:
    if isinstance(value, BaseModel):
        current: object = cast(object, value.model_dump())
    else:
        current = value
    for segment in path:
        if not isinstance(current, dict):
            raise EdgeTransformError(
                f"Cannot project {'.'.join(path)!r} from artifact "
                f"{ref.artifact_id}: {segment!r} is not inside a JSON object"
            )
        mapping = cast(dict[object, object], current)
        if segment not in mapping:
            raise EdgeTransformError(
                f"Cannot project {'.'.join(path)!r} from artifact "
                f"{ref.artifact_id}: field {segment!r} is missing"
            )
        current = mapping[segment]
    return current


async def _convert(
    value: object,
    ref: ArtifactRef,
    transform: EdgeTransform,
    item_context: str,
) -> object:
    converted = value
    conversions: Sequence[Conversion[Any, Any]] = transform.conversions
    for step_index, conversion in enumerate(conversions):
        try:
            converted = await conversion.convert(cast(Any, converted))
        except Exception as exc:
            raise EdgeTransformError(
                f"Failed conversion step {step_index + 1}/{len(conversions)} "
                f"{conversion.id!r}@{conversion.version} for artifact "
                f"{ref.artifact_id}{item_context} on {transform.label}"
            ) from exc
    return converted


__all__ = ["EdgeTransform", "EdgeTransformError", "apply_edge_transform"]
