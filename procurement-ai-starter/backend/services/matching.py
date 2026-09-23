from backend.models.purchase import OfferMatch, Product, PurchaseRequest, Supplier
from backend.services.catalog import CatalogService


_SPEC_KEYS = {
    "storage_gb": ("storage_gb", "capacity_gb", "ssd_gb"),
    "capacity_gb": ("capacity_gb", "ssd_gb"),
    "ssd_gb": ("ssd_gb", "capacity_gb"),
    "ram_gb": ("ram_gb",),
    "interface": ("interface",),
}


class ProductMatchingService:
    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    def match(self, request: PurchaseRequest, products: list[Product]) -> list[OfferMatch]:
        product_by_id = {product.id: product for product in products}
        supplier_by_id = {supplier.id: supplier for supplier in self._catalog.list_suppliers()}
        offers = self._catalog.offers_for_products(set(product_by_id))
        matches = []
        for offer in offers:
            product = product_by_id.get(offer.product_id)
            supplier = supplier_by_id.get(offer.supplier_id)
            if product is None or supplier is None:
                continue
            matches.append(self._match_offer(request, product, supplier, offer))
        return matches

    @staticmethod
    def _match_offer(request: PurchaseRequest, product: Product, supplier: Supplier, offer) -> OfferMatch:
        matched: dict[str, str] = {}
        unmet: list[str] = []
        exact_specs = True
        for key, requested in request.required_specs.items():
            product_value = None
            for alias in _SPEC_KEYS.get(key, (key,)):
                product_value = getattr(product, alias, None)
                if product_value is not None:
                    break
            if product_value is None:
                unmet.append(key)
                continue

            if isinstance(requested, (int, float)) and not isinstance(requested, bool):
                try:
                    passes = float(product_value) >= float(requested)
                except (TypeError, ValueError):
                    passes = False
                if not passes:
                    unmet.append(key)
                    continue
                if float(product_value) != float(requested):
                    exact_specs = False
                matched[key] = f"{product_value} (required >= {requested})"
            else:
                passes = str(product_value).casefold() == str(requested).casefold()
                if not passes:
                    unmet.append(key)
                    continue
                matched[key] = str(product_value)

        brand_match = bool(
            request.preferred_brand
            and product.brand
            and request.preferred_brand.casefold() == product.brand.casefold()
        )
        query = request.product_query.casefold().strip()
        exact_product = bool(query and query in product.name.casefold())
        if unmet:
            match_type = "unsuitable"
            soft_score = 0.0
        elif request.preferred_brand and not brand_match:
            match_type = "partial"
            soft_score = 0.8 if exact_specs else 0.7
        elif exact_product and exact_specs:
            match_type = "exact"
            soft_score = 1.0
        elif request.required_specs and not exact_specs:
            match_type = "compatible"
            soft_score = 0.95 if brand_match or not request.preferred_brand else 0.85
        elif not request.required_specs and exact_product:
            match_type = "exact"
            soft_score = 0.9
        else:
            match_type = "partial"
            soft_score = 0.8 if brand_match else 0.7

        return OfferMatch(
            offer=offer,
            product=product,
            supplier=supplier,
            match_type=match_type,
            hard_requirements_met=not unmet,
            matched_specs=matched,
            unmet_specs=unmet,
            soft_score=soft_score,
        )
