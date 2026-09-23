from decimal import Decimal, ROUND_CEILING

from backend.models.purchase import DemandForecast, InventoryItem, ReorderRecommendation


class ReorderService:
    @staticmethod
    def recommend(
        item: InventoryItem,
        forecast: DemandForecast,
        lead_time_days: int | None,
    ) -> ReorderRecommendation:
        threshold_reached = item.available <= item.reorder_point
        lead_demand = 0
        if forecast.average_monthly_demand is not None and lead_time_days is not None:
            raw_lead_demand = forecast.average_monthly_demand * Decimal(lead_time_days) / Decimal("30")
            lead_demand = int(raw_lead_demand.to_integral_value(rounding=ROUND_CEILING))
        target_stock = item.reorder_point + lead_demand
        quantity = max(0, target_stock - item.available) if threshold_reached else 0
        if not threshold_reached:
            reason = f"Доступно {item.available}; точка пополнения {item.reorder_point} ещё не достигнута."
        elif forecast.status == "insufficient_data":
            reason = (
                f"Доступно {item.available} при точке пополнения {item.reorder_point}; "
                "истории спроса недостаточно, поэтому размер рассчитан только до точки пополнения."
            )
        else:
            reason = (
                f"Доступно {item.available} при точке пополнения {item.reorder_point}; "
                f"к точке добавлен прогноз спроса {lead_demand} шт. за {lead_time_days} дней поставки."
            )
        return ReorderRecommendation(
            product_id=item.product_id,
            product_name=item.product_name,
            on_hand=item.on_hand,
            reserved=item.reserved,
            available=item.available,
            reorder_point=item.reorder_point,
            forecast=forecast,
            lead_time_days=lead_time_days,
            expected_lead_time_demand=lead_demand,
            recommended_quantity=quantity,
            reason=reason,
            source_label="DEMO DATA" if item.data_source == "DEMO DATA" or forecast.source_label == "DEMO DATA" else "LOCAL DATA",
        )
