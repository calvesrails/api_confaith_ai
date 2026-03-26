from __future__ import annotations

from enum import Enum

from sqlalchemy.types import String, TypeDecorator


class FlexibleEnum(TypeDecorator):
    impl = String
    cache_ok = True

    def __init__(self, enum_cls: type[Enum], length: int = 64) -> None:
        self.enum_cls = enum_cls
        super().__init__(length=length)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value.value
        if isinstance(value, str):
            try:
                return self.enum_cls(value).value
            except ValueError:
                try:
                    return self.enum_cls[value].value
                except KeyError:
                    return value
        raise TypeError(f"Valor invalido para {self.enum_cls.__name__}: {value!r}")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value
        try:
            return self.enum_cls(value)
        except ValueError:
            try:
                return self.enum_cls[value]
            except KeyError as exc:
                raise LookupError(
                    f"{value!r} nao corresponde a nenhum valor de {self.enum_cls.__name__}"
                ) from exc
