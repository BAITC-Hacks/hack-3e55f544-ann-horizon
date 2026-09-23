from backend.models.purchase import DemandForecast, InventoryItem, ReorderRecommendation
from backend.tools.procurement import ProcurementTools


class AutomaticReorderAgent:
    def __init__(self, tools: ProcurementTools) -> None:
        self._tools = tools

    def recommend(
        self,
        item: InventoryItem,
        forecast: DemandForecast,
    ) -> ReorderRecommendation:
        return self._tools.recommend_reorder(item, forecast)
