import json
from pathlib import Path
from typing import Protocol

from backend.models.purchase import Offer, PriceHistoryRecord, Product, Supplier


class CatalogRepository(Protocol):
    def list_products(self) -> list[Product]: ...

    def list_suppliers(self) -> list[Supplier]: ...

    def list_offers(self) -> list[Offer]: ...

    def list_price_history(self) -> list[PriceHistoryRecord]: ...


class JsonCatalogRepository:
    """Read-only repository for the linked local sample catalog."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or Path(__file__).resolve().parents[2] / "data"
        self._products = self._read("products.json", Product)
        self._suppliers = self._read("suppliers.json", Supplier)
        self._offers = self._read("offers.json", Offer)
        history_path = self._data_dir / "sample_price_history.json"
        self._price_history = self._read("sample_price_history.json", PriceHistoryRecord) if history_path.exists() else []
        self._validate_references()

    def _read(self, filename: str, model: type) -> list:
        path = self._data_dir / filename
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(f"{path} must contain a JSON list")
        return [model.model_validate(row) for row in raw]

    def _validate_references(self) -> None:
        product_ids = {item.id for item in self._products}
        supplier_ids = {item.id for item in self._suppliers}
        offer_ids: set[int] = set()
        for offer in self._offers:
            if offer.id in offer_ids:
                raise ValueError(f"Duplicate offer id in sample catalog: {offer.id}")
            offer_ids.add(offer.id)
            if offer.product_id not in product_ids:
                raise ValueError(f"Offer {offer.id} refers to missing product {offer.product_id}")
            if offer.supplier_id not in supplier_ids:
                raise ValueError(f"Offer {offer.id} refers to missing supplier {offer.supplier_id}")
        offers_by_id = {offer.id: offer for offer in self._offers}
        observations: set[tuple[int, object]] = set()
        for record in self._price_history:
            offer = offers_by_id.get(record.offer_id)
            if offer is None or (record.product_id, record.supplier_id, record.currency) != (
                offer.product_id, offer.supplier_id, offer.currency
            ):
                raise ValueError(f"Price history refers to a missing or mismatched offer {record.offer_id}")
            key = (record.offer_id, record.observed_on)
            if key in observations:
                raise ValueError(f"Duplicate price observation for offer {record.offer_id} on {record.observed_on}")
            observations.add(key)

    def list_products(self) -> list[Product]:
        return list(self._products)

    def list_suppliers(self) -> list[Supplier]:
        return list(self._suppliers)

    def list_offers(self) -> list[Offer]:
        return list(self._offers)

    def list_price_history(self) -> list[PriceHistoryRecord]:
        return list(self._price_history)
