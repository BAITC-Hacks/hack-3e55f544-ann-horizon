"""Contracts for explicitly local personal shopping workflows."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from backend.models.purchase import StrictModel


class PersonalPreferencesInput(StrictModel):
    preferred_brands: list[str] = Field(default_factory=list, max_length=30)
    preferred_supplier_ids: list[int] = Field(default_factory=list, max_length=30)
    favorite_categories: list[str] = Field(default_factory=list, max_length=30)
    budget_min: Decimal | None = Field(default=None, ge=0)
    budget_max: Decimal | None = Field(default=None, gt=0)
    currency: str = Field(default="KZT", pattern="^[A-Za-z]{3}$")
    note: str = Field(default="", max_length=1000)

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, value: str) -> str:
        return value.upper()

    @field_validator("preferred_brands", "favorite_categories")
    @classmethod
    def useful_strings(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip() for value in values))
        if any(not value or len(value) > 100 for value in cleaned):
            raise ValueError("Preference values must contain 1–100 characters")
        return cleaned

    @model_validator(mode="after")
    def valid_range(self):
        if self.budget_min is not None and self.budget_max is not None and self.budget_min > self.budget_max:
            raise ValueError("budget_min must not exceed budget_max")
        if any(value <= 0 for value in self.preferred_supplier_ids):
            raise ValueError("Supplier IDs must be positive")
        self.preferred_supplier_ids = list(dict.fromkeys(self.preferred_supplier_ids))
        return self


class PersonalPreferences(PersonalPreferencesInput):
    user_id: str
    updated_at: datetime | None = None


class PersonalPurchaseInput(StrictModel):
    user_id: str = Field(default="demo-user", min_length=1, max_length=100)
    product_id: int = Field(gt=0)
    offer_id: int | None = Field(default=None, gt=0)
    quantity: int = Field(default=1, gt=0, le=100000)
    unit_price: Decimal = Field(ge=0)
    currency: str = Field(default="KZT", pattern="^[A-Za-z]{3}$")
    purchased_at: datetime
    repeat_after_days: int | None = Field(default=None, ge=1, le=3650)
    note: str = Field(default="", max_length=1000)

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, value: str) -> str:
        return value.upper()

    @field_validator("purchased_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("purchased_at must include a timezone")
        return value


class PersonalPurchase(PersonalPurchaseInput):
    purchase_id: str
    product_name: str
    supplier_id: int | None = None
    supplier_name: str | None = None
    total_price: Decimal
    created_at: datetime
    data_source: str = "MANUALLY RECORDED PURCHASE"


class PersonalReorderRecommendation(StrictModel):
    product_id: int
    product_name: str
    source_purchase_id: str
    quantity: int
    repeat_after_days: int
    due_at: datetime
    status: Literal["DUE", "SCHEDULED"]
    current_offer_id: int | None = None
    current_unit_price: Decimal | None = None
    estimated_subtotal: Decimal | None = None
    currency: str
    explanation: str
    external_order_created: Literal[False] = False


CompatibilityCheckName = Literal["interface", "form_factor", "dimensions", "power", "socket"]


class ComponentSpecs(StrictModel):
    interface: str | None = Field(default=None, min_length=1, max_length=100)
    form_factor: str | None = Field(default=None, min_length=1, max_length=100)
    length_mm: Decimal | None = Field(default=None, gt=0)
    required_power_w: Decimal | None = Field(default=None, ge=0)
    socket: str | None = Field(default=None, min_length=1, max_length=100)


class HostSpecs(StrictModel):
    accepted_interfaces: list[str] | None = Field(default=None, max_length=20)
    accepted_form_factors: list[str] | None = Field(default=None, max_length=20)
    maximum_length_mm: Decimal | None = Field(default=None, gt=0)
    available_power_w: Decimal | None = Field(default=None, ge=0)
    accepted_sockets: list[str] | None = Field(default=None, max_length=20)

    @field_validator("accepted_interfaces", "accepted_form_factors", "accepted_sockets")
    @classmethod
    def nonempty_values(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not item.strip() or len(item) > 100 for item in value):
            raise ValueError("Host spec values must contain 1–100 characters")
        return value


class CompatibilityRequest(StrictModel):
    product_id: int = Field(gt=0)
    host_product_id: int | None = Field(default=None, gt=0)
    host_specs: HostSpecs = Field(default_factory=HostSpecs)
    component_specs: ComponentSpecs = Field(default_factory=ComponentSpecs)
    required_checks: list[CompatibilityCheckName] = Field(
        default_factory=lambda: ["interface", "form_factor", "dimensions", "power"],
        min_length=1, max_length=5,
    )

    @field_validator("required_checks")
    @classmethod
    def deduplicate_checks(cls, value):
        return list(dict.fromkeys(value))


class CompatibilityFinding(StrictModel):
    check: CompatibilityCheckName
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    explanation: str


class CompatibilityResult(StrictModel):
    product_id: int
    product_name: str
    host_product_id: int | None = None
    verdict: Literal["COMPATIBLE", "INCOMPATIBLE", "UNKNOWN"]
    findings: list[CompatibilityFinding]
    scope_note: str = "Проверены только перечисленные условия. Дополнительные характеристики введены пользователем и не проверены по данным производителя."


class BundleItemInput(StrictModel):
    product_id: int | None = Field(default=None, gt=0)
    product_query: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: int = Field(default=1, gt=0, le=10000)
    minimum_ram_gb: int | None = Field(default=None, gt=0)
    minimum_capacity_gb: int | None = Field(default=None, gt=0)
    component_specs: ComponentSpecs = Field(default_factory=ComponentSpecs)

    @model_validator(mode="after")
    def one_selector(self):
        if (self.product_id is None) == (self.product_query is None):
            raise ValueError("Provide exactly one of product_id or product_query")
        return self


class BundleRequest(StrictModel):
    user_id: str = Field(default="demo-user", min_length=1, max_length=100)
    items: list[BundleItemInput] = Field(min_length=1, max_length=8)
    budget_total: Decimal = Field(gt=0)
    currency: str = Field(default="KZT", pattern="^[A-Za-z]{3}$")
    host_product_id: int | None = Field(default=None, gt=0)
    host_specs: HostSpecs = Field(default_factory=HostSpecs)
    required_checks: list[CompatibilityCheckName] = Field(
        default_factory=lambda: ["interface", "form_factor", "dimensions", "power"],
        min_length=1, max_length=5,
    )

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, value: str) -> str:
        return value.upper()


class BundleLine(StrictModel):
    product_id: int
    product_name: str
    offer_id: int
    supplier_id: int
    supplier_name: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    compatibility: CompatibilityResult | None = None


class BundleResult(StrictModel):
    outcome: Literal["READY_FOR_REVIEW", "REVIEW_REQUIRED", "BLOCKED"]
    lines: list[BundleLine]
    merchandise_subtotal: Decimal
    currency: str
    within_budget: bool
    compatibility_verdict: Literal["COMPATIBLE", "INCOMPATIBLE", "UNKNOWN", "NOT_APPLICABLE"]
    findings: list[str]
    data_source: str = "LOCAL DEMO CATALOG"
    external_order_created: Literal[False] = False


class ReturnDraftInput(StrictModel):
    user_id: str = Field(default="demo-user", min_length=1, max_length=100)
    purchase_id: str = Field(min_length=1, max_length=100)
    quantity: int = Field(default=1, gt=0)
    reason: str = Field(min_length=1, max_length=1000)
    return_deadline: date | None = None
    policy_source: str | None = Field(default=None, min_length=1, max_length=500)
    documents: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def source_for_deadline(self):
        if (self.return_deadline is None) != (self.policy_source is None):
            raise ValueError("return_deadline and policy_source must be supplied together")
        if any(not value.strip() or len(value) > 300 for value in self.documents):
            raise ValueError("Document labels must contain 1–300 characters")
        return self


class ReturnDraft(ReturnDraftInput):
    return_id: str
    product_name: str
    purchased_at: datetime
    created_at: datetime
    status: Literal["DRAFT", "CANCELLED"] = "DRAFT"
    deadline_status: Literal["UNKNOWN", "WITHIN_PROVIDED_DEADLINE", "PAST_PROVIDED_DEADLINE"]
    explanation: str
    externally_submitted: Literal[False] = False
