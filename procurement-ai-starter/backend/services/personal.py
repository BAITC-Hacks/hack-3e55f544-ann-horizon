from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass(frozen=True)
class PriceWatchDecision:
    next_status: str
    event_type: str | None
    change_amount: Decimal


class PriceWatchService:
    """Evaluate one local price snapshot without external feeds or notifications."""

    @staticmethod
    def evaluate(
        previous_price: Decimal,
        current_price: Decimal,
        target_price: Decimal,
        status: str,
    ) -> PriceWatchDecision:
        if status != "ACTIVE":
            return PriceWatchDecision(status, None, Decimal("0"))
        change = previous_price - current_price
        if current_price <= target_price:
            return PriceWatchDecision("TRIGGERED", "TARGET_REACHED", change)
        if change > 0:
            return PriceWatchDecision("ACTIVE", "PRICE_DROP", change)
        return PriceWatchDecision("ACTIVE", None, change)


class PurchaseReminderService:
    @staticmethod
    def status(stored_status: str, remind_at: datetime, now: datetime | None = None) -> str:
        if stored_status != "OPEN":
            return stored_status
        current = now or datetime.now(timezone.utc)
        due_at = remind_at if remind_at.tzinfo else remind_at.replace(tzinfo=timezone.utc)
        return "DUE" if due_at <= current else "SCHEDULED"