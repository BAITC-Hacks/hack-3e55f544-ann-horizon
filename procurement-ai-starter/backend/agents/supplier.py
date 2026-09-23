from backend.models.purchase import OfferMatch, SupplierAssessment
from backend.tools.procurement import ProcurementTools


class SupplierAgent:
    def __init__(self, tools: ProcurementTools) -> None:
        self._tools = tools

    def assess(self, matches: list[OfferMatch]) -> list[SupplierAssessment]:
        return self._tools.assess_suppliers(matches)
