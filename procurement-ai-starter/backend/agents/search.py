from backend.models.purchase import Product, PurchaseRequest
from backend.tools.procurement import ProcurementTools


class SearchAgent:
    def __init__(self, tools: ProcurementTools) -> None:
        self._tools = tools

    def search(self, request: PurchaseRequest) -> list[Product]:
        return self._tools.find_products(request.product_query)
