from backend.models.purchase import PurchasePlan, PurchaseRequest, RiskAssessment
from backend.services.risk import RiskService


class RiskAgent:
    """Deterministic risk synthesis from recorded plan and supplier evidence."""

    def __init__(self, service: RiskService | None = None) -> None:
        self._service = service or RiskService()

    def assess(self, request: PurchaseRequest, plan: PurchasePlan) -> list[RiskAssessment]:
        return self._service.assess(request, plan)
