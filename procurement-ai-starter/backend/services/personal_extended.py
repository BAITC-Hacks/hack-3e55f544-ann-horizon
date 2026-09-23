"""Deterministic shopping memory, repeat buying, compatibility and local returns."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.models.personal_extended import (
    BundleLine, BundleRequest, BundleResult, CompatibilityFinding, CompatibilityRequest,
    CompatibilityResult, PersonalPreferences, PersonalPreferencesInput, PersonalPurchase,
    PersonalPurchaseInput, PersonalReorderRecommendation, ReturnDraft, ReturnDraftInput,
)
from backend.repositories.personal_extended import PersonalExtendedRepository
from backend.services.catalog import CatalogService


_MAX_BUNDLE_SEARCH_NODES = 100_000


def _key(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _owner(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 100:
        raise ValueError("user_id must contain 1–100 characters")
    return value


class PersonalExtendedService:
    def __init__(self, repository: PersonalExtendedRepository, catalog: CatalogService):
        self._repository = repository
        self._catalog = catalog

    def preferences(self, user_id: str) -> PersonalPreferences:
        user_id = _owner(user_id)
        return self._repository.get_preferences(user_id) or PersonalPreferences(user_id=user_id)

    def save_preferences(self, user_id: str, request: PersonalPreferencesInput) -> PersonalPreferences:
        user_id = _owner(user_id)
        supplier_ids = {item.id for item in self._catalog.list_suppliers()}
        if not set(request.preferred_supplier_ids) <= supplier_ids:
            raise LookupError("A preferred supplier is not present in the local catalog")
        record = PersonalPreferences(**request.model_dump(), user_id=user_id, updated_at=datetime.now(timezone.utc))
        return self._repository.save_preferences(record)

    def add_purchase(self, request: PersonalPurchaseInput) -> PersonalPurchase:
        product = self._catalog.product_by_id(request.product_id)
        if product is None:
            raise LookupError("Product not found")
        now = datetime.now(timezone.utc)
        if request.purchased_at > now:
            raise ValueError("A recorded purchase cannot be in the future")
        supplier = None
        if request.offer_id is not None:
            offer = self._catalog.offer_by_id(request.offer_id)
            if offer is None:
                raise LookupError("Offer not found")
            if offer.product_id != request.product_id:
                raise ValueError("Offer does not belong to the selected product")
            if offer.currency.upper() != request.currency:
                raise ValueError("Recorded currency differs from the selected offer currency")
            supplier = self._catalog.supplier_by_id(offer.supplier_id)
        payload = request.model_dump()
        # Preserve the entered offset: a seller's return deadline is a calendar
        # date, so silently shifting the recorded purchase date to UTC is lossy.
        payload.update(user_id=_owner(request.user_id))
        record = PersonalPurchase(
            **payload, purchase_id=f"personal-{uuid.uuid4().hex}", product_name=product.name,
            supplier_id=supplier.id if supplier else None, supplier_name=supplier.name if supplier else None,
            total_price=request.unit_price * request.quantity, created_at=now,
        )
        return self._repository.add_purchase(record)

    def purchases(self, user_id: str) -> list[PersonalPurchase]:
        return self._repository.list_purchases(_owner(user_id))

    def reorders(self, user_id: str, due_only: bool = False) -> list[PersonalReorderRecommendation]:
        now = datetime.now(timezone.utc)
        purchases = sorted(self.purchases(user_id), key=lambda item: (item.purchased_at, item.purchase_id), reverse=True)
        latest = {}
        for purchase in purchases:
            latest.setdefault(purchase.product_id, purchase)
        results = []
        offers = self._catalog.list_offers()
        for purchase in latest.values():
            if purchase.repeat_after_days is None:
                continue
            due_at = purchase.purchased_at + timedelta(days=purchase.repeat_after_days)
            status = "DUE" if due_at <= now else "SCHEDULED"
            if due_only and status != "DUE":
                continue
            candidates = [offer for offer in offers if offer.product_id == purchase.product_id
                          and offer.currency.upper() == purchase.currency
                          and offer.minimum_order_quantity <= purchase.quantity <= offer.quantity_available]
            offer = min(candidates, key=lambda item: (item.unit_price, item.id)) if candidates else None
            explanation = (
                f"Повтор по заданному циклу {purchase.repeat_after_days} дней после последней записанной покупки; "
                f"рекомендуемая дата {due_at.date().isoformat()}. "
                + ("Цена взята из текущего локального demo-предложения; доставка и налоги исключены."
                   if offer else "Нет доступного предложения на это количество и валюту; цена неизвестна.")
            )
            results.append(PersonalReorderRecommendation(
                product_id=purchase.product_id, product_name=purchase.product_name,
                source_purchase_id=purchase.purchase_id, quantity=purchase.quantity,
                repeat_after_days=purchase.repeat_after_days, due_at=due_at, status=status,
                current_offer_id=offer.id if offer else None, current_unit_price=offer.unit_price if offer else None,
                estimated_subtotal=offer.unit_price * purchase.quantity if offer else None,
                currency=purchase.currency, explanation=explanation,
            ))
        return sorted(results, key=lambda item: (item.due_at, item.product_id))

    def compatibility(self, request: CompatibilityRequest) -> CompatibilityResult:
        product = self._catalog.product_by_id(request.product_id)
        if product is None:
            raise LookupError("Product not found")
        if request.host_product_id is not None:
            if self._catalog.product_by_id(request.host_product_id) is None:
                raise LookupError("Host product not found")
            if request.host_product_id == request.product_id:
                raise ValueError("Host and component must be different products")
        component = request.component_specs
        if component.interface and product.interface and _key(component.interface) != _key(product.interface):
            raise ValueError("Provided component interface contradicts the catalog")
        interface = product.interface or component.interface
        host = request.host_specs
        checks = {
            "interface": (interface, host.accepted_interfaces, "Интерфейс", "membership"),
            "form_factor": (component.form_factor, host.accepted_form_factors, "Форм-фактор", "membership"),
            "dimensions": (component.length_mm, host.maximum_length_mm, "Длина, мм", "maximum"),
            "power": (component.required_power_w, host.available_power_w, "Мощность, Вт", "maximum"),
            "socket": (component.socket, host.accepted_sockets, "Разъём / сокет", "membership"),
        }
        findings = []
        for name in request.required_checks:
            actual, accepted, label, kind = checks[name]
            if actual is None or accepted is None:
                status, text = "UNKNOWN", f"{label}: не хватает характеристик компонента или принимающей системы."
            else:
                passed = (_key(str(actual)) in {_key(value) for value in accepted}
                          if kind == "membership" else actual <= accepted)
                status = "PASS" if passed else "FAIL"
                shown = ", ".join(accepted) if isinstance(accepted, list) else str(accepted)
                text = f"{label}: {actual}; допустимо системой: {shown or 'ничего'}."
            findings.append(CompatibilityFinding(check=name, status=status, explanation=text))
        verdict = ("INCOMPATIBLE" if any(item.status == "FAIL" for item in findings)
                   else "UNKNOWN" if any(item.status == "UNKNOWN" for item in findings) else "COMPATIBLE")
        return CompatibilityResult(product_id=product.id, product_name=product.name,
                                   host_product_id=request.host_product_id, verdict=verdict, findings=findings)

    def bundle(self, request: BundleRequest) -> BundleResult:
        preferences = self.preferences(request.user_id)
        if request.host_product_id is not None and self._catalog.product_by_id(request.host_product_id) is None:
            raise LookupError("Host product not found")
        suppliers = {item.id: item for item in self._catalog.list_suppliers()}
        offers = self._catalog.list_offers()
        check_assembly = len(request.items) > 1 or request.host_product_id is not None or bool(request.host_specs.model_fields_set)
        findings = []
        options = []
        blocked_by_compatibility = False
        for index, item in enumerate(request.items):
            if item.product_id is not None:
                product = self._catalog.product_by_id(item.product_id)
                if product is None:
                    raise LookupError(f"Product {item.product_id} not found")
                products = [product]
            else:
                products = self._catalog.search_products(item.product_query)
            candidates = []
            rejected_incompatible = False
            for product in products:
                if item.minimum_ram_gb is not None and (product.ram_gb is None or product.ram_gb < item.minimum_ram_gb):
                    continue
                capacity = product.capacity_gb or product.ssd_gb
                if item.minimum_capacity_gb is not None and (capacity is None or capacity < item.minimum_capacity_gb):
                    continue
                if (item.component_specs.interface and product.interface
                        and _key(item.component_specs.interface) != _key(product.interface)):
                    rejected_incompatible = True
                    continue
                compatibility = None
                if check_assembly and product.id != request.host_product_id:
                    compatibility = self.compatibility(CompatibilityRequest(
                        product_id=product.id, host_product_id=request.host_product_id,
                        host_specs=request.host_specs, component_specs=item.component_specs,
                        required_checks=request.required_checks,
                    ))
                    if compatibility.verdict == "INCOMPATIBLE":
                        rejected_incompatible = True
                        continue
                for offer in offers:
                    if (offer.product_id != product.id or offer.currency.upper() != request.currency
                            or not offer.minimum_order_quantity <= item.quantity <= offer.quantity_available):
                        continue
                    supplier = suppliers.get(offer.supplier_id)
                    if supplier is None:
                        continue
                    preference = (0 if product.brand in preferences.preferred_brands else 1,
                                  0 if supplier.id in preferences.preferred_supplier_ids else 1)
                    line = BundleLine(product_id=product.id, product_name=product.name, offer_id=offer.id,
                                      supplier_id=supplier.id, supplier_name=supplier.name, quantity=item.quantity,
                                      unit_price=offer.unit_price, subtotal=offer.unit_price * item.quantity,
                                      compatibility=compatibility)
                    candidates.append((line, offer.quantity_available, preference))
            candidates.sort(key=lambda option: (option[0].subtotal, option[2], option[0].product_id, option[0].offer_id))
            if not candidates:
                blocked_by_compatibility = blocked_by_compatibility or rejected_incompatible
                reason = "подтверждена несовместимость либо нет предложения с нужными характеристиками" if rejected_incompatible else "нет доступного предложения с нужными характеристиками, количеством и валютой"
                findings.append(f"Позиция {index + 1}: {reason}.")
            options.append(candidates)
        if any(not choices for choices in options):
            return BundleResult(outcome="BLOCKED", lines=[], merchandise_subtotal=Decimal("0"), currency=request.currency,
                                within_budget=False,
                                compatibility_verdict="INCOMPATIBLE" if blocked_by_compatibility else "UNKNOWN",
                                findings=findings)

        # Exact bounded basket search: eight requested lines at most; one offer per line.
        # Stocks are shared between repeated lines, so the same offer cannot be oversold.
        suffix_min = [Decimal("0")] * (len(options) + 1)
        for index in range(len(options) - 1, -1, -1):
            suffix_min[index] = suffix_min[index + 1] + options[index][0][0].subtotal
        best_lines = None
        best_total = None
        visited_nodes = 0

        def select(index, subtotal, used, selected):
            nonlocal best_lines, best_total, visited_nodes
            visited_nodes += 1
            if visited_nodes > _MAX_BUNDLE_SEARCH_NODES:
                raise ValueError("Bundle search is too broad for the local limit; narrow the product queries or use product IDs")
            if best_total is not None and subtotal + suffix_min[index] >= best_total:
                return
            if index == len(options):
                best_total, best_lines = subtotal, list(selected)
                return
            for line, stock, _ in options[index]:
                current = used.get(line.offer_id, 0)
                if current + line.quantity > stock:
                    continue
                used[line.offer_id] = current + line.quantity
                selected.append(line)
                select(index + 1, subtotal + line.subtotal, used, selected)
                selected.pop()
                used[line.offer_id] = current

        select(0, Decimal("0"), {}, [])
        if best_lines is None:
            return BundleResult(outcome="BLOCKED", lines=[], merchandise_subtotal=Decimal("0"), currency=request.currency,
                                within_budget=False, compatibility_verdict="UNKNOWN",
                                findings=["Недостаточно общего остатка предложений для всего комплекта."])
        results = [line.compatibility for line in best_lines if line.compatibility is not None]
        verdict = ("UNKNOWN" if any(result.verdict == "UNKNOWN" for result in results)
                   else "COMPATIBLE" if results else "NOT_APPLICABLE")
        if "power" in request.required_checks and request.host_specs.available_power_w is not None:
            known_power = sum((item.component_specs.required_power_w or Decimal("0")) * line.quantity
                              for item, line in zip(request.items, best_lines)
                              if line.product_id != request.host_product_id)
            if known_power > request.host_specs.available_power_w:
                verdict = "INCOMPATIBLE"
                findings.append(
                    f"Суммарная указанная мощность компонентов {known_power} Вт превышает доступные "
                    f"{request.host_specs.available_power_w} Вт с учётом количества."
                )
        within_budget = best_total <= request.budget_total
        outcome = ("BLOCKED" if not within_budget or verdict == "INCOMPATIBLE"
                   else "REVIEW_REQUIRED" if verdict == "UNKNOWN" else "READY_FOR_REVIEW")
        findings.append("Выбрана минимальная товарная сумма из доступных предложений; на каждую позицию используется один поставщик.")
        if not within_budget:
            findings.append(f"Самый дешёвый доступный комплект превышает бюджет на {best_total - request.budget_total} {request.currency}.")
        if verdict == "UNKNOWN":
            findings.append("Совместимость не подтверждена: в каталоге или введённых данных не хватает характеристик системы.")
        if results:
            findings.append("Совместимость оценена только по указанным проверкам и введённым пользователем характеристикам.")
        findings.append("Доставка и налоги исключены; локальные demo-остатки не зарезервированы.")
        return BundleResult(outcome=outcome, lines=best_lines, merchandise_subtotal=best_total,
                            currency=request.currency, within_budget=within_budget,
                            compatibility_verdict=verdict, findings=findings)

    @staticmethod
    def _return_deadline(record: ReturnDraft) -> ReturnDraft:
        if record.return_deadline is None:
            status = "UNKNOWN"
            explanation = "Правила продавца и срок возврата неизвестны. Сохранён локальный черновик; проверьте условия у продавца."
        else:
            today = datetime.now(timezone.utc).date()
            status = "WITHIN_PROVIDED_DEADLINE" if today <= record.return_deadline else "PAST_PROVIDED_DEADLINE"
            explanation = (f"Сравнение с указанной пользователем датой {record.return_deadline.isoformat()}; "
                           f"источник: {record.policy_source}. Правила и право на возврат сервисом не подтверждены.")
        return record.model_copy(update={"deadline_status": status, "explanation": explanation})

    def create_return(self, request: ReturnDraftInput) -> ReturnDraft:
        user_id = _owner(request.user_id)
        purchase = self._repository.get_purchase(request.purchase_id, user_id)
        if purchase is None:
            raise LookupError("Personal purchase not found")
        if request.quantity > purchase.quantity:
            raise ValueError("Return quantity exceeds the recorded purchase quantity")
        if not request.reason.strip():
            raise ValueError("Return reason must not be blank")
        if request.return_deadline is not None and request.return_deadline < purchase.purchased_at.date():
            raise ValueError("Return deadline cannot precede the recorded purchase")
        payload = request.model_dump()
        payload["user_id"] = user_id
        record = ReturnDraft(**payload, return_id=f"return-{uuid.uuid4().hex}", product_name=purchase.product_name,
                             purchased_at=purchase.purchased_at, created_at=datetime.now(timezone.utc),
                             deadline_status="UNKNOWN", explanation="")
        return self._repository.add_return(self._return_deadline(record))

    def returns(self, user_id: str) -> list[ReturnDraft]:
        return [self._return_deadline(record) for record in self._repository.list_returns(_owner(user_id))]

    def cancel_return(self, return_id: str, user_id: str) -> ReturnDraft:
        return self._return_deadline(self._repository.cancel_return(return_id, _owner(user_id)))
