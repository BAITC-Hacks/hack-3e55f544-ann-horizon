import sqlite3
import unittest
import uuid
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agents.manager import ManagerAgent
from backend.api_analytics import router
from backend.integrations.catalog import SQLiteCatalogAdapter
from backend.repositories.procurement import SQLiteProcurementRepository
from backend.services.analytics import AnalyticsService
from backend.tools.procurement import ProcurementTools


class AnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = Path(__file__).resolve().parents[1] / "data" / f"analytics-test-{uuid.uuid4().hex}.db"
        self.repo = SQLiteProcurementRepository(self.db_path)
        self.addCleanup(self.db_path.unlink, missing_ok=True)
        self.tools = ProcurementTools(SQLiteCatalogAdapter(self.repo), inventory_repository=self.repo, persistence_repository=self.repo)

    def test_empty_overview_has_unknown_ratios_and_no_invented_performance(self) -> None:
        overview = AnalyticsService(self.repo).overview()
        self.assertEqual((overview.order_count, overview.active_order_count, overview.pending_approval_count), (0, 0, 0))
        self.assertEqual(overview.currency_merchandise_totals, [])
        self.assertIsNone(overview.damage_fraction)
        for metric in (overview.savings, overview.average_actual_delivery_days, overview.supplier_reliability):
            self.assertIsNone(metric.value)
            self.assertTrue(metric.reason)
        self.assertEqual((overview.low_stock_count, overview.stockout_count), (2, 0))

    def test_dashboard_aggregates_all_rows_exact_money_latest_delays_and_reorder_runs(self) -> None:
        template = ManagerAgent(self.tools).plan_text("Купить 1 SSD")
        now = "2026-09-23T12:00:00+00:00"
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("PRAGMA foreign_keys=ON")

            def add_order(key, currency, subtotals, status="DRAFT"):
                total = sum((Decimal(amount) for amount in subtotals), Decimal("0"))
                quantity = 3 if key == "kzt-0" else 1
                stored_plan = template.model_copy(update={
                    "plan_id": key, "currency": currency, "merchandise_subtotal": total, "total_cost": total,
                    "request": template.request.model_copy(update={"currency": currency, "quantity": quantity}),
                    "quantity_requested": quantity, "quantity_planned": quantity,
                })
                connection.execute(
                    """INSERT INTO procurement_plans
                    (id,created_at,status,user_id,user_type,product_query,quantity_requested,quantity_planned,
                     merchandise_subtotal,currency,source_label,approval_status,plan_json)
                    VALUES (?,?,'READY_FOR_REVIEW','demo-user','business','ssd',?,?,?,?,'DEMO DATA','NOT_REQUIRED',?)""",
                    (key, now, quantity, quantity, str(total), currency, stored_plan.model_dump_json()),
                )
                connection.execute(
                    "INSERT INTO purchase_orders(id,plan_id,status,external_order_created,created_at,updated_at) VALUES (?,?,?,0,?,?)",
                    (key, key, status, now, now),
                )
                item_ids = []
                for amount in subtotals:
                    cursor = connection.execute(
                        """INSERT INTO purchase_order_items(order_id,offer_id,product_id,supplier_id,quantity,unit_price,merchandise_subtotal)
                        VALUES (?,105,4,2,?,?,?)""", (key, quantity, str(Decimal(amount) / quantity), amount),
                    )
                    item_ids.append(cursor.lastrowid)
                return item_ids

            first_item = None
            for index in range(101):
                item_ids = add_order(f"kzt-{index}", "KZT", ["0.30" if index == 0 else "0.10"], "RECEIVED" if index == 0 else "DRAFT")
                if index == 0:
                    first_item = item_ids[0]
            add_order("usd", "USD", ["0.10", "0.20"])
            add_order("cancelled", "KZT", ["999.99"], "CANCELLED")
            for index, key in enumerate(("kzt-1", "usd")):
                connection.execute(
                    """INSERT INTO approval_records(approval_id,plan_id,status,required_role,requested_by,amount,currency,created_at)
                    VALUES (?,?,'PENDING','finance','demo-user','0.10',?,?)""", (f"approval-{index}", key, "USD" if key == "usd" else "KZT", now),
                )
            # Repeated delayed events count once; a later shipped event clears an old delay.
            for key, status in (
                ("kzt-1", "DELAYED"), ("kzt-1", "SHIPPED"),
                ("kzt-2", "DELAYED"), ("kzt-2", "DELAYED"), ("usd", "DELAYED"),
                ("cancelled", "DELAYED"), ("kzt-0", "DELAYED"),
            ):
                connection.execute(
                    "INSERT INTO delivery_events(event_id,order_id,supplier_id,status,created_at) VALUES (?,?,2,?,?)",
                    (uuid.uuid4().hex, key, status, now),
                )
            connection.execute("UPDATE inventory SET on_hand=10,reserved=10 WHERE product_id=4")
            connection.execute("UPDATE inventory SET on_hand=12,reserved=2 WHERE product_id=3")
            connection.execute(
                """INSERT INTO receiving_records(receiving_id,order_id,order_item_id,product_id,expected_quantity,
                   received_quantity,damaged_quantity,accepted_quantity,received_at)
                   VALUES ('receipt-1','kzt-0',?,4,3,3,1,2,?)""", (first_item, now),
            )
            for action, at in (
                ("reorder_recommendation_created", "2026-09-20T10:00:00+00:00"),
                ("reorder_recommendation_created", "2026-09-20T10:00:00+00:00"),
                ("reorder_analysis_no_action", "2026-09-21T10:00:00+00:00"),
            ):
                connection.execute(
                    "INSERT INTO audit_log(actor,action,entity_type,entity_id,occurred_at,details_json) VALUES ('system',?,'reorder','legacy',?,'{}')",
                    (action, at),
                )
        self.repo.log_reorder_analysis([])
        self.repo.log_reorder_analysis(ManagerAgent(self.tools).reorder_recommendations())
        before_audit = len(self.repo.list_audit_events(500))
        overview = self.tools.procurement_overview()
        self.assertEqual((overview.order_count, overview.active_order_count), (103, 101))
        self.assertEqual(overview.pending_approval_count, 2)
        self.assertEqual((overview.low_stock_count, overview.stockout_count), (1, 1))
        self.assertEqual((overview.delayed_supplier_count, overview.delayed_shipment_count), (1, 2))
        self.assertEqual(overview.reorder_analysis_count, 4)
        self.assertEqual((overview.received_unit_count, overview.accepted_unit_count, overview.damaged_unit_count), (3, 2, 1))
        self.assertEqual(overview.damage_fraction, Decimal("0.333333"))
        currencies = {row.currency: row for row in overview.currency_merchandise_totals}
        self.assertEqual(currencies["KZT"].order_count, 101)
        self.assertEqual(currencies["KZT"].order_merchandise_total, Decimal("10.30"))
        self.assertEqual(currencies["KZT"].average_order_merchandise_value, Decimal("0.10"))
        self.assertEqual(currencies["USD"].order_count, 1)
        self.assertEqual(currencies["USD"].order_merchandise_total, Decimal("0.30"))
        self.assertEqual(currencies["USD"].average_order_merchandise_value, Decimal("0.30"))
        app = FastAPI()
        app.include_router(router)
        with patch("backend.api.get_manager", return_value=ManagerAgent(self.tools)), TestClient(app) as client:
            response = client.get("/api/procurement/analytics/overview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["order_count"], 103)
        self.assertEqual(response.json()["currency_merchandise_totals"][1]["order_merchandise_total"], "0.30")
        self.assertEqual(len(self.repo.list_audit_events(500)), before_audit)


if __name__ == "__main__":
    unittest.main()
