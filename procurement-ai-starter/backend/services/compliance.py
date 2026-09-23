from decimal import Decimal

from backend.models.purchase import ApprovalThreshold, ComplianceFinding, PurchasePlan, PurchaseRequest
from backend.services.catalog import CatalogService
from backend.services.policy import PolicyService


class ComplianceService:
    def __init__(self, catalog: CatalogService, policy: PolicyService) -> None:
        self._catalog = catalog
        self._policy = policy

    def evaluate(self, request: PurchaseRequest, plan: PurchasePlan) -> list[ComplianceFinding]:
        if request.user_context.user_type != "business":
            return [
                ComplianceFinding(
                    code="personal_purchase_policy",
                    severity="info",
                    message="Business procurement policy does not apply to personal requests.",
                    evidence=["user_type=personal"],
                )
            ]

        rules = self._policy.policy.business
        findings: list[ComplianceFinding] = []
        quote_count = len({item.supplier_id for item in plan.supplier_assessments})
        if quote_count < rules.minimum_supplier_quotes:
            findings.append(
                ComplianceFinding(
                    code="insufficient_supplier_quotes",
                    severity="error",
                    message=(
                        f"Policy requires at least {rules.minimum_supplier_quotes} supplier quotes; "
                        f"only {quote_count} candidate supplier(s) are available."
                    ),
                    evidence=[f"candidate_supplier_count={quote_count}"],
                )
            )

        allowed = rules.allowed_supplier_ids
        if allowed is not None:
            disallowed = sorted({line.supplier_id for line in plan.lines if line.supplier_id not in allowed})
            if disallowed:
                findings.append(
                    ComplianceFinding(
                        code="supplier_not_allowed",
                        severity="error",
                        message="The draft includes suppliers outside the configured allowlist.",
                        evidence=[f"disallowed_supplier_ids={disallowed}", f"allowed_supplier_ids={sorted(allowed)}"],
                    )
                )

        blocked_categories = {value.casefold() for value in rules.blocked_categories}
        categories = {
            product.category
            for line in plan.lines
            if (product := self._catalog.product_by_id(line.product_id)) is not None
        }
        blocked = sorted(category for category in categories if category.casefold() in blocked_categories)
        if blocked:
            findings.append(
                ComplianceFinding(
                    code="category_blocked",
                    severity="error",
                    message="The draft contains a category blocked by the business policy.",
                    evidence=[f"blocked_categories={blocked}"],
                )
            )

        maximum = rules.maximum_budget_by_currency.get(request.currency)
        if maximum is not None and plan.total_cost > maximum:
            findings.append(
                ComplianceFinding(
                    code="policy_budget_exceeded",
                    severity="error",
                    message=f"Draft total exceeds the configured {request.currency} policy limit.",
                    evidence=[f"total={plan.total_cost}", f"maximum={maximum}"],
                )
            )
        elif maximum is None:
            findings.append(
                ComplianceFinding(
                    code="policy_budget_not_configured",
                    severity="info",
                    message="No organization-wide maximum budget is configured for this currency.",
                    evidence=[f"currency={request.currency}"],
                )
            )

        return findings


def approval_role_for_amount(amount: Decimal, thresholds: list[ApprovalThreshold]) -> str | None:
    """Return the first configured role whose inclusive upper bound contains amount."""
    ordered = sorted(
        thresholds,
        key=lambda item: (item.max_amount is None, item.max_amount or Decimal("0")),
    )
    for threshold in ordered:
        if threshold.max_amount is None or amount <= threshold.max_amount:
            return threshold.role
    return None
