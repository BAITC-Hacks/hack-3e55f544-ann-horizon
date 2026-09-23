from backend.models.purchase import ComplianceFinding, PurchasePlan, PurchaseRequest
from backend.services.compliance import ComplianceService


class ComplianceAgent:
    """Applies the configured business rules through a deterministic service."""

    def __init__(self, service: ComplianceService) -> None:
        self._service = service

    def evaluate(self, request: PurchaseRequest, plan: PurchasePlan) -> list[ComplianceFinding]:
        return self._service.evaluate(request, plan)
