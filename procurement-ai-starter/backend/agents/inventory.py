from backend.models.purchase import InventoryItem
from backend.tools.procurement import ProcurementTools


class InventoryAgent:
    def __init__(self, tools: ProcurementTools) -> None:
        self._tools = tools

    def scan(self) -> list[InventoryItem]:
        return self._tools.list_inventory()
