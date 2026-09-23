from dataclasses import dataclass
from decimal import Decimal

from backend.models.purchase import OfferMatch, PurchaseLine, PurchaseRequest
from backend.services.pricing import PricingService


@dataclass
class AllocationResult:
    lines: list[PurchaseLine]
    quantity_planned: int
    merchandise_subtotal: Decimal
    score_order: list[int]


_WEIGHTS = {
    "price": (0.65, 0.10, 0.15, 0.10),
    "balanced": (0.50, 0.20, 0.20, 0.10),
    "speed": (0.30, 0.50, 0.10, 0.10),
    "quality": (0.30, 0.10, 0.40, 0.20),
}


class OptimizationService:
    """Allocate units across offers after filtering hard constraints."""

    def allocate(self, request: PurchaseRequest, matches: list[OfferMatch]) -> AllocationResult:
        candidates = [
            match
            for match in matches
            if match.hard_requirements_met
            and match.offer.currency == request.currency
            and match.offer.quantity_available >= match.offer.minimum_order_quantity
            and (request.budget_per_unit is None or match.offer.unit_price <= request.budget_per_unit)
            and (request.max_delivery_days is None or match.offer.delivery_days <= request.max_delivery_days)
        ]
        scores = self._scores(request, candidates)
        ranked = sorted(
            candidates,
            key=lambda item: (-scores[item.offer.id], item.offer.unit_price, item.offer.delivery_days, item.offer.id),
        )
        allocation = self._allocate_in_order(request, ranked, scores)

        if allocation.quantity_planned < request.quantity and request.budget_total is not None:
            # A soft-score ordering can spend the budget too early. Recheck feasibility
            # with the cheapest hard-eligible offers before declaring a shortage.
            cheapest = sorted(
                candidates,
                key=lambda item: (item.offer.unit_price, item.offer.delivery_days, item.offer.id),
            )
            least_cost = self._allocate_in_order(request, cheapest, scores)
            if least_cost.quantity_planned > allocation.quantity_planned:
                allocation = least_cost

        return allocation

    def _scores(self, request: PurchaseRequest, matches: list[OfferMatch]) -> dict[int, float]:
        if not matches:
            return {}
        prices = [float(item.offer.unit_price) for item in matches]
        deliveries = [item.offer.delivery_days for item in matches]
        warranties = [item.offer.warranty_months for item in matches]
        low_price, high_price = min(prices), max(prices)
        fast_day, slow_day = min(deliveries), max(deliveries)
        best_warranty = max(warranties) or 1
        price_weight, speed_weight, supplier_weight, warranty_weight = _WEIGHTS[request.priority]

        def score(match: OfferMatch) -> float:
            price = float(match.offer.unit_price)
            price_score = 1.0 if high_price == low_price else (high_price - price) / (high_price - low_price)
            delivery_score = 1.0 if slow_day == fast_day else (slow_day - match.offer.delivery_days) / (slow_day - fast_day)
            supplier_score = match.supplier.reliability if match.supplier.reliability is not None else 0.5
            warranty_score = match.offer.warranty_months / best_warranty
            return 0.95 * (
                price_weight * price_score
                + speed_weight * delivery_score
                + supplier_weight * supplier_score
                + warranty_weight * warranty_score
            ) + 0.05 * match.soft_score

        return {match.offer.id: min(1.0, max(0.0, score(match))) for match in matches}

    @staticmethod
    def _allocate_in_order(
        request: PurchaseRequest,
        matches: list[OfferMatch],
        scores: dict[int, float],
    ) -> AllocationResult:
        remaining = request.quantity
        spent = Decimal("0")
        lines: list[PurchaseLine] = []
        selected_order = []
        for match in matches:
            if remaining <= 0:
                break
            offer = match.offer
            take = min(remaining, offer.quantity_available)
            if request.budget_total is not None:
                budget_left = request.budget_total - spent
                affordable = int(budget_left / offer.unit_price) if budget_left > 0 else 0
                take = min(take, affordable)
            if take < offer.minimum_order_quantity:
                continue
            subtotal = PricingService.line_subtotal(offer.unit_price, take)
            lines.append(
                PurchaseLine(
                    offer_id=offer.id,
                    product_id=match.product.id,
                    product_name=match.product.name,
                    supplier_id=match.supplier.id,
                    supplier_name=match.supplier.name,
                    quantity=take,
                    unit_price=offer.unit_price,
                    merchandise_subtotal=subtotal,
                    delivery_days=offer.delivery_days,
                    warranty_months=offer.warranty_months,
                    match_type=match.match_type,
                    match_score=round(match.soft_score, 4),
                    optimization_score=round(scores[offer.id], 4),
                    data_source=offer.data_source,
                )
            )
            selected_order.append(offer.id)
            spent += subtotal
            remaining -= take
        return AllocationResult(
            lines=lines,
            quantity_planned=request.quantity - remaining,
            merchandise_subtotal=spent,
            score_order=selected_order,
        )
