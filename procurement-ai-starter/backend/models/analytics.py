from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from backend.models.purchase import StrictModel


class MerchandiseCurrencySnapshot(StrictModel):
    currency: str
    order_count: int = Field(ge=0)
    order_merchandise_total: Decimal = Field(ge=0)


class MerchandiseCurrencyOverview(MerchandiseCurrencySnapshot):
    average_order_merchandise_value: Decimal | None = Field(default=None, ge=0)


class ProcurementAnalyticsSnapshot(StrictModel):
    generated_at: datetime
    order_count: int = Field(ge=0)
    active_order_count: int = Field(ge=0)
    pending_approval_count: int = Field(ge=0)
    low_stock_count: int = Field(ge=0)
    stockout_count: int = Field(ge=0)
    delayed_supplier_count: int = Field(ge=0)
    delayed_shipment_count: int = Field(ge=0)
    reorder_analysis_count: int = Field(ge=0)
    received_unit_count: int = Field(ge=0)
    accepted_unit_count: int = Field(ge=0)
    damaged_unit_count: int = Field(ge=0)
    currency_merchandise_totals: list[MerchandiseCurrencySnapshot] = Field(default_factory=list)


class UnavailableMetric(StrictModel):
    value: None = None
    reason: str


class ProcurementOverview(ProcurementAnalyticsSnapshot):
    currency_merchandise_totals: list[MerchandiseCurrencyOverview] = Field(default_factory=list)
    damage_fraction: Decimal | None = Field(default=None, ge=0, le=1)
    savings: UnavailableMetric
    average_actual_delivery_days: UnavailableMetric
    supplier_reliability: UnavailableMetric
    calculation_notes: list[str] = Field(default_factory=list)
    source_label: Literal["LOCAL DEMO / MANUAL INPUT"] = "LOCAL DEMO / MANUAL INPUT"
