from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from statistics import median

from backend.models.purchase import Offer, PriceHistoryComparison, PriceHistoryRecord, PriceSummary


class PricingService:
    HISTORY_LOOKBACK_DAYS = 90
    MINIMUM_OBSERVATIONS = 3
    ANOMALY_THRESHOLD_PERCENT = Decimal("20")

    @staticmethod
    def line_subtotal(unit_price: Decimal, quantity: int) -> Decimal:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        return unit_price * quantity

    @staticmethod
    def summarize(
        offers: list[Offer], currency: str, history: list[PriceHistoryRecord] | None = None,
        as_of: date | None = None,
    ) -> PriceSummary:
        prices = sorted(offer.unit_price for offer in offers if offer.currency == currency)
        if not prices:
            return PriceSummary(currency=currency, offer_count=0)
        average = (sum(prices, Decimal("0")) / len(prices)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        mid = median(prices)
        return PriceSummary(
            currency=currency,
            offer_count=len(prices),
            minimum_unit_price=prices[0],
            maximum_unit_price=prices[-1],
            average_unit_price=average,
            median_unit_price=Decimal(str(mid)),
            shipping_tax_status="unknown and excluded",
            history_comparisons=PricingService.compare_history(offers, history or [], currency, as_of),
        )

    @classmethod
    def compare_history(
        cls, offers: list[Offer], history: list[PriceHistoryRecord], currency: str,
        as_of: date | None = None,
    ) -> list[PriceHistoryComparison]:
        today = as_of or date.today()
        start = today - timedelta(days=cls.HISTORY_LOOKBACK_DAYS)
        result: list[PriceHistoryComparison] = []
        for offer in sorted(offers, key=lambda item: item.id):
            if offer.currency != currency:
                continue
            # Count distinct observation dates, and do not attach demo evidence to live offers.
            by_date = {
                record.observed_on: record for record in history
                if offer.data_source == "DEMO DATA"
                and (record.offer_id, record.product_id, record.supplier_id, record.currency) == (
                    offer.id, offer.product_id, offer.supplier_id, currency
                )
                and start <= record.observed_on <= today
            }
            records = [by_date[key] for key in sorted(by_date)]
            baseline = None
            deviation = None
            status = "unknown"
            if len(records) >= cls.MINIMUM_OBSERVATIONS:
                baseline = median(record.unit_price for record in records)
                raw_deviation = (offer.unit_price - baseline) / baseline * Decimal("100")
                deviation = raw_deviation.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if raw_deviation >= cls.ANOMALY_THRESHOLD_PERCENT:
                    status = "above_history"
                elif raw_deviation <= -cls.ANOMALY_THRESHOLD_PERCENT:
                    status = "below_history"
                else:
                    status = "within_range"
            result.append(PriceHistoryComparison(
                offer_id=offer.id, currency=currency, current_unit_price=offer.unit_price,
                status=status, sample_count=len(records), minimum_observations=cls.MINIMUM_OBSERVATIONS,
                as_of=today, window_start=start,
                history_from=records[0].observed_on if records else None,
                history_to=records[-1].observed_on if records else None,
                median_historical_unit_price=baseline, deviation_percent=deviation,
                anomaly_threshold_percent=cls.ANOMALY_THRESHOLD_PERCENT,
            ))
        return result
