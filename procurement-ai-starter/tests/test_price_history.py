"""Synthetic evidence must stay dated, offer-specific, and clearly labelled."""

import sqlite3
import unittest
import uuid
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from backend.agents.manager import ManagerAgent
from backend.integrations.catalog import SampleCatalogAdapter, SQLiteCatalogAdapter
from backend.models.purchase import Offer, PriceHistoryRecord, PurchaseRequest
from backend.repositories.catalog import JsonCatalogRepository
from backend.repositories.procurement import SQLiteProcurementRepository
from backend.services.pricing import PricingService
from backend.services.risk import RiskService


class PriceHistoryTests(unittest.TestCase):
    as_of = date(2026, 9, 23)

    @staticmethod
    def offer(price: str = "100", **updates) -> Offer:
        payload = dict(id=1, product_id=1, supplier_id=1, unit_price=price, quantity_available=10,
                       delivery_days=1, warranty_months=12, currency="KZT", data_source="DEMO DATA")
        payload.update(updates)
        return Offer(**payload)

    @staticmethod
    def record(day: date, price: str = "100", **updates) -> PriceHistoryRecord:
        payload = dict(offer_id=1, product_id=1, supplier_id=1, observed_on=day,
                       unit_price=price, currency="KZT", data_source="DEMO DATA")
        payload.update(updates)
        return PriceHistoryRecord(**payload)

    def test_anomaly_uses_median_decimal_arithmetic_and_unrounded_threshold(self) -> None:
        records = [self.record(self.as_of - timedelta(days=i), price) for i, price in enumerate(("99", "100", "101"))]
        for price, status, deviation in (
            ("120", "above_history", "20.00"), ("80", "below_history", "-20.00"),
            ("119.999", "within_range", "20.00"), ("100", "within_range", "0.00"),
        ):
            with self.subTest(price=price):
                summary = PricingService.summarize([self.offer(price)], "KZT", records, self.as_of)
                comparison = summary.history_comparisons[0]
                self.assertEqual(comparison.status, status)
                self.assertEqual(comparison.deviation_percent, Decimal(deviation))
                self.assertEqual(comparison.median_historical_unit_price, Decimal("100"))
                self.assertEqual(comparison.sample_count, 3)
                self.assertEqual(summary.minimum_unit_price, Decimal(price))

    def test_history_window_excludes_old_and_future_prices_and_counts_distinct_dates(self) -> None:
        start = self.as_of - timedelta(days=90)
        records = [
            self.record(start - timedelta(days=1), "100000"), self.record(start),
            self.record(self.as_of - timedelta(days=1)), self.record(self.as_of),
            self.record(self.as_of + timedelta(days=1), "1"),
        ]
        result = PricingService.compare_history([self.offer()], records, "KZT", self.as_of)[0]
        self.assertEqual(result.status, "within_range")
        self.assertEqual(result.sample_count, 3)
        self.assertEqual(result.history_from, start)
        self.assertEqual(result.history_to, self.as_of)
        self.assertEqual(result.window_start, start)
        self.assertEqual(result.median_historical_unit_price, Decimal("100"))
        repeated = [self.record(self.as_of), self.record(self.as_of), self.record(start)]
        insufficient = PricingService.compare_history([self.offer()], repeated, "KZT", self.as_of)[0]
        self.assertEqual(insufficient.sample_count, 2)
        self.assertEqual(insufficient.status, "unknown")
        self.assertIsNone(insufficient.median_historical_unit_price)
        self.assertIsNone(insufficient.deviation_percent)
        expired = PricingService.compare_history([self.offer()], records, "KZT", date(2027, 1, 1))[0]
        self.assertEqual(expired.status, "unknown")
        self.assertEqual(expired.sample_count, 0)

    def test_other_offers_currencies_suppliers_and_live_data_do_not_supply_evidence(self) -> None:
        records = [
            self.record(self.as_of), self.record(self.as_of - timedelta(days=1)),
            self.record(self.as_of - timedelta(days=2), offer_id=2),
            self.record(self.as_of - timedelta(days=3), currency="USD"),
            self.record(self.as_of - timedelta(days=4), supplier_id=2),
            self.record(self.as_of - timedelta(days=5), product_id=2),
        ]
        result = PricingService.compare_history([self.offer()], records, "KZT", self.as_of)[0]
        self.assertEqual((result.sample_count, result.status), (2, "unknown"))
        result = PricingService.compare_history([self.offer(data_source="VERIFIED")], records, "KZT", self.as_of)[0]
        self.assertEqual((result.sample_count, result.status), (0, "unknown"))

    def test_sample_and_sqlite_adapters_expose_only_matching_demo_history(self) -> None:
        records = SampleCatalogAdapter().price_history()
        self.assertEqual(len(records), 84)
        self.assertTrue(all(row.data_source == "DEMO DATA" for row in records))
        db_path = Path(__file__).resolve().parents[1] / "data" / f"price-history-test-{uuid.uuid4().hex}.db"
        self.addCleanup(db_path.unlink, missing_ok=True)
        repo = SQLiteProcurementRepository(db_path)
        self.assertEqual(SQLiteCatalogAdapter(repo).price_history(), records)
        with closing(sqlite3.connect(db_path)) as connection, connection:
            connection.execute("UPDATE offers SET data_source='VERIFIED' WHERE id=105")
            connection.execute("UPDATE offers SET currency='USD' WHERE id=106")
        filtered = SQLiteCatalogAdapter(repo).price_history()
        self.assertEqual(len(filtered), 76)
        self.assertTrue(all(row.offer_id not in {105, 106} for row in filtered))

    def test_repository_rejects_duplicate_dates_and_mismatched_history_references(self) -> None:
        repo = JsonCatalogRepository()
        source = {
            "products.json": repo.list_products(), "suppliers.json": repo.list_suppliers(),
            "offers.json": repo.list_offers(), "sample_price_history.json": repo.list_price_history(),
        }
        for invalid in (
            [*source["sample_price_history.json"], source["sample_price_history.json"][0]],
            [source["sample_price_history.json"][0].model_copy(update={"supplier_id": 999})],
        ):
            with self.subTest(size=len(invalid)):
                changed = {**source, "sample_price_history.json": invalid}
                with patch.object(JsonCatalogRepository, "_read", side_effect=lambda name, model: changed[name]):
                    with self.assertRaises(ValueError):
                        JsonCatalogRepository()

    def test_price_risk_uses_selected_offer_evidence_and_marks_missing_history_unknown(self) -> None:
        with patch("backend.services.pricing.date") as date_clock:
            date_clock.today.return_value = self.as_of
            plan = ManagerAgent().plan(PurchaseRequest(product_query="ssd", quantity=1, required_specs={"ssd_gb": 2048}))
        self.assertEqual(plan.selected_offer_ids, [108])
        price_risk = next(item for item in plan.risks if item.risk_type == "price")
        self.assertEqual(price_risk.severity, "high")
        self.assertEqual(price_risk.entity_id, "108")
        self.assertTrue(any("DEMO DATA" in item for item in price_risk.evidence))
        missing = plan.model_copy(update={"price_summary": plan.price_summary.model_copy(update={"history_comparisons": []})})
        unknown = next(item for item in RiskService().assess(missing.request, missing) if item.risk_type == "price")
        self.assertEqual(unknown.severity, "unknown")


if __name__ == "__main__":
    unittest.main()
