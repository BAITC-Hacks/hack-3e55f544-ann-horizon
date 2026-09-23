import re
from decimal import Decimal

from backend.models.purchase import PurchaseRequest, UserContext


_QUANTITY_UNITS = r"(?:шт(?:\.|ук\w*)?|единиц\w*|units?|pieces?|pcs)"
_PRODUCT_QUANTITY = r"(?:laptops?|notebooks?|ноутбук\w*|ssd|монитор\w*|monitors?|keyboards?|клавиатур\w*|mice|мыш\w*|headsets?|гарнитур\w*|наушник\w*)"
_CAPACITY_UNITS = r"(?:tb|тб|gb|гб)"


def _number(raw: str) -> Decimal:
    compact = re.sub(r"\s+", "", raw)
    if "," in compact and "." in compact:
        decimal_sep = "," if compact.rfind(",") > compact.rfind(".") else "."
        group_sep = "." if decimal_sep == "," else ","
        compact = compact.replace(group_sep, "").replace(decimal_sep, ".")
    elif "," in compact or "." in compact:
        separator = "," if "," in compact else "."
        tail = compact.rsplit(separator, 1)[1]
        if len(tail) == 3:
            compact = compact.replace(separator, "")
        else:
            compact = compact.replace(separator, ".")
    return Decimal(compact)


def _capacity_gb(value: str, unit: str) -> int:
    amount = Decimal(value.replace(",", "."))
    if unit.casefold() in {"tb", "тб"}:
        amount *= 1024
    return int(amount)


class IntakeAgent:
    """Offline natural-language extractor for the supported demo request fields."""

    def parse(self, text: str, user_context: UserContext | None = None) -> PurchaseRequest:
        clean = text.strip()
        if not clean:
            raise ValueError("Текст закупочного запроса пуст.")

        quantity = self._quantity(clean)
        product_query = self._product_query(clean)
        required_specs = self._specifications(clean)
        preferred_brand = self._preferred_brand(clean)
        currency = self._currency(clean, user_context)
        budget_total, budget_per_unit = self._budget(clean, quantity)
        max_delivery_days = self._delivery_limit(clean)
        priority = self._priority(clean)

        return PurchaseRequest(
            product_query=product_query,
            quantity=quantity,
            budget_total=budget_total,
            budget_per_unit=budget_per_unit,
            currency=currency,
            max_delivery_days=max_delivery_days,
            required_specs=required_specs,
            preferred_brand=preferred_brand,
            priority=priority,
            user_context=user_context or UserContext(),
            source_text=clean,
        )

    @staticmethod
    def _quantity(text: str) -> int:
        explicit = re.search(rf"\b(\d[\d ,]*)\s*{_QUANTITY_UNITS}\b", text, re.IGNORECASE)
        if explicit:
            return int(re.sub(r"\D", "", explicit.group(1)))
        by_product = re.search(rf"\b(\d[\d ,]*)\s*(?:[xх×]\s*)?{_PRODUCT_QUANTITY}\b", text, re.IGNORECASE)
        if by_product:
            return int(re.sub(r"\D", "", by_product.group(1)))
        return 1

    @staticmethod
    def _product_query(text: str) -> str:
        if re.search(r"\b(laptop|laptops|notebook|ноутбук\w*)\b", text, re.IGNORECASE):
            return "laptop"
        if re.search(r"\b(ssd|накопител\w*|диск\w*)\b", text, re.IGNORECASE):
            return "ssd"
        return text[:200]

    @staticmethod
    def _specifications(text: str) -> dict[str, int | str]:
        specs: dict[str, int | str] = {}
        ram_patterns = (
            rf"(?:ram|оператив\w*\s+памят\w*)\D{{0,24}}(\d+(?:[.,]\d+)?)\s*(?:gb|гб)\b",
            rf"(\d+(?:[.,]\d+)?)\s*(?:gb|гб)\s*(?:ram|оператив\w*\s+памят\w*)",
        )
        for pattern in ram_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                specs["ram_gb"] = int(Decimal(match.group(1).replace(",", ".")))
                break

        storage_patterns = (
            rf"(?:ssd|storage|capacity|накопител\w*|объ[её]м\s+(?:ssd|диска|накопителя))\D{{0,28}}(\d+(?:[.,]\d+)?)\s*({_CAPACITY_UNITS})",
            rf"(\d+(?:[.,]\d+)?)\s*({_CAPACITY_UNITS})\s*(?:ssd|storage|накопител\w*)",
        )
        for pattern in storage_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                specs["ssd_gb"] = _capacity_gb(match.group(1), match.group(2))
                break

        interface = re.search(r"\b(NVMe|SATA|PCIe)\b", text, re.IGNORECASE)
        if interface:
            specs["interface"] = interface.group(1).upper()
        return specs

    @staticmethod
    def _preferred_brand(text: str) -> str | None:
        match = re.search(
            r"(?:prefer(?:red)?(?:\s+brand)?|желательно|предпочтительно|бренд)\s+([A-Za-zА-Яа-яЁё0-9-]+)",
            text,
            re.IGNORECASE,
        )
        return match.group(1) if match else None

    @staticmethod
    def _currency(text: str, user_context: UserContext | None) -> str:
        found = re.search(r"(KZT|USD|EUR|GBP|₸|тенге|тг|\$|€|£)", text, re.IGNORECASE)
        if not found:
            return user_context.currency if user_context else "KZT"
        token = found.group(1).upper()
        return {"₸": "KZT", "ТЕНГЕ": "KZT", "ТГ": "KZT", "$": "USD", "€": "EUR", "£": "GBP"}.get(token, token)

    @staticmethod
    def _budget(text: str, quantity: int) -> tuple[Decimal | None, Decimal | None]:
        pattern = (
            r"(?:budget|бюджет|price|цена|стоимость|up\s+to|under|below|no\s+more\s+than|не\s+дороже|до)"
            r"(?:\s+(?:per\s+unit|total|за\s*(?:штук\w*|единиц\w*|шт\.?|ед\.?)|общ(?:ий|его)))?"
            r"\s*(?:[:=]\s*)?([0-9][0-9\s,.]*[0-9]|[0-9])"
        )
        found = None
        for match in re.finditer(pattern, text, re.IGNORECASE):
            tail = text[match.end():match.end() + 18]
            if re.match(r"\s*(?:дн\w*|days?)\b", tail, re.IGNORECASE):
                continue
            if match.group(1).strip() in {"7", "10", "14", "30"} and re.match(r"\s*дн", tail, re.IGNORECASE):
                continue
            found = match
        if not found:
            return None, None
        try:
            amount = _number(found.group(1))
        except Exception:
            return None, None
        surrounding = text[max(0, found.start() - 20):min(len(text), found.end() + 32)].casefold()
        per_unit = bool(re.search(r"за\s*(?:штук\w*|единиц\w*|шт\.?|ед\.?)|per\s+unit|each", surrounding))
        total_label = bool(re.search(r"общ(?:ий|его)\s+бюджет|total\s+budget", surrounding))
        if per_unit or quantity == 1 and not total_label:
            return None, amount
        return amount, None

    @staticmethod
    def _delivery_limit(text: str) -> int | None:
        pattern = r"(?:максимум|не\s+более|max(?:imum)?|no\s+more\s+than|at\s+most|within|delivery\s+in|доставк\w*\s*(?:до|за)?|до)\s*(?:(?:of|за)\s*)?(\d+)\s*(?:дн\w*|days?)\b"
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        return int(matches[-1].group(1)) if matches else None

    @staticmethod
    def _priority(text: str) -> str:
        lowered = text.casefold()
        if any(token in lowered for token in ("fastest", "as soon as", "как можно быстрее", "скорость", "срочно")):
            return "speed"
        if any(token in lowered for token in ("best quality", "quality", "качество", "надёжност", "надежност")):
            return "quality"
        if any(token in lowered for token in ("cheapest", "lowest price", "самый дешёв", "самый дешев", "минимальн")):
            return "price"
        return "balanced"
