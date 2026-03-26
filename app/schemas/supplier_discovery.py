from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SupplierDiscoveryCandidate(BaseModel):
    supplier_name: str = Field(min_length=1)
    phone: str | None = None
    website: str | None = None
    city: str | None = None
    state: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    discovery_confidence: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = None


class SupplierDiscoveryResponse(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    search_id: str
    mode: str
    segment_name: str
    region: str | None = None
    callback_phone: str
    callback_contact_name: str | None = None
    generated_at: datetime
    total_suppliers: int
    suppliers: list[SupplierDiscoveryCandidate]
    downloadable_file_url: str
    message: str | None = None
