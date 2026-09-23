from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol

from backend.models.analytics import (
    MerchandiseCurrencyOverview,
    ProcurementAnalyticsSnapshot,
    ProcurementOverview,
    UnavailableMetric,
)


class AnalyticsRepository(Protocol):
    def procurement_analytics_snapshot(self) -> ProcurementAnalyticsSnapshot: ...


class AnalyticsService:
    """Derive metrics from a complete repository snapshot without triggering workflows."""

    def __init__(self, repository: AnalyticsRepository) -> None:
        self._repository = repository

    def overview(self) -> ProcurementOverview:
        snapshot = self._repository.procurement_analytics_snapshot()
        currencies = [MerchandiseCurrencyOverview(
            **row.model_dump(),
            average_order_merchandise_value=(row.order_merchandise_total / row.order_count).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ) if row.order_count else None,
        ) for row in snapshot.currency_merchandise_totals]
        fraction = (
            Decimal(snapshot.damaged_unit_count) / snapshot.received_unit_count
        ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP) if snapshot.received_unit_count else None
        return ProcurementOverview(
            **snapshot.model_dump(exclude={"currency_merchandise_totals"}),
            currency_merchandise_totals=currencies,
            damage_fraction=fraction,
            savings=UnavailableMetric(reason="Нет сопоставимой утверждённой базовой стоимости и подтверждённой фактической суммы покупки."),
            average_actual_delivery_days=UnavailableMetric(reason="Нет полной подтверждённой истории времени размещения заказов и завершения всех поставок."),
            supplier_reliability=UnavailableMetric(reason="Нет проверенной истории исполнения поставщиков; DEMO-рейтинги не являются фактической надёжностью."),
            calculation_notes=[
                "Охват: все записи локальной базы. Активные заказы — все статусы, кроме RECEIVED и CANCELLED.",
                "Суммы и средний заказ — только стоимость товаров (merchandise), без доставки и налогов; отменённые заказы исключены. Валюты не объединяются.",
                "Низкий остаток: доступно больше нуля, но не выше порога пополнения; stockout: доступно ноль. Товары без записи складского остатка не учитываются.",
                "Задержки учитывают последний зарегистрированный статус пары заказ/поставщик; завершённые и отменённые заказы исключены.",
                "Доля повреждений = повреждённые / все полученные единицы; при отсутствии приёмки значение неизвестно.",
                "Запуски пополнения считаются по журналу; старые записи рекомендаций одного времени считаются одним историческим запуском.",
            ],
        )
