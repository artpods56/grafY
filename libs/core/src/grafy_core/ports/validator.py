import abc
from typing import Protocol

class Validator[T](Protocol):
    @abc.abstractmethod
    async def validate(self, data: T) -> None:
        raise NotImplementedError
