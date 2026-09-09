"""Shared SQL serialization for Pydantic models and string enums."""

from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy import JSON, String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class PydanticJSONType[T: BaseModel](TypeDecorator[T]):
    impl = JSON
    cache_ok = True
    model_type: type[T]

    def process_bind_param(
        self,
        value: T | None,
        dialect: Dialect,
    ) -> dict[str, object] | None:
        del dialect
        return None if value is None else value.model_dump(mode="json")

    def process_result_value(
        self,
        value: object | None,
        dialect: Dialect,
    ) -> T | None:
        del dialect
        return None if value is None else self.model_type.model_validate(value)


class StringEnumType[E: StrEnum](TypeDecorator[E]):
    impl = String
    cache_ok = True
    enum_type: type[E]

    def process_bind_param(
        self,
        value: E | None,
        dialect: Dialect,
    ) -> str | None:
        del dialect
        return None if value is None else self.enum_type(value).value

    def process_result_value(
        self,
        value: str | None,
        dialect: Dialect,
    ) -> E | None:
        del dialect
        return None if value is None else self.enum_type(value)
