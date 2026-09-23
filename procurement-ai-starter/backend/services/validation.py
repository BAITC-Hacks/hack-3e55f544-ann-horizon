from decimal import Decimal

from backend.models.purchase import (
    PurchasePlan,
    PurchaseRequest,
    ValidationFinding,
)
from backend.services.catalog import CatalogService


_SPEC_ALIASES = {
    "storage_gb": ("storage_gb", "capacity_gb", "ssd_gb"),
    "capacity_gb": ("capacity_gb", "ssd_gb"),
    "ssd_gb": ("ssd_gb", "capacity_gb"),
    "ram_gb": ("ram_gb",),
    "interface": ("interface",),
}


class ValidationService:
    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    def validate(self, request: PurchaseRequest, plan: PurchasePlan) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        errors: list[tuple[str, str]] = []
        seen: set[int] = set()
        computed_total = Decimal("0")
        computed_quantity = 0
        offer_by_id = {offer.id: offer for offer in self._catalog.list_offers()}

        for line in plan.lines:
            if line.offer_id in seen:
                errors.append(("duplicate_offer", f"Повторное предложение в плане: {line.offer_id}."))
            seen.add(line.offer_id)
            offer = offer_by_id.get(line.offer_id)
            product = self._catalog.product_by_id(line.product_id)
            supplier = self._catalog.supplier_by_id(line.supplier_id)
            if offer is None:
                errors.append(("unknown_offer", f"Предложение {line.offer_id} отсутствует в каталоге."))
                continue
            if product is None or offer.product_id != line.product_id:
                errors.append(("product_mismatch", f"Товар для предложения {line.offer_id} не совпадает."))
            elif product is not None:
                for spec_name, required in request.required_specs.items():
                    actual = None
                    for alias in _SPEC_ALIASES.get(spec_name, (spec_name,)):
                        actual = getattr(product, alias, None)
                        if actual is not None:
                            break
                    passes = actual is not None
                    if passes and isinstance(required, (int, float)) and not isinstance(required, bool):
                        try:
                            passes = float(actual) >= float(required)
                        except (TypeError, ValueError):
                            passes = False
                    elif passes:
                        passes = str(actual).casefold() == str(required).casefold()
                    if not passes:
                        errors.append(("requirements_unmet", f"Товар {product.id} не проходит характеристику {spec_name}."))
            if supplier is None or offer.supplier_id != line.supplier_id:
                errors.append(("supplier_mismatch", f"Поставщик для предложения {line.offer_id} не совпадает."))
            if line.quantity <= 0:
                errors.append(("invalid_quantity", "Количество в каждой строке должно быть положительным."))
            if line.quantity > offer.quantity_available:
                errors.append(("insufficient_stock", f"Предложение {line.offer_id}: запрошено больше остатка."))
            if line.quantity < offer.minimum_order_quantity:
                errors.append(("below_moq", f"Предложение {line.offer_id}: количество ниже MOQ."))
            if line.unit_price != offer.unit_price or line.unit_price < 0:
                errors.append(("price_mismatch", f"Цена в предложении {line.offer_id} не совпадает с каталогом."))
            expected_subtotal = offer.unit_price * line.quantity
            if line.merchandise_subtotal != expected_subtotal:
                errors.append(("subtotal_mismatch", f"Сумма строки {line.offer_id} рассчитана неверно."))
            if offer.currency != request.currency:
                errors.append(("currency_mismatch", f"Предложение {line.offer_id} имеет другую валюту."))
            if request.budget_per_unit is not None and offer.unit_price > request.budget_per_unit:
                errors.append(("unit_budget_exceeded", f"Цена по предложению {line.offer_id} превышает лимит за единицу."))
            if request.max_delivery_days is not None and offer.delivery_days > request.max_delivery_days:
                errors.append(("delivery_limit_exceeded", f"Срок по предложению {line.offer_id} превышает ограничение."))
            if line.match_type == "unsuitable":
                errors.append(("requirements_unmet", f"Предложение {line.offer_id} не соответствует характеристикам."))
            computed_total += expected_subtotal
            computed_quantity += line.quantity

        if computed_quantity != plan.quantity_planned:
            errors.append(("planned_quantity_mismatch", "Итоговое количество не совпадает с суммой строк."))
        if computed_total != plan.merchandise_subtotal or plan.total_cost != computed_total:
            errors.append(("plan_total_mismatch", "Итог плана не совпадает с суммой строк."))
        if plan.quantity_planned < request.quantity:
            errors.append(("quantity_shortage", f"Найдено {plan.quantity_planned} из {request.quantity} единиц."))
        if request.budget_total is not None and computed_total > request.budget_total:
            errors.append(("total_budget_exceeded", "Стоимость товара превышает общий бюджет."))
        expected_ids = [line.offer_id for line in plan.lines]
        if plan.selected_offer_ids != expected_ids:
            errors.append(("offer_id_mismatch", "Список выбранных предложений не совпадает со строками плана."))

        for code, message in errors:
            findings.append(ValidationFinding(code=code, severity="error", message=message))

        if not plan.lines:
            findings.append(
                ValidationFinding(
                    code="no_eligible_offers",
                    severity="info",
                    message="Нет предложений, удовлетворяющих доступным ограничениям.",
                )
            )
        if any(line.data_source == "DEMO DATA" for line in plan.lines):
            findings.append(
                ValidationFinding(
                    code="demo_catalog",
                    severity="warning",
                    message="План рассчитан по синтетическим DEMO DATA; перед закупкой нужны актуальные коммерческие предложения.",
                )
            )
        if plan.lines and any(
            source is not None and (source.shipping_cost is None or source.tax_rate is None)
            for source in (offer_by_id.get(line.offer_id) for line in plan.lines)
        ):
            findings.append(
                ValidationFinding(
                    code="shipping_tax_unknown",
                    severity="warning",
                    message="Доставка и налоги не указаны в источнике и не включены в сумму.",
                )
            )
        findings.append(
            ValidationFinding(
                code="human_review_required",
                severity="info",
                message="Результат является проектом рекомендации; заказ не создан, внешние действия не выполнялись.",
            )
        )
        return findings
