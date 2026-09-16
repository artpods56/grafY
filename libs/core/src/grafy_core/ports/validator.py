import abc
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Sequence
from typing import Protocol, final

class SkipItem(Exception):
    """Raised by a validator when an item should be skipped."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Validator[T](Protocol):
    @abc.abstractmethod
    async def validate(self, data: T) -> None:
        raise NotImplementedError

    async def validate_iter(
        self,
        items: Iterable[T],
    ) -> AsyncIterator[T]:
        for item in items:
            try:
                await self.validate(item)
            except SkipItem:
                continue

            yield item

    async def validate_async_iter(
        self,
        items: AsyncIterable[T],
    ) -> AsyncIterator[T]:
        async for item in items:
            try:
                await self.validate(item)
            except SkipItem:
                continue

            yield item


@final
class ComposedValidator[T](Validator[T]):
    def __init__(
        self,
        validators: Sequence[Validator[T]],
    ) -> None:
        self.validators = validators

    async def validate(self, data: T) -> None:
        for validator in self.validators:
            await validator.validate(data)
