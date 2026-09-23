from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserContext(StrictModel):
    user_id: str = "demo-user"
    user_type: Literal["personal", "business"] = "business"
    organization_id: str | None = "demo-organization"
    department: str | None = None
    permissions: set[str] = Field(default_factory=set)
    currency: str = "KZT"


class PurchaseRequest(StrictModel):
    product_query: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, gt=0, le=1_000_000)
    budget_total: Decimal | None = Field(default=None, gt=0)
    budget_per_unit: Decimal | None = Field(default=None, gt=0)
    currency: str = Field(default="KZT", min_length=3, max_length=3)
    max_delivery_days: int | None = Field(default=None, gt=0, le=3650)
    required_specs: dict[str, Any] = Field(default_factory=dict)
    preferred_brand: str | None = None
    priority: Literal["price", "balanced", "speed", "quality"] = "balanced"
    user_context: UserContext = Field(default_factory=UserContext)
    source_text: str | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class Product(StrictModel):
    id: int = Field(gt=0)
    name: str
    category: str
    brand: str | None = None
    model: str | None = None
    sku: str | None = None
    ram_gb: int | None = Field(default=None, gt=0)
    ssd_gb: int | None = Field(default=None, gt=0)
    capacity_gb: int | None = Field(default=None, gt=0)
    interface: str | None = None
    data_source: str = "DEMO DATA"


class Supplier(StrictModel):
    id: int = Field(gt=0)
    name: str
    reliability: float | None = Field(default=None, ge=0, le=1)
    rating: float | None = Field(default=None, ge=0, le=5)
    successful_deliveries: int | None = Field(default=None, ge=0)
    late_deliveries: int | None = Field(default=None, ge=0)
    average_delay_days: float | None = Field(default=None, ge=0)
    defect_rate: float | None = Field(default=None, ge=0, le=1)
    return_rate: float | None = Field(default=None, ge=0, le=1)
    data_source: str = "DEMO DATA"


class Offer(StrictModel):
    id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    supplier_id: int = Field(gt=0)
    unit_price: Decimal = Field(gt=0)
    quantity_available: int = Field(ge=0)
    delivery_days: int = Field(ge=0)
    warranty_months: int = Field(ge=0)
    minimum_order_quantity: int = Field(default=1, ge=1)
    shipping_cost: Decimal | None = Field(default=None, ge=0)
    tax_rate: Decimal | None = Field(default=None, ge=0)
    currency: str = "KZT"
    data_source: str = "DEMO DATA"


class OfferMatch(StrictModel):
    offer: Offer
    product: Product
    supplier: Supplier
    match_type: Literal["exact", "partial", "compatible", "analogue", "unsuitable"]
    hard_requirements_met: bool
    matched_specs: dict[str, str]
    unmet_specs: list[str]
    soft_score: float = Field(ge=0, le=1)


class SupplierAssessment(StrictModel):
    supplier_id: int
    supplier_name: str
    data_status: Literal["available", "insufficient_data"]
    delivery_rate: float | None = Field(default=None, ge=0, le=1)
    late_delivery_rate: float | None = Field(default=None, ge=0, le=1)
    average_delay_days: float | None = Field(default=None, ge=0)
    defect_rate: float | None = Field(default=None, ge=0, le=1)
    return_rate: float | None = Field(default=None, ge=0, le=1)
    demo_rating: float | None = Field(default=None, ge=0, le=5)
    demo_reliability: float | None = Field(default=None, ge=0, le=1)
    evidence_note: str


class PriceHistoryRecord(StrictModel):
    offer_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    supplier_id: int = Field(gt=0)
    observed_on: date
    unit_price: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    data_source: Literal["DEMO DATA"] = "DEMO DATA"


class PriceHistoryComparison(StrictModel):
    offer_id: int = Field(gt=0)
    currency: str
    current_unit_price: Decimal = Field(gt=0)
    status: Literal["unknown", "within_range", "above_history", "below_history"]
    sample_count: int = Field(ge=0)
    minimum_observations: int = 3
    as_of: date
    window_start: date
    history_from: date | None = None
    history_to: date | None = None
    median_historical_unit_price: Decimal | None = Field(default=None, gt=0)
    deviation_percent: Decimal | None = None
    anomaly_threshold_percent: Decimal = Decimal("20")
    source_label: Literal["DEMO DATA"] = "DEMO DATA"


class PriceSummary(StrictModel):
    currency: str
    offer_count: int = Field(ge=0)
    minimum_unit_price: Decimal | None = None
    maximum_unit_price: Decimal | None = None
    average_unit_price: Decimal | None = None
    median_unit_price: Decimal | None = None
    shipping_tax_status: str = "unknown and excluded"
    history_comparisons: list[PriceHistoryComparison] = Field(default_factory=list)


class PurchaseLine(StrictModel):
    offer_id: int
    product_id: int
    product_name: str
    supplier_id: int
    supplier_name: str
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(gt=0)
    merchandise_subtotal: Decimal = Field(ge=0)
    delivery_days: int = Field(ge=0)
    warranty_months: int = Field(ge=0)
    match_type: str
    match_score: float = Field(ge=0, le=1)
    optimization_score: float = Field(ge=0, le=1)
    data_source: str = "DEMO DATA"


class ValidationFinding(StrictModel):
    code: str
    severity: Literal["error", "warning", "info"]
    message: str


class RiskAssessment(StrictModel):
    risk_type: Literal[
        "supplier", "delivery", "price", "availability", "single_supplier", "concentration"
    ]
    severity: Literal["low", "medium", "high", "unknown"]
    reason: str
    evidence: list[str] = Field(default_factory=list)
    entity_id: str | None = None


class ComplianceFinding(StrictModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    evidence: list[str] = Field(default_factory=list)


class ApprovalRecord(StrictModel):
    approval_id: str
    plan_id: str
    status: Literal["PENDING", "APPROVED", "REJECTED"]
    required_role: str
    requested_by: str
    amount: Decimal = Field(ge=0)
    currency: str
    created_at: str
    decided_by: str | None = None
    decided_role: str | None = None
    decision_comment: str | None = None
    decided_at: str | None = None


class ApprovalDecision(StrictModel):
    decision: Literal["approved", "rejected"]
    reviewer_id: str = Field(min_length=1, max_length=100)
    reviewer_role: str = Field(min_length=1, max_length=50)
    comment: str | None = Field(default=None, max_length=1000)


class OrderDraftUpdate(StrictModel):
    buyer_note: str | None = Field(default=None, max_length=1000)


class DeliveryUpdate(StrictModel):
    supplier_id: int = Field(gt=0)
    status: Literal["ORDERED", "SHIPPED", "DELAYED", "DELIVERED", "CANCELLED"]
    expected_at: str | None = None
    actual_at: str | None = None
    tracking_number: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)
    source_label: Literal["MANUAL INPUT"] = "MANUAL INPUT"

    @model_validator(mode="after")
    def require_delay_evidence(self) -> "DeliveryUpdate":
        if self.status in {"DELAYED", "CANCELLED"} and not self.note:
            raise ValueError("A note is required when a delivery is delayed or cancelled")
        return self


class ReceivingLineInput(StrictModel):
    order_item_id: int = Field(gt=0)
    quantity_received: int = Field(gt=0)
    damaged_quantity: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def damaged_cannot_exceed_received(self) -> "ReceivingLineInput":
        if self.damaged_quantity > self.quantity_received:
            raise ValueError("damaged_quantity cannot exceed quantity_received")
        return self


class ReceivingRequest(StrictModel):
    received_at: str | None = None
    note: str | None = Field(default=None, max_length=1000)
    items: list[ReceivingLineInput] = Field(min_length=1)


class PurchaseOrderItemRecord(StrictModel):
    id: int = Field(gt=0)
    order_id: str
    offer_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    supplier_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(gt=0)
    merchandise_subtotal: Decimal = Field(ge=0)
    product_name: str | None = None
    supplier_name: str | None = None


class PurchaseOrder(StrictModel):
    order_id: str
    plan_id: str
    status: Literal[
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "ORDERED", "SHIPPED",
        "DELAYED", "DELIVERED", "RECEIVED", "CANCELLED"
    ]
    external_order_created: bool = False
    buyer_note: str | None = None
    items: list[PurchaseOrderItemRecord] = Field(default_factory=list)
    created_at: str
    updated_at: str
    source_label: Literal["LOCAL DRAFT"] = "LOCAL DRAFT"


class DeliveryEvent(StrictModel):
    event_id: str
    order_id: str
    supplier_id: int = Field(gt=0)
    status: Literal["ORDERED", "SHIPPED", "DELAYED", "DELIVERED", "CANCELLED"]
    expected_at: str | None = None
    actual_at: str | None = None
    tracking_number: str | None = None
    note: str | None = None
    source_label: Literal["MANUAL INPUT"] = "MANUAL INPUT"
    created_at: str


class PurchaseOrderSummary(StrictModel):
    order_id: str
    plan_id: str
    status: Literal[
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "ORDERED", "SHIPPED",
        "DELAYED", "DELIVERED", "RECEIVED", "CANCELLED"
    ]
    external_order_created: bool = False
    buyer_note: str | None = None
    created_at: str
    updated_at: str
    item_count: int = Field(ge=0)
    source_label: Literal["LOCAL DRAFT"] = "LOCAL DRAFT"


class ReplanResult(StrictModel):
    order_id: str
    excluded_supplier_ids: list[int]
    replaced_quantity: int = Field(gt=0)
    replacement_plan: PurchasePlan


class ReplanRequest(StrictModel):
    exclude_supplier_ids: list[int] = Field(default_factory=list)


class ReceivingRecord(StrictModel):
    receiving_id: str
    order_id: str
    order_item_id: int
    product_id: int
    expected_quantity: int = Field(ge=0)
    received_quantity: int = Field(gt=0)
    damaged_quantity: int = Field(ge=0)
    accepted_quantity: int = Field(ge=0)
    received_at: str
    note: str | None = None
    source_label: Literal["MANUAL INPUT"] = "MANUAL INPUT"


class InvoiceLineInput(StrictModel):
    order_item_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(gt=0)


class InvoiceSubmission(StrictModel):
    supplier_id: int = Field(gt=0)
    invoice_number: str = Field(min_length=1, max_length=100)
    invoice_date: str = Field(min_length=10, max_length=10)
    currency: str = Field(default="KZT", min_length=3, max_length=3)
    subtotal: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)
    shipping_amount: Decimal = Field(default=Decimal("0"), ge=0)
    total_amount: Decimal = Field(ge=0)
    items: list[InvoiceLineInput] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("currency")
    @classmethod
    def normalize_invoice_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("invoice_date")
    @classmethod
    def validate_invoice_date(cls, value: str) -> str:
        from datetime import date

        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("invoice_date must be an ISO calendar date (YYYY-MM-DD)") from exc
        if parsed.isoformat() != value:
            raise ValueError("invoice_date must use YYYY-MM-DD format")
        return value

    @field_validator("invoice_number")
    @classmethod
    def trim_invoice_number(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("invoice_number cannot be blank")
        return cleaned

    @model_validator(mode="after")
    def unique_invoice_items(self) -> "InvoiceSubmission":
        identifiers = [item.order_item_id for item in self.items]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Each order item can appear only once per invoice")
        return self


class InvoiceLineRecord(StrictModel):
    id: int = Field(gt=0)
    invoice_id: str
    order_item_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(gt=0)
    line_total: Decimal = Field(ge=0)


class InvoiceFinding(StrictModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    order_item_id: int | None = None


class PurchaseInvoice(StrictModel):
    invoice_id: str
    order_id: str
    supplier_id: int = Field(gt=0)
    supplier_name: str | None = None
    invoice_number: str
    invoice_date: str
    currency: str
    subtotal: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(ge=0)
    shipping_amount: Decimal = Field(ge=0)
    total_amount: Decimal = Field(ge=0)
    status: Literal["PENDING_RECEIVING", "MATCHED", "VARIANCE"]
    payment_status: Literal["NOT_PAID"] = "NOT_PAID"
    findings: list[InvoiceFinding] = Field(default_factory=list)
    items: list[InvoiceLineRecord] = Field(default_factory=list)
    note: str | None = None
    source_label: Literal["MANUAL INPUT"] = "MANUAL INPUT"
    created_at: str
    reviewed_at: str


class CurrencyFinanceSummary(StrictModel):
    currency: str
    ordered_subtotal: Decimal = Field(ge=0)
    invoiced_total: Decimal = Field(ge=0)
    matched_invoice_total: Decimal = Field(ge=0)
    variance_invoice_total: Decimal = Field(ge=0)
    pending_invoice_total: Decimal = Field(ge=0)


class SupplierFinanceSummary(StrictModel):
    supplier_id: int = Field(gt=0)
    supplier_name: str
    currency: str
    ordered_subtotal: Decimal = Field(ge=0)
    invoiced_total: Decimal = Field(ge=0)


class ProcurementFinanceSummary(StrictModel):
    order_count: int = Field(ge=0)
    invoice_count: int = Field(ge=0)
    invoice_status_counts: dict[str, int] = Field(default_factory=dict)
    currency_totals: list[CurrencyFinanceSummary] = Field(default_factory=list)
    supplier_totals: list[SupplierFinanceSummary] = Field(default_factory=list)
    received_unit_count: int = Field(ge=0)
    accepted_unit_count: int = Field(ge=0)
    damaged_unit_count: int = Field(ge=0)
    source_label: Literal["LOCAL DEMO / MANUAL INPUT"] = "LOCAL DEMO / MANUAL INPUT"


class WishlistEntryInput(StrictModel):
    user_id: str = Field(default="demo-user", min_length=1, max_length=100)
    product_id: int = Field(gt=0)
    offer_id: int | None = Field(default=None, gt=0)
    target_price: Decimal | None = Field(default=None, gt=0)
    currency: str = Field(default="KZT", min_length=3, max_length=3)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("currency")
    @classmethod
    def normalize_wishlist_currency(cls, value: str) -> str:
        return value.upper()


class WishlistEntry(StrictModel):
    wishlist_id: str
    user_id: str
    product_id: int = Field(gt=0)
    product_name: str
    offer_id: int | None = None
    supplier_id: int | None = None
    supplier_name: str | None = None
    current_price: Decimal | None = Field(default=None, ge=0)
    target_price: Decimal | None = Field(default=None, gt=0)
    currency: str
    note: str | None = None
    created_at: str
    source_label: Literal["DEMO DATA"] = "DEMO DATA"


class PriceWatchInput(StrictModel):
    user_id: str = Field(default="demo-user", min_length=1, max_length=100)
    product_id: int = Field(gt=0)
    offer_id: int | None = Field(default=None, gt=0)
    target_price: Decimal = Field(gt=0)
    currency: str = Field(default="KZT", min_length=3, max_length=3)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("currency")
    @classmethod
    def normalize_watch_currency(cls, value: str) -> str:
        return value.upper()


class PriceWatch(StrictModel):
    watch_id: str
    user_id: str
    product_id: int = Field(gt=0)
    product_name: str
    offer_id: int | None = None
    target_price: Decimal = Field(gt=0)
    baseline_price: Decimal = Field(gt=0)
    last_observed_price: Decimal | None = Field(default=None, ge=0)
    currency: str
    status: Literal["ACTIVE", "TRIGGERED", "PAUSED"]
    note: str | None = None
    created_at: str
    updated_at: str
    source_label: Literal["LOCAL DEMO CATALOG"] = "LOCAL DEMO CATALOG"


class PriceWatchEvent(StrictModel):
    event_id: str
    watch_id: str
    user_id: str
    product_id: int
    product_name: str
    event_type: Literal["PRICE_DROP", "TARGET_REACHED"]
    previous_price: Decimal | None = Field(default=None, ge=0)
    current_price: Decimal = Field(ge=0)
    target_price: Decimal = Field(gt=0)
    currency: str
    change_amount: Decimal
    occurred_at: str
    source_label: Literal["LOCAL DEMO CATALOG"] = "LOCAL DEMO CATALOG"


class PriceWatchEvaluation(StrictModel):
    evaluated_count: int = Field(ge=0)
    alert_count: int = Field(ge=0)
    alerts: list[PriceWatchEvent] = Field(default_factory=list)
    source_label: Literal["LOCAL DEMO CATALOG"] = "LOCAL DEMO CATALOG"


class PriceWatchStatusUpdate(StrictModel):
    status: Literal["ACTIVE", "PAUSED"]


class PurchaseReminderInput(StrictModel):
    user_id: str = Field(default="demo-user", min_length=1, max_length=100)
    product_id: int | None = Field(default=None, gt=0)
    product_query: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: int = Field(default=1, gt=0, le=1000000)
    remind_at: datetime
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("remind_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("remind_at must include a timezone offset")
        return value

    @field_validator("product_query")
    @classmethod
    def trim_product_query(cls, value: str | None) -> str | None:
        cleaned = value.strip() if value is not None else None
        return cleaned or None

    @model_validator(mode="after")
    def require_exactly_one_product_reference(self) -> "PurchaseReminderInput":
        if self.product_id is None and not self.product_query:
            raise ValueError("Provide product_id or product_query")
        if self.product_id is not None and self.product_query:
            raise ValueError("Provide product_id or product_query, not both")
        return self


class PurchaseReminderUpdate(StrictModel):
    status: Literal["COMPLETED", "CANCELLED"]
    note: str | None = Field(default=None, max_length=1000)


class PurchaseReminder(StrictModel):
    reminder_id: str
    user_id: str
    product_id: int | None = None
    product_name: str | None = None
    product_query: str | None = None
    quantity: int = Field(gt=0)
    remind_at: datetime
    status: Literal["SCHEDULED", "DUE", "COMPLETED", "CANCELLED"]
    note: str | None = None
    created_at: str
    closed_at: str | None = None
    source_label: Literal["LOCAL REMINDER"] = "LOCAL REMINDER"


class ApprovalThreshold(StrictModel):
    max_amount: Decimal | None = Field(default=None, ge=0)
    role: str | None = Field(default=None, min_length=1, max_length=50)


class ApprovalRequirement(StrictModel):
    status: Literal["NOT_REQUIRED", "PENDING", "BLOCKED"]
    required: bool = False
    role: str | None = None
    approval_id: str | None = None


class BusinessProcurementPolicy(StrictModel):
    minimum_supplier_quotes: int = Field(default=1, ge=1)
    allowed_supplier_ids: list[int] | None = None
    blocked_categories: list[str] = Field(default_factory=list)
    maximum_budget_by_currency: dict[str, Decimal] = Field(default_factory=dict)
    approval_thresholds: list[ApprovalThreshold] = Field(default_factory=list)


class ProcurementPolicy(StrictModel):
    business: BusinessProcurementPolicy = Field(default_factory=BusinessProcurementPolicy)
    approver_roles: dict[str, str] = Field(default_factory=dict)


class InventoryItem(StrictModel):
    product_id: int = Field(gt=0)
    product_name: str
    on_hand: int = Field(ge=0)
    reserved: int = Field(ge=0)
    available: int = Field(ge=0)
    reorder_point: int = Field(ge=0)
    data_source: str = "DEMO DATA"

    @model_validator(mode="after")
    def check_available_quantity(self) -> "InventoryItem":
        if self.reserved > self.on_hand or self.available != self.on_hand - self.reserved:
            raise ValueError("available must equal on_hand minus reserved")
        return self


class DemandRecord(StrictModel):
    id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    period_start: str
    consumed_quantity: int = Field(ge=0)
    data_source: str = "DEMO DATA"


class DemandForecast(StrictModel):
    product_id: int = Field(gt=0)
    product_name: str
    status: Literal["available", "insufficient_data"]
    period_unit: Literal["month"] = "month"
    periods_used: int = Field(ge=0)
    average_monthly_demand: Decimal | None = Field(default=None, ge=0)
    average_daily_demand: Decimal | None = Field(default=None, ge=0)
    source_label: str = "DEMO DATA"


class ReorderRecommendation(StrictModel):
    product_id: int = Field(gt=0)
    product_name: str
    on_hand: int = Field(ge=0)
    reserved: int = Field(ge=0)
    available: int = Field(ge=0)
    reorder_point: int = Field(ge=0)
    forecast: DemandForecast
    lead_time_days: int | None = Field(default=None, ge=0)
    expected_lead_time_demand: int = Field(ge=0)
    recommended_quantity: int = Field(ge=0)
    reason: str
    source_label: str = "DEMO DATA"


class StoredPlanSummary(StrictModel):
    plan_id: str
    status: Literal["READY_FOR_REVIEW", "BLOCKED"]
    approval_status: Literal[
        "NOT_EVALUATED", "NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED", "BLOCKED"
    ] = "NOT_EVALUATED"
    created_at: str
    user_type: Literal["personal", "business"]
    product_query: str
    quantity_requested: int = Field(gt=0)
    quantity_planned: int = Field(ge=0)
    merchandise_subtotal: Decimal = Field(ge=0)
    currency: str
    source_label: str = "DEMO DATA"


class AuditEvent(StrictModel):
    id: int = Field(gt=0)
    actor: str
    action: str
    entity_type: str
    entity_id: str
    occurred_at: str
    details: dict[str, Any] = Field(default_factory=dict)


class PurchasePlan(StrictModel):
    plan_id: str | None = None
    request: PurchaseRequest
    status: Literal["READY_FOR_REVIEW", "BLOCKED"]
    selected_offer_ids: list[int] = Field(default_factory=list)
    lines: list[PurchaseLine] = Field(default_factory=list)
    quantity_requested: int = Field(gt=0)
    quantity_planned: int = Field(ge=0)
    merchandise_subtotal: Decimal = Field(ge=0)
    total_cost: Decimal = Field(ge=0, description="Merchandise subtotal; shipping and tax are excluded when absent from source offers.")
    currency: str
    average_effective_unit_cost: Decimal | None = None
    price_summary: PriceSummary
    supplier_assessments: list[SupplierAssessment] = Field(default_factory=list)
    findings: list[ValidationFinding] = Field(default_factory=list)
    risks: list[RiskAssessment] = Field(default_factory=list)
    compliance_findings: list[ComplianceFinding] = Field(default_factory=list)
    compliance_status: Literal["COMPLIANT", "BLOCKED"] = "COMPLIANT"
    approval_status: Literal[
        "NOT_EVALUATED", "NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED", "BLOCKED"
    ] = "NOT_EVALUATED"
    approval_required: bool = False
    approval_role: str | None = None
    approval_id: str | None = None
    explanation: list[str] = Field(default_factory=list)
    agents_used: list[str] = Field(default_factory=list)
    ai_summary: str | None = None
    source_label: str = "DEMO DATA"
    requires_human_review: bool = True
    external_order_created: bool = False


class ReorderWorkflow(StrictModel):
    recommendation: ReorderRecommendation
    purchase_plan: PurchasePlan
