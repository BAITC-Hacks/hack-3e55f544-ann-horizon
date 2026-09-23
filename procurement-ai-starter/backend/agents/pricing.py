from backend.models.purchase import OfferMatch, PriceSummary, PurchaseRequest
from backend.tools.procurement import ProcurementTools


class PricingAgent:
    def __init__(self, tools: ProcurementTools) -> None:
        self._tools = tools

    def analyze(self, request: PurchaseRequest, matches: list[OfferMatch]) -> PriceSummary:
        return self._tools.summarize_prices(matches, request.currency)
