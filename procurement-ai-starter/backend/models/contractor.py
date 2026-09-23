from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field

from backend.models.purchase import StrictModel


class ContractorProfile(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    anon_name: str = Field(min_length=1, max_length=120)
    categories: list[str] = Field(min_length=1)
    city: str
    price_from_kzt: Decimal = Field(gt=0)
    event_formats: list[str] = Field(min_length=1)
    languages: list[str] = Field(min_length=1)
    max_hours: Decimal | None = Field(default=None, gt=0)
    busy_dates: list[date] = Field(default_factory=list)
    description: str = Field(min_length=1, max_length=5000)
    synthetic: bool = False
    city_imputed: bool = False
    price_imputed: bool = False


class ContractorSearchRequest(StrictModel):
    city: str = Field(min_length=1, max_length=100)
    event_date: date
    event_type: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=120)
    budget_kzt: Decimal = Field(gt=0)
    duration_hours: Decimal | None = Field(default=None, gt=0, le=168)
    language: str | None = Field(default=None, max_length=50)
    limit: int = Field(default=3, ge=1, le=3)


class ContractorCard(StrictModel):
    contractor_id: str
    name: str
    category: str
    city: str
    price_from_kzt: Decimal
    explanation: str
    synthetic: bool
    city_imputed: bool
    price_imputed: bool
    source_label: Literal["SYNTHETIC", "ANONYMIZED SOURCE"]


class ContractorSearchResult(StrictModel):
    outcome: Literal["MATCHES", "CATEGORY_NOT_FOUND", "NO_MATCHES"]
    message: str
    requested_limit: int
    candidate_count: int
    matched_count: int
    cards: list[ContractorCard] = Field(default_factory=list, max_length=3)
    rejection_reasons: dict[str, int] = Field(default_factory=dict)
    source_label: Literal[
        "SYNTHETIC DEMO CATALOG", "ANONYMIZED SOURCE DATA", "ANONYMIZED SOURCE + SYNTHETIC"
    ]


class ContractorDemoScenarioResult(StrictModel):
    scenario_id: str
    title: str
    request: ContractorSearchRequest
    result: ContractorSearchResult
