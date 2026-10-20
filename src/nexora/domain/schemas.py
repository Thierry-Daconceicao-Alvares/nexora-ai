"""What a purchase request contains, as received from the form, a CSV row,
the API or the n8n email intake."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AttachmentKind(StrEnum):
    QUOTE = "quote"
    BID_COMPARISON = "bid_comparison"
    AWARD_DECISION = "award_decision"
    SINGLE_SOURCE_JUSTIFICATION = "single_source_justification"
    CAPEX_APPROVAL = "capex_approval"
    SPECIFICATION = "specification"


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AttachmentKind
    file_name: str = Field(min_length=1, max_length=200)


class PurchaseRequestIn(BaseModel):
    """A submitted request. Types and bounds are checked here; the business
    checks (currency supported, department known, date in the future...) are
    in services.validation, so that every problem is reported at once."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    external_ref: str = Field(pattern=r"^PR-\d{4}-\d{5}$", examples=["PR-2026-00123"])
    department: str = Field(min_length=1, max_length=50)
    supplier_id: str = Field(min_length=1, max_length=20, examples=["SUP-0002"])
    item_category: str = Field(min_length=1, max_length=50, examples=["spare_parts"])
    item_code: str | None = Field(default=None, max_length=30, examples=["MRO-BRG-6205"])
    description: str = Field(min_length=10, max_length=2000)
    quantity: Decimal = Field(gt=0, le=1_000_000, max_digits=12, decimal_places=3)
    unit_price: Decimal = Field(gt=0, le=100_000_000, max_digits=14, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3, examples=["EUR"])
    justification: str = Field(min_length=10, max_length=2000)
    delivery_date: date
    is_capex: bool = False
    attachments: list[Attachment] = Field(default_factory=list, max_length=20)

    @property
    def amount(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))
