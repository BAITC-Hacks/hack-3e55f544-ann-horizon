from backend.models.purchase import DemandForecast, InventoryItem
from backend.tools.procurement import ProcurementTools


class DemandForecastAgent:
    def __init__(self, tools: ProcurementTools) -> None:
        self._tools = tools

    def forecast(self, item: InventoryItem) -> DemandForecast:
        return self._tools.forecast_demand(item)
