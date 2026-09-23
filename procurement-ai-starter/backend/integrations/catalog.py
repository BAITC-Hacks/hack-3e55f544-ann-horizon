from typing import Protocol

from backend.models.purchase import Offer, PriceHistoryRecord, Product, Supplier
from backend.repositories.catalog import CatalogRepository, JsonCatalogRepository
from backend.repositories.procurement import SQLiteProcurementRepository


class CatalogAdapter(Protocol):
    def products(self) -> list[Product]: ...

    def suppliers(self) -> list[Supplier]: ...

    def offers(self) -> list[Offer]: ...

    def price_history(self) -> list[PriceHistoryRecord]: ...


class SampleCatalogAdapter:
    """Adapter for explicitly synthetic local sample data."""

    def __init__(self, repository: CatalogRepository | None = None) -> None:
        self._repository = repository or JsonCatalogRepository()

    def products(self) -> list[Product]:
        return self._repository.list_products()

    def suppliers(self) -> list[Supplier]:
        return self._repository.list_suppliers()

    def offers(self) -> list[Offer]:
        return self._repository.list_offers()

    def price_history(self) -> list[PriceHistoryRecord]:
        reader = getattr(self._repository, "list_price_history", None)
        return reader() if reader else []


class SQLiteCatalogAdapter:
    """SQLite-backed catalog adapter, seeded once from the local DEMO JSON files."""

    def __init__(self, repository: SQLiteProcurementRepository | None = None) -> None:
        self._repository = repository or SQLiteProcurementRepository()

    def products(self) -> list[Product]:
        return self._repository.list_products()

    def suppliers(self) -> list[Supplier]:
        return self._repository.list_suppliers()

    def offers(self) -> list[Offer]:
        return self._repository.list_offers()

    def price_history(self) -> list[PriceHistoryRecord]:
        return self._repository.list_price_history()
