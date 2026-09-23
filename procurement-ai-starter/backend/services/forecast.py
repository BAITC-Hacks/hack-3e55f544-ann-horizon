from decimal import Decimal, ROUND_HALF_UP

from backend.models.purchase import DemandForecast, InventoryItem
from backend.services.inventory import InventoryService


class DemandForecastService:
    def __init__(self, inventory: InventoryService, window_months: int = 4) -> None:
        self._inventory = inventory
        self._window = window_months

    def forecast(self, item: InventoryItem) -> DemandForecast:
        records = self._inventory.demand_history(item.product_id, self._window)
        if not records:
            return DemandForecast(
                product_id=item.product_id,
                product_name=item.product_name,
                status="insufficient_data",
                periods_used=0,
                source_label=item.data_source,
            )
        average_month = (Decimal(sum(record.consumed_quantity for record in records)) / len(records)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        average_day = (average_month / Decimal("30")).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        source_label = "DEMO DATA" if all(record.data_source == "DEMO DATA" for record in records) else "LOCAL HISTORY"
        return DemandForecast(
            product_id=item.product_id,
            product_name=item.product_name,
            status="available",
            periods_used=len(records),
            average_monthly_demand=average_month,
            average_daily_demand=average_day,
            source_label=source_label,
        )
