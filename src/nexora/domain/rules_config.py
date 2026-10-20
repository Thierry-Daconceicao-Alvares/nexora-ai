"""The rule set of config/rules.yaml, validated when it is loaded."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from nexora.domain.models import Severity


class Band(BaseModel):
    from_eur: float = Field(ge=0)
    approvers: list[str]


class ApprovalBands(BaseModel):
    policy_ref: str
    bands: list[Band]

    @model_validator(mode="after")
    def ordered(self) -> ApprovalBands:
        starts = [b.from_eur for b in self.bands]
        if starts != sorted(starts) or starts[0] != 0:
            raise ValueError("approval bands must start at 0 and be in ascending order")
        return self

    def band_for(self, amount_eur: float) -> Band:
        return [b for b in self.bands if amount_eur >= b.from_eur][-1]


class Routing(BaseModel):
    approver_from_eur: float
    approver_from_severity: Severity


class SourcingLevel(BaseModel):
    from_eur: float = Field(ge=0)
    quotes: int = Field(ge=1)
    also: list[str] = []


class Sourcing(BaseModel):
    policy_ref: str
    levels: list[SourcingLevel]
    single_source_document: str

    def level_for(self, amount_eur: float) -> SourcingLevel:
        return [lv for lv in self.levels if amount_eur >= lv.from_eur][-1]


class Capex(BaseModel):
    policy_ref: str
    document: str


class PriceDeviation(BaseModel):
    policy_ref: str | None
    medium_pct: float
    high_pct: float


class Duplicates(BaseModel):
    policy_ref: str | None
    window_days: int
    amount_tolerance_pct: float
    min_description_similarity: float = Field(ge=0, le=1)


class Splitting(BaseModel):
    policy_ref: str
    window_days: int


class SupplierStatus(BaseModel):
    policy_ref: str


class RulesConfig(BaseModel):
    version: str
    base_currency: str
    fx_rates_to_eur: dict[str, float]
    departments: list[str]
    approval_bands: ApprovalBands
    routing: Routing
    sourcing: Sourcing
    capex: Capex
    price_deviation: PriceDeviation
    duplicates: Duplicates
    splitting: Splitting
    supplier_status: SupplierStatus

    def thresholds_eur(self) -> list[float]:
        """Every amount at which the sourcing or the approvers change."""
        values = {b.from_eur for b in self.approval_bands.bands}
        values |= {lv.from_eur for lv in self.sourcing.levels}
        return sorted(v for v in values if v > 0)


def load_rules(path: Path) -> RulesConfig:
    with path.open(encoding="utf-8") as handle:
        return RulesConfig.model_validate(yaml.safe_load(handle))
