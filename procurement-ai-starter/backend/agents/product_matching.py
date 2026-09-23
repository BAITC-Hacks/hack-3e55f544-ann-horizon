from backend.models.purchase import OfferMatch, Product, PurchaseRequest
from backend.tools.procurement import ProcurementTools


class ProductMatchingAgent:
    def __init__(self, tools: ProcurementTools) -> None:
        self._tools = tools

    def match(self, request: PurchaseRequest, products: list[Product]) -> list[OfferMatch]:
        return self._tools.match_products(request, products)
