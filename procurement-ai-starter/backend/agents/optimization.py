from backend.models.purchase import OfferMatch, PurchaseRequest
from backend.services.optimization import AllocationResult
from backend.tools.procurement import ProcurementTools


class OptimizationAgent:
    def __init__(self, tools: ProcurementTools) -> None:
        self._tools = tools

    def optimize(self, request: PurchaseRequest, matches: list[OfferMatch]) -> AllocationResult:
        return self._tools.optimize(request, matches)
