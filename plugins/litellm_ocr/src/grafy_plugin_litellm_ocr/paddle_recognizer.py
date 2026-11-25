"""Cyrillic crop recognition over the deployment's scoped LiteLLM route."""

from asyncio import AbstractEventLoop, Semaphore, get_running_loop
from base64 import b64encode
from collections.abc import Sequence
from typing import final, override
from weakref import WeakValueDictionary

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.contracts.ocr import CropTextReader, ServiceCacheIdentity, TextReading
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.node_context import UserFacingNodeError
from grafy_core.nodes import (
    Node,
    NodeExecutionContext,
    active_node_context,
    emit_node_progress,
)
from grafy_core.plugins import (
    NodeHttpEgressContract,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from grafy_plugin_litellm_ocr.auth import API_KEY, LITELLM_ORIGIN
from grafy_plugin_litellm_ocr.declaration import LITELLM_OCR
from grafy_core.provider_http import ProviderRequest, post_json

PADDLE_URL = f"{LITELLM_ORIGIN}/v1/ocr/cyrillic/recognize"
PADDLE_MODEL = (
    "cyrillic_PP-OCRv5_mobile_rec@sha256:"
    "434dc9fa2a99fa3653e08f8cf793ae56be7dd41c35c4980e6255147cc02bbc80"
)
_MAX_PNG_BYTES = 4 * 1024**2
_MAX_ENCODED_BYTES = 4 * ((_MAX_PNG_BYTES + 2) // 3)
_MAX_BATCH_SIZE = 8
_MAX_RESPONSE_BYTES = 1024**2
_slots: WeakValueDictionary[AbstractEventLoop, Semaphore] = WeakValueDictionary()


def _recognizer_slot() -> Semaphore:
    """One batch at a time per event loop: recognition answers in arrival order."""
    loop = get_running_loop()
    slot = _slots.get(loop)
    if slot is None:
        slot = Semaphore(1)
        _slots[loop] = slot
    return slot


class PaddleBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[TextReading]


@final
class PaddleCyrillicRecognizer(CropTextReader):
    def cache_identity(self) -> ServiceCacheIdentity:
        return ServiceCacheIdentity("paddle.ai-test-ihpan", PADDLE_MODEL, {})

    def __init__(
        self, api_key: SecretStr, *, timeout_ms: int, max_retries: int
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_ms / 1_000
        self._attempts = max_retries + 1

    async def recognize(self, crops: Sequence[bytes]) -> list[TextReading]:
        """One reading per crop, in input order.

        Deliberately uncached: the node that cuts a crop already keeps its reading
        against the crop's digest (see `tiff_recognition._recognizer_spec`), so a cache
        here would hold the same answers under a second key and neither one could be
        told stale. What this method owns is the shape of the request: batches the
        route accepts, one of them in flight at a time.
        """

        results: list[TextReading] = []
        batch: list[str] = []
        encoded_size = 0
        total = len(crops)
        context = active_node_context()

        async def flush() -> None:
            nonlocal batch, encoded_size
            if not batch:
                return
            await emit_node_progress(
                context,
                "Calling Cyrillic OCR…",
                current=len(results),
                total=total,
            )
            results.extend(await self._recognize_batch(batch))
            batch = []
            encoded_size = 0

        for crop in crops:
            if len(crop) > _MAX_PNG_BYTES:
                raise UserFacingNodeError("A TIFF crop exceeds the OCR image limit")
            encoded = b64encode(crop).decode("ascii")
            if (
                len(batch) == _MAX_BATCH_SIZE
                or encoded_size + len(encoded) > _MAX_ENCODED_BYTES
            ):
                await flush()
            batch.append(encoded)
            encoded_size += len(encoded)
        await flush()
        if total:
            await emit_node_progress(
                context,
                "Calling Cyrillic OCR…",
                current=len(results),
                total=total,
            )
        return results

    async def _recognize_batch(self, batch: list[str]) -> list[TextReading]:
        body = await post_json(
            ProviderRequest(
                service="Cyrillic OCR",
                url=PADDLE_URL,
                payload={"images_base64": batch},
                api_key=self._api_key,
                attempts=self._attempts,
                timeout_seconds=self._timeout_seconds,
                max_response_bytes=_MAX_RESPONSE_BYTES,
                slot=_recognizer_slot,
            )
        )
        try:
            result = PaddleBatchResponse.model_validate_json(body)
        except ValidationError as exc:
            raise UserFacingNodeError("Cyrillic OCR returned invalid readings") from exc
        if len(result.results) != len(batch):
            raise UserFacingNodeError(
                "Cyrillic OCR returned the wrong number of readings"
            )
        if any(item.model != PADDLE_MODEL for item in result.results):
            raise UserFacingNodeError(
                "Cyrillic OCR returned an unexpected model revision"
            )
        return result.results


class PaddleConfig(NodeConfig):
    timeout_ms: int = Field(
        title="Time limit (ms)",
        json_schema_extra={"x-grafy-advanced": True},
        default=120_000,
        ge=1_000,
        le=900_000,
        description="Maximum Cyrillic OCR request time in milliseconds.",
    )
    max_retries: int = Field(
        title="Max retries",
        json_schema_extra={"x-grafy-advanced": True},
        default=2,
        ge=0,
        le=5,
        description=(
            "Additional attempts after a timeout, connection failure, or retryable "
            "HTTP status. Recognizing the same crops twice returns the same "
            "readings, so a retry costs provider time and changes nothing else."
        ),
    )


class PaddleInput(NodeInput):
    pass


class PaddleOutput(NodeOutput):
    recognizer: PaddleCyrillicRecognizer = Field(title="Text recognizer")


@LITELLM_OCR.node(
    operator_id="ocr.paddle_cyrillic_provider",
    version=1,
    title="PaddleOCR Cyrillic recognizer",
    required_capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
    http_egress=NodeHttpEgressContract(
        fixed_destinations=(LITELLM_ORIGIN,)
    ),
    secret_inputs=(API_KEY,),
)
@final
class PaddleProviderNode(Node[PaddleConfig, PaddleInput, PaddleOutput]):
    """Provide a Paddle Cyrillic text recognizer."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: PaddleConfig,
        _inputs: PaddleInput,
        /,
    ) -> PaddleOutput:
        return PaddleOutput(
            recognizer=PaddleCyrillicRecognizer(
                await context.secrets.require(API_KEY.name),
                timeout_ms=config.timeout_ms,
                max_retries=config.max_retries,
            )
        )
