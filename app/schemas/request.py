from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class Source(str, Enum):
    WEB = 'web'
    EXTERNAL = 'integracao_externa'


class ValidationRecordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    external_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices('external_id', 'id_registro'),
    )
    client_name: str = Field(
        min_length=1,
        validation_alias=AliasChoices(
            'client_name',
            'supplier_name',
            'nome_cliente',
            'nome_fornecedor',
        ),
    )
    cnpj: str = Field(min_length=1)
    phone: str = Field(
        min_length=1,
        validation_alias=AliasChoices('phone', 'telefone'),
    )
    email: str | None = Field(
        default=None,
        validation_alias=AliasChoices('email', 'e_mail', 'correio_eletronico'),
    )


class ValidationBatchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    batch_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices('batch_id', 'id_lote'),
    )
    source: Source = Field(validation_alias=AliasChoices('source', 'origem'))
    records: list[ValidationRecordRequest] = Field(min_length=1)


class SupplierValidationRecordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    external_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices('external_id', 'id_registro'),
    )
    supplier_name: str = Field(
        min_length=1,
        validation_alias=AliasChoices(
            'supplier_name',
            'client_name',
            'nome_fornecedor',
            'nome_cliente',
            'empresa',
            'nome',
        ),
    )
    phone: str = Field(
        min_length=1,
        validation_alias=AliasChoices('phone', 'telefone'),
    )
    email: str | None = Field(
        default=None,
        validation_alias=AliasChoices('email', 'e_mail', 'correio_eletronico'),
    )
    city: str | None = None
    state: str | None = None
    notes: str | None = None
    custom_fields: dict[str, str] | None = None


class SupplierValidationBatchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    batch_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices('batch_id', 'id_lote'),
    )
    source: Source = Field(validation_alias=AliasChoices('source', 'origem'))
    segment_name: str = Field(min_length=1)
    callback_phone: str = Field(min_length=1)
    callback_contact_name: str | None = None
    records: list[SupplierValidationRecordRequest] = Field(min_length=1)


class SupplierDiscoveryRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    segment_name: str = Field(min_length=2)
    callback_phone: str = Field(min_length=1)
    callback_contact_name: str | None = None
    region: str | None = None
    max_suppliers: int = Field(default=10, ge=1, le=50)
