import re

from backend.integrations.catalog import CatalogAdapter
from backend.models.purchase import Offer, PriceHistoryRecord, Product, Supplier


_ALIASES = {
    "ноутбук": "laptop",
    "ноутбуки": "laptop",
    "ноутбуков": "laptop",
    "laptops": "laptop",
    "notebook": "laptop",
    "накопитель": "ssd",
    "накопителя": "ssd",
    "накопители": "ssd",
    "диск": "ssd",
    "диски": "ssd",
    "solidstate": "ssd",
}
_CATEGORY_ALIASES = {
    "keyboard": {"keyboard", "keyboards", "клавиатура", "клавиатуры", "клавиатур"},
    "mouse": {"mouse", "mice", "мышь", "мыши", "мышку", "мышей"},
    "headset": {"headset", "headsets", "гарнитура", "гарнитуры", "наушники"},
    "monitor": {"monitor", "monitors", "монитор", "мониторы", "монитора"},
}


def _terms(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-zа-яё0-9]+", text.lower()))
    return {_ALIASES.get(token, token) for token in tokens if len(token) > 1}


class CatalogService:
    def __init__(self, adapter: CatalogAdapter) -> None:
        self._adapter = adapter

    def list_products(self) -> list[Product]:
        return self._adapter.products()

    def list_suppliers(self) -> list[Supplier]:
        return self._adapter.suppliers()

    def list_offers(self) -> list[Offer]:
        return self._adapter.offers()

    def price_history(self) -> list[PriceHistoryRecord]:
        reader = getattr(self._adapter, "price_history", None)
        return reader() if reader else []

    def search_products(self, query: str) -> list[Product]:
        query_terms = _terms(query)
        if not query_terms:
            return []
        products = self._adapter.products()
        normalized_query = " ".join(re.findall(r"[a-zа-яё0-9]+", query.casefold()))
        # A complete known SKU/model/product name is an exact identifier. Return
        # those matches first so shared words like "wireless" cannot select a
        # neighbouring category by token overlap.
        exact = []
        for product in products:
            for identifier in (product.sku, product.model, product.name):
                normalized_id = " ".join(re.findall(r"[a-zа-яё0-9]+", (identifier or "").casefold()))
                if normalized_id and (normalized_query == normalized_id or f" {normalized_id} " in f" {normalized_query} "):
                    exact.append(product)
                    break
        if exact:
            return exact

        category_filter = next(
            (category for category, aliases in _CATEGORY_ALIASES.items() if query_terms & aliases),
            None,
        )
        if category_filter:
            categorized = [product for product in products if product.category.casefold() == category_filter]
            if categorized:
                return categorized

        found: list[Product] = []
        for product in products:
            searchable = " ".join(
                value or ""
                for value in (
                    product.name,
                    product.category,
                    product.brand,
                    product.model,
                    product.sku,
                    product.interface,
                )
            )
            product_terms = _terms(searchable)
            if query_terms & product_terms:
                found.append(product)
        return found

    def offers_for_products(self, product_ids: set[int]) -> list[Offer]:
        if not product_ids:
            return []
        return [
            offer
            for offer in self._adapter.offers()
            if offer.product_id in product_ids and offer.quantity_available > 0
        ]

    def product_by_id(self, product_id: int) -> Product | None:
        return next((p for p in self._adapter.products() if p.id == product_id), None)

    def supplier_by_id(self, supplier_id: int) -> Supplier | None:
        return next((s for s in self._adapter.suppliers() if s.id == supplier_id), None)

    def offer_by_id(self, offer_id: int) -> Offer | None:
        return next((o for o in self._adapter.offers() if o.id == offer_id), None)
