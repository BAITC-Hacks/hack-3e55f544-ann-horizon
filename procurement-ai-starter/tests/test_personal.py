"""Behavioral coverage for local personal shopping and the v5 migration."""

import sqlite3
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from backend.agents.manager import ManagerAgent
from backend.integrations.catalog import SQLiteCatalogAdapter
from backend.models.purchase import (
    ApprovalDecision,
    DeliveryUpdate,
    InvoiceLineInput,
    InvoiceSubmission,
    PriceWatchInput,
    PriceWatchStatusUpdate,
    PurchaseReminderInput,
    PurchaseReminderUpdate,
    WishlistEntryInput,
)
from backend.repositories.procurement import SQLiteProcurementRepository
from backend.services.personal import PurchaseReminderService
from backend.tools.procurement import ProcurementTools


class PersonalShoppingTests(unittest.TestCase):
    def setUp(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        self.db_path = project_root / "data" / f"personal-test-{uuid.uuid4().hex}.db"
        self.repo = SQLiteProcurementRepository(self.db_path)
        self.addCleanup(self.db_path.unlink, missing_ok=True)

    def update_offer(self, offer_id: int, price: str, stock: int = 100) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                "UPDATE offers SET unit_price=?,quantity_available=? WHERE id=?",
                (price, stock, offer_id),
            )

    def test_wishlist_duplicate_and_owner_scope_survive_reopen(self) -> None:
        alice = self.repo.add_wishlist_item(WishlistEntryInput(user_id="alice", product_id=4))
        bob = self.repo.add_wishlist_item(WishlistEntryInput(user_id="bob", product_id=4))
        with self.assertRaisesRegex(ValueError, "already"):
            self.repo.add_wishlist_item(WishlistEntryInput(user_id="alice", product_id=4))
        selected = self.repo.add_wishlist_item(
            WishlistEntryInput(user_id="alice", product_id=4, offer_id=106)
        )
        self.assertFalse(self.repo.remove_wishlist_item(alice.wishlist_id, "bob"))
        reopened = SQLiteProcurementRepository(self.db_path)
        self.assertEqual(
            {entry.wishlist_id for entry in reopened.list_wishlist("alice")},
            {alice.wishlist_id, selected.wishlist_id},
        )
        self.assertEqual([entry.wishlist_id for entry in reopened.list_wishlist("bob")], [bob.wishlist_id])
        self.assertTrue(reopened.remove_wishlist_item(alice.wishlist_id, "alice"))
        self.assertFalse(reopened.remove_wishlist_item(alice.wishlist_id, "alice"))
        self.assertEqual(len(reopened.list_wishlist("bob")), 1)

    def test_wishlist_reads_current_numeric_prices_and_honors_stock_and_selected_offer(self) -> None:
        broad = self.repo.add_wishlist_item(WishlistEntryInput(product_id=4, currency="kzt"))
        selected = self.repo.add_wishlist_item(WishlistEntryInput(product_id=4, offer_id=106))
        self.assertEqual(broad.current_price, Decimal("24000"))
        self.assertEqual(selected.current_price, Decimal("24500"))
        self.update_offer(105, "9500.25")
        self.update_offer(106, "10000.50")
        rows = {entry.wishlist_id: entry for entry in self.repo.list_wishlist("demo-user")}
        self.assertEqual(rows[broad.wishlist_id].current_price, Decimal("9500.25"))
        self.assertEqual(rows[selected.wishlist_id].current_price, Decimal("10000.50"))
        self.update_offer(106, "1", stock=0)
        rows = {entry.wishlist_id: entry for entry in self.repo.list_wishlist("demo-user")}
        self.assertEqual(rows[broad.wishlist_id].current_price, Decimal("9500.25"))
        self.assertIsNone(rows[selected.wishlist_id].current_price)

    def test_invalid_product_offer_or_currency_does_not_create_wishlist_or_watch(self) -> None:
        for model, create in (
            (WishlistEntryInput, self.repo.add_wishlist_item),
            (PriceWatchInput, self.repo.create_price_watch),
        ):
            with self.subTest(model=model.__name__):
                with self.assertRaises(LookupError):
                    create(model(product_id=9999, target_price=20000))
                with self.assertRaisesRegex(ValueError, "belong"):
                    create(model(product_id=4, offer_id=101, target_price=20000))
                with self.assertRaisesRegex(ValueError, "currency"):
                    create(model(product_id=4, offer_id=105, currency="USD", target_price=20000))
        self.assertEqual(self.repo.list_wishlist("demo-user"), [])
        self.assertEqual(self.repo.list_price_watches("demo-user"), [])

    def test_price_drop_then_target_emits_once_and_persists_events(self) -> None:
        watch = self.repo.create_price_watch(
            PriceWatchInput(user_id="alice", product_id=4, offer_id=105, target_price="22000.25")
        )
        other = self.repo.create_price_watch(
            PriceWatchInput(user_id="bob", product_id=4, offer_id=105, target_price=23000)
        )
        self.assertEqual(self.repo.evaluate_price_watches("alice").alert_count, 0)
        self.update_offer(105, "23000.75")
        result = self.repo.evaluate_price_watches("alice")
        self.assertEqual((result.evaluated_count, result.alert_count), (1, 1))
        self.assertEqual(result.alerts[0].event_type, "PRICE_DROP")
        self.assertEqual(result.alerts[0].change_amount, Decimal("999.25"))
        self.assertEqual(self.repo.list_price_watches("bob")[0].last_observed_price, Decimal("24000"))
        self.assertEqual(self.repo.list_price_watch_events(other.watch_id, "bob"), [])
        self.assertEqual(self.repo.evaluate_price_watches("alice").alert_count, 0)
        self.update_offer(105, "23500")
        self.assertEqual(self.repo.evaluate_price_watches("alice").alert_count, 0)
        self.update_offer(105, "22000.25")
        target = self.repo.evaluate_price_watches("alice")
        self.assertEqual(target.alerts[0].event_type, "TARGET_REACHED")
        self.assertEqual(target.alerts[0].previous_price, Decimal("23500"))
        self.assertEqual(target.alerts[0].change_amount, Decimal("1499.75"))
        self.assertEqual(self.repo.list_price_watches("alice")[0].status, "TRIGGERED")
        self.assertEqual(self.repo.evaluate_price_watches("alice").evaluated_count, 0)
        reopened = SQLiteProcurementRepository(self.db_path)
        self.assertEqual(
            [event.event_type for event in reopened.list_price_watch_events(watch.watch_id, "alice")],
            ["PRICE_DROP", "TARGET_REACHED"],
        )
        with self.assertRaises(LookupError):
            reopened.list_price_watch_events(watch.watch_id, "bob")
        with self.assertRaises(LookupError):
            reopened.update_price_watch_status(watch.watch_id, "bob", PriceWatchStatusUpdate(status="PAUSED"))

    def test_paused_watch_skips_checks_until_owner_reactivates_it(self) -> None:
        watch = self.repo.create_price_watch(PriceWatchInput(product_id=4, offer_id=105, target_price=23000))
        self.repo.update_price_watch_status(watch.watch_id, "demo-user", PriceWatchStatusUpdate(status="PAUSED"))
        self.update_offer(105, "22000")
        result = self.repo.evaluate_price_watches("demo-user")
        self.assertEqual((result.evaluated_count, result.alert_count), (0, 0))
        self.assertEqual(self.repo.list_price_watches("demo-user")[0].last_observed_price, Decimal("24000"))
        self.repo.update_price_watch_status(watch.watch_id, "demo-user", PriceWatchStatusUpdate(status="ACTIVE"))
        self.assertEqual(self.repo.evaluate_price_watches("demo-user").alerts[0].event_type, "TARGET_REACHED")

    def test_out_of_stock_offer_cannot_start_or_trigger_price_watch(self) -> None:
        watch = self.repo.create_price_watch(PriceWatchInput(product_id=4, offer_id=105, target_price=23000))
        self.update_offer(105, "100", stock=0)
        with self.assertRaisesRegex(ValueError, "in-stock"):
            self.repo.create_price_watch(PriceWatchInput(product_id=4, offer_id=105, target_price=23000))
        self.assertEqual(self.repo.evaluate_price_watches("demo-user").alert_count, 0)
        unchanged = self.repo.list_price_watches("demo-user")[0]
        self.assertEqual(unchanged.status, "ACTIVE")
        self.assertEqual(unchanged.last_observed_price, Decimal("24000"))
        self.assertEqual(self.repo.list_price_watch_events(watch.watch_id, "demo-user"), [])
        self.update_offer(105, "100", stock=1)
        self.assertEqual(self.repo.evaluate_price_watches("demo-user").alerts[0].event_type, "TARGET_REACHED")

    def test_product_watch_uses_cheapest_available_offer_in_its_currency(self) -> None:
        watch = self.repo.create_price_watch(PriceWatchInput(product_id=4, target_price=22000))
        self.update_offer(106, "23000")
        result = self.repo.evaluate_price_watches("demo-user")
        self.assertEqual(result.alerts[0].current_price, Decimal("23000"))
        self.update_offer(107, "100")
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("UPDATE offers SET currency='USD' WHERE id=107")
        self.assertEqual(self.repo.evaluate_price_watches("demo-user").alert_count, 0)
        self.assertEqual(self.repo.list_price_watches("demo-user")[0].watch_id, watch.watch_id)

    def test_reminder_validates_timezone_and_exactly_one_product_reference(self) -> None:
        for payload in (
            {"product_id": 4, "remind_at": "2026-10-01T09:00:00"},
            {"remind_at": "2026-10-01T09:00:00+05:00"},
            {"product_query": "   ", "remind_at": "2026-10-01T09:00:00+05:00"},
            {"product_id": 4, "product_query": "SSD", "remind_at": "2026-10-01T09:00:00+05:00"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                PurchaseReminderInput(**payload)
        with self.assertRaises(LookupError):
            self.repo.create_purchase_reminder(
                PurchaseReminderInput(product_id=9999, remind_at="2026-10-01T09:00:00+05:00")
            )
        self.assertEqual(self.repo.list_purchase_reminders("demo-user"), [])
        fixed_now = datetime(2026, 10, 1, 4, tzinfo=timezone.utc)
        same_instant = datetime.fromisoformat("2026-10-01T09:00:00+05:00")
        self.assertEqual(PurchaseReminderService.status("OPEN", same_instant, fixed_now), "DUE")
        self.assertEqual(PurchaseReminderService.status("OPEN", same_instant + timedelta(seconds=1), fixed_now), "SCHEDULED")

    def test_due_reminders_normalize_timezone_and_terminal_status_is_immutable(self) -> None:
        now = datetime.now(timezone.utc)
        due_at = (now - timedelta(days=1)).astimezone(timezone(timedelta(hours=5)))
        due = self.repo.create_purchase_reminder(
            PurchaseReminderInput(user_id="alice", product_id=4, remind_at=due_at, note="initial")
        )
        later = self.repo.create_purchase_reminder(
            PurchaseReminderInput(user_id="alice", product_query="  Кофе  ", remind_at=now + timedelta(days=1))
        )
        self.assertEqual(due.remind_at.utcoffset(), timedelta(0))
        self.assertEqual(due.remind_at, due_at)
        self.assertEqual(due.status, "DUE")
        self.assertEqual(later.status, "SCHEDULED")
        self.assertEqual(later.product_query, "Кофе")
        self.assertEqual([item.reminder_id for item in self.repo.list_purchase_reminders("alice", due_only=True)], [due.reminder_id])
        self.assertEqual(self.repo.list_purchase_reminders("bob"), [])
        with self.assertRaises(LookupError):
            self.repo.update_purchase_reminder(due.reminder_id, "bob", PurchaseReminderUpdate(status="COMPLETED"))
        closed = self.repo.update_purchase_reminder(due.reminder_id, "alice", PurchaseReminderUpdate(status="COMPLETED"))
        self.assertEqual(closed.status, "COMPLETED")
        self.assertEqual(closed.note, "initial")
        self.assertIsNotNone(closed.closed_at)
        self.assertEqual(self.repo.list_purchase_reminders("alice", due_only=True), [])
        cancelled = self.repo.update_purchase_reminder(later.reminder_id, "alice", PurchaseReminderUpdate(status="CANCELLED", note="cancelled"))
        self.assertEqual(cancelled.status, "CANCELLED")
        self.assertEqual(cancelled.note, "cancelled")
        reopened = SQLiteProcurementRepository(self.db_path)
        for reminder in reopened.list_purchase_reminders("alice"):
            with self.subTest(status=reminder.status), self.assertRaisesRegex(ValueError, "closed"):
                reopened.update_purchase_reminder(reminder.reminder_id, "alice", PurchaseReminderUpdate(status="COMPLETED"))

    def test_v4_migration_preserves_existing_finance_and_catalog_records(self) -> None:
        tools = ProcurementTools(SQLiteCatalogAdapter(self.repo), persistence_repository=self.repo)
        plan = self.repo.save_plan(ManagerAgent(tools).plan_text("Нужно закупить 100 SSD минимум 1 TB до 25 000 ₸ за штуку"))
        for approval in self.repo.list_approvals("PENDING"):
            self.repo.decide_approval(approval.approval_id, ApprovalDecision(decision="approved", reviewer_id="finance", reviewer_role=approval.required_role))
        order = self.repo.create_purchase_order(plan.plan_id)
        for supplier_id in {item.supplier_id for item in order.items}:
            self.repo.update_delivery(order.order_id, DeliveryUpdate(supplier_id=supplier_id, status="ORDERED"))
        first_item = order.items[0]
        invoice = self.repo.create_invoice(order.order_id, InvoiceSubmission(
            supplier_id=first_item.supplier_id, invoice_number="KEEP-001", invoice_date="2026-09-23", currency="KZT",
            items=[InvoiceLineInput(order_item_id=first_item.id, quantity=first_item.quantity, unit_price=first_item.unit_price)],
            subtotal=first_item.quantity * first_item.unit_price,
            total_amount=first_item.quantity * first_item.unit_price,
        ))
        self.update_offer(105, "23500.50")
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            for table in ("price_watch_events", "price_watches", "wishlist_items", "purchase_reminders"):
                connection.execute(f"DROP TABLE {table}")
            connection.execute("PRAGMA user_version=4")
            existing_tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            before = {table: connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall() for table in existing_tables}
        migrated = SQLiteProcurementRepository(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
            after = {table: connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall() for table in existing_tables}
        self.assertEqual(before, after)
        self.assertEqual(migrated.get_invoice(invoice.invoice_id).invoice_number, "KEEP-001")
        self.assertEqual(migrated.get_purchase_order(order.order_id).plan_id, plan.plan_id)
        self.assertEqual(migrated.add_wishlist_item(WishlistEntryInput(product_id=4)).current_price, Decimal("23500.50"))
        self.assertEqual(migrated.list_price_watches("demo-user"), [])
        self.assertEqual(migrated.list_purchase_reminders("demo-user"), [])

    def test_newer_database_is_rejected_before_schema_changes(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("DROP TABLE wishlist_items")
            connection.execute("PRAGMA user_version=6")
            before = connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        with self.assertRaisesRegex(RuntimeError, "newer"):
            SQLiteProcurementRepository(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 6)
            after = connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
