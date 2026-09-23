from typing import Protocol

from backend.models.purchase import DemandRecord, InventoryItem


class InventoryRepository(Protocol):
    def list_inventory(self) -> list[InventoryItem]: ...

    def list_demand_history(self, product_id: int, limit: int = 12) -> list[DemandRecord]: ...


class InventoryService:
    def __init__(self, repository: InventoryRepository) -> None:
        self._repository = repository

    def list_inventory(self) -> list[InventoryItem]:
        return self._repository.list_inventory()

    def get_item(self, product_id: int) -> InventoryItem | None:
        return next((item for item in self.list_inventory() if item.product_id == product_id), None)

    def demand_history(self, product_id: int, limit: int = 12) -> list[DemandRecord]:
        return self._repository.list_demand_history(product_id, limit)
