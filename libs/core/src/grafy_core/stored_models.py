"""Read stored Pydantic models after checking their recorded byte identity."""

from hashlib import sha256

from pydantic import BaseModel

from grafy_core.ports.storage import FileStoragePort


async def load_stored_model[ModelT: BaseModel](
    storage: FileStoragePort,
    *,
    bucket: str,
    object_key: str,
    model: type[ModelT],
    expected_byte_size: int | None = None,
    expected_sha256: str | None = None,
) -> ModelT:
    stream = await storage.load(bucket=bucket, path=object_key)
    try:
        content = stream.read()
    finally:
        stream.close()
    if expected_byte_size is not None and len(content) != expected_byte_size:
        raise ValueError(
            f"Stored object {object_key!r} contains {len(content)} bytes, "
            f"expected {expected_byte_size}"
        )
    if expected_sha256 is not None:
        observed_sha256 = sha256(content).hexdigest()
        if observed_sha256 != expected_sha256:
            raise ValueError(
                f"Stored object {object_key!r} has SHA-256 {observed_sha256}, "
                f"expected {expected_sha256}"
            )
    return model.model_validate_json(content)

