from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class Source(str, Enum):
    WEB = "web"
    EXTERNAL = "integracao_externa"


class ValidationRecordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    external_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("external_id", "id_registro"),
    )
    supplier_name: str = Field(
        min_length=1,
        validation_alias=AliasChoices("supplier_name", "nome_fornecedor"),
    )
    cnpj: str = Field(min_length=1)
    phone: str = Field(
        min_length=1,
        validation_alias=AliasChoices("phone", "telefone"),
    )


class ValidationBatchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    batch_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("batch_id", "id_lote"),
    )
    source: Source = Field(validation_alias=AliasChoices("source", "origem"))
    records: list[ValidationRecordRequest] = Field(min_length=1)
