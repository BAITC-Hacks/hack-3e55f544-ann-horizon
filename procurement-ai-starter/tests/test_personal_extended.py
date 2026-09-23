"""Behavioral coverage for additive local B2C workflows."""

import sqlite3
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api_personal_extended import create_personal_router
from backend.integrations.catalog import SQLiteCatalogAdapter
from backend.models.personal_extended import (
    BundleItemInput, BundleRequest, CompatibilityRequest, ComponentSpecs, HostSpecs,
    PersonalPreferencesInput, PersonalPurchaseInput, ReturnDraftInput,
)
from backend.repositories.personal_extended import PersonalExtendedRepository
from backend.repositories.procurement import SQLiteProcurementRepository
from backend.services.catalog import CatalogService
from backend.services.personal_extended import PersonalExtendedService


class ExtendedPersonalTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).resolve().parents[1] / "data" / f"personal-extended-test-{uuid.uuid4().hex}.db"
        self.addCleanup(self.path.unlink, missing_ok=True)
        self.procurement = SQLiteProcurementRepository(self.path)
        self.initial_product_count = len(self.procurement.list_products())
        self.repo = PersonalExtendedRepository(self.path)
        self.service = PersonalExtendedService(self.repo, CatalogService(SQLiteCatalogAdapter(self.procurement)))

    def purchase(self, **kwargs):
        payload = dict(user_id="alice", product_id=4, offer_id=105, quantity=2, unit_price="24000.25",
                       purchased_at=datetime.now(timezone.utc) - timedelta(days=30), repeat_after_days=20)
        payload.update(kwargs)
        return self.service.add_purchase(PersonalPurchaseInput(**payload))

    def test_preferences_purchase_memory_and_schema_survive_reopen(self):
        saved = self.service.save_preferences("alice", PersonalPreferencesInput(
            preferred_brands=["Aster"], preferred_supplier_ids=[1], budget_min=10000, budget_max=500000,
        ))
        purchase = self.purchase()
        reopened = PersonalExtendedRepository(self.path)
        self.assertEqual(reopened.get_preferences("alice"), saved)
        self.assertEqual(reopened.get_purchase(purchase.purchase_id, "alice"), purchase)
        self.assertIsNone(reopened.get_purchase(purchase.purchase_id, "bob"))
        self.assertEqual(purchase.total_price, Decimal("48000.50"))
        self.assertEqual(self.service.purchases("bob"), [])
        self.assertEqual(self.service.preferences("bob").preferred_brands, [])
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0], self.initial_product_count)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_log WHERE action LIKE 'personal_%'").fetchone()[0], 2)

    def test_invalid_purchase_or_preference_is_not_saved(self):
        with self.assertRaises(LookupError):
            self.purchase(product_id=99999, offer_id=None)
        with self.assertRaisesRegex(ValueError, "belong"):
            self.purchase(offer_id=101)
        with self.assertRaisesRegex(ValueError, "currency"):
            self.purchase(currency="USD")
        with self.assertRaisesRegex(ValueError, "future"):
            self.purchase(purchased_at=datetime.now(timezone.utc) + timedelta(days=2))
        with self.assertRaises(ValidationError):
            PersonalPurchaseInput(product_id=4, unit_price=1, purchased_at=datetime(2026, 1, 1))
        with self.assertRaises(LookupError):
            self.service.save_preferences("alice", PersonalPreferencesInput(preferred_supplier_ids=[9999]))
        with self.assertRaises(ValidationError):
            PersonalPreferencesInput(budget_min=20000, budget_max=10000)
        self.assertEqual(self.service.purchases("alice"), [])

    def test_reorder_uses_latest_purchase_and_explicit_cycle_with_current_offer(self):
        older = self.purchase()
        due = self.service.reorders("alice", due_only=True)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].source_purchase_id, older.purchase_id)
        self.assertEqual(due[0].current_offer_id, 105)
        self.assertEqual(due[0].estimated_subtotal, Decimal("48000"))
        newer = self.purchase(purchased_at=datetime.now(timezone.utc) - timedelta(days=1))
        self.assertEqual(self.service.reorders("alice", due_only=True), [])
        self.assertEqual(self.service.reorders("alice")[0].source_purchase_id, newer.purchase_id)
        self.assertEqual(self.service.reorders("alice")[0].status, "SCHEDULED")
        self.assertEqual(self.service.reorders("bob"), [])
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE offers SET quantity_available=0 WHERE product_id=4")
        self.assertIsNone(self.service.reorders("alice")[0].current_unit_price)

    def test_compatibility_distinguishes_known_failures_from_missing_specs(self):
        unknown = self.service.compatibility(CompatibilityRequest(product_id=4, host_product_id=1))
        self.assertEqual(unknown.verdict, "UNKNOWN")
        match = self.service.compatibility(CompatibilityRequest(
            product_id=4, host_product_id=1, host_specs=HostSpecs(accepted_interfaces=["nvme"]),
            required_checks=["interface"],
        ))
        self.assertEqual(match.verdict, "COMPATIBLE")
        mismatch = self.service.compatibility(CompatibilityRequest(
            product_id=4, host_specs=HostSpecs(accepted_interfaces=["SATA"]),
        ))
        self.assertEqual(mismatch.verdict, "INCOMPATIBLE")
        self.assertIn("UNKNOWN", [finding.status for finding in mismatch.findings])
        with self.assertRaisesRegex(ValueError, "contradicts"):
            self.service.compatibility(CompatibilityRequest(product_id=4, component_specs=ComponentSpecs(interface="SATA")))
        power = self.service.compatibility(CompatibilityRequest(
            product_id=4, required_checks=["power", "dimensions"],
            component_specs=ComponentSpecs(required_power_w=10, length_mm=100),
            host_specs=HostSpecs(available_power_w=9, maximum_length_mm=100),
        ))
        self.assertEqual(power.verdict, "INCOMPATIBLE")
        self.assertEqual([finding.status for finding in power.findings], ["FAIL", "PASS"])

    def test_bundle_uses_budget_and_does_not_invent_compatibility(self):
        request = BundleRequest(items=[BundleItemInput(product_id=1), BundleItemInput(product_id=4)],
                                budget_total=500000, host_product_id=1)
        result = self.service.bundle(request)
        self.assertEqual(result.merchandise_subtotal, Decimal("484000"))
        self.assertEqual(result.outcome, "REVIEW_REQUIRED")
        self.assertEqual(result.compatibility_verdict, "UNKNOWN")
        self.assertTrue(result.within_budget)
        self.assertEqual(self.service.bundle(request), result)
        too_expensive = self.service.bundle(request.model_copy(update={"budget_total": Decimal("480000")}))
        self.assertEqual(too_expensive.outcome, "BLOCKED")
        self.assertFalse(too_expensive.within_budget)
        known = self.service.bundle(request.model_copy(update={
            "host_specs": HostSpecs(accepted_interfaces=["NVMe"]), "required_checks": ["interface"],
        }))
        self.assertEqual(known.compatibility_verdict, "COMPATIBLE")
        self.assertEqual(known.outcome, "READY_FOR_REVIEW")

    def test_bundle_respects_shared_stock_minimum_quantity_and_specs(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE offers SET quantity_available=0 WHERE id IN(106,107)")
            connection.execute("UPDATE offers SET quantity_available=2 WHERE id=105")
        request = BundleRequest(items=[BundleItemInput(product_id=4, quantity=2), BundleItemInput(product_id=4)], budget_total=100000)
        self.assertEqual(self.service.bundle(request).outcome, "BLOCKED")
        empty = self.service.bundle(BundleRequest(items=[BundleItemInput(product_query="unknown camera")], budget_total=100000))
        self.assertEqual(empty.lines, [])
        mismatch = self.service.bundle(BundleRequest(items=[BundleItemInput(product_id=4, minimum_capacity_gb=2048)], budget_total=100000))
        self.assertEqual(mismatch.outcome, "BLOCKED")
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE offers SET minimum_order_quantity=2 WHERE id=105")
        insufficient = self.service.bundle(BundleRequest(items=[BundleItemInput(product_id=4)], budget_total=100000))
        self.assertEqual(insufficient.outcome, "BLOCKED")

    def test_bundle_combines_component_power_and_reports_confirmed_incompatibility(self):
        request = BundleRequest(items=[BundleItemInput(product_id=4, quantity=2,
                                                       component_specs=ComponentSpecs(required_power_w=10))],
                                host_product_id=1, host_specs=HostSpecs(available_power_w=15),
                                required_checks=["power"], budget_total=100000)
        result = self.service.bundle(request)
        self.assertTrue(result.within_budget)
        self.assertEqual(result.compatibility_verdict, "INCOMPATIBLE")
        self.assertEqual(result.outcome, "BLOCKED")
        mismatch = self.service.bundle(request.model_copy(update={
            "required_checks": ["interface"], "host_specs": HostSpecs(accepted_interfaces=["SATA"]),
        }))
        self.assertEqual(mismatch.compatibility_verdict, "INCOMPATIBLE")
        self.assertEqual(mismatch.lines, [])

    def test_purchase_offsets_are_preserved_and_history_sorts_by_actual_time(self):
        # Both purchases are safely historical, with SQL text order opposite to actual time.
        first = self.purchase(purchased_at=datetime.fromisoformat("2025-01-02T00:30:00+05:00"))
        later = self.purchase(purchased_at=datetime.fromisoformat("2025-01-01T21:00:00+00:00"))
        self.assertEqual(self.service.purchases("alice")[0].purchase_id, later.purchase_id)
        reread = self.repo.get_purchase(first.purchase_id, "alice")
        self.assertEqual(reread.purchased_at.date().isoformat(), "2025-01-02")
        with self.assertRaisesRegex(ValueError, "precede"):
            self.service.create_return(ReturnDraftInput(user_id="alice", purchase_id=first.purchase_id,
                                                       reason="Reason", return_deadline="2025-01-01", policy_source="Receipt"))

    def test_returns_use_owned_purchase_and_do_not_invent_policy_or_submit(self):
        purchase = self.purchase()
        request = ReturnDraftInput(user_id="alice", purchase_id=purchase.purchase_id, quantity=1,
                                   reason="Не подошло", documents=["Чек"])
        record = self.service.create_return(request)
        self.assertEqual(record.status, "DRAFT")
        self.assertEqual(record.deadline_status, "UNKNOWN")
        self.assertFalse(record.externally_submitted)
        self.assertEqual(self.service.returns("bob"), [])
        with self.assertRaises(LookupError):
            self.service.create_return(request.model_copy(update={"user_id": "bob"}))
        with self.assertRaisesRegex(ValueError, "remaining"):
            self.service.create_return(request.model_copy(update={"quantity": 2}))
        self.assertEqual(self.service.cancel_return(record.return_id, "alice").status, "CANCELLED")
        again = self.service.create_return(request.model_copy(update={"quantity": 2}))
        self.assertEqual(again.quantity, 2)
        with self.assertRaises(LookupError):
            self.service.cancel_return(again.return_id, "bob")

    def test_return_deadline_requires_source_and_never_asserts_legal_eligibility(self):
        purchase = self.purchase()
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        with self.assertRaises(ValidationError):
            ReturnDraftInput(purchase_id=purchase.purchase_id, reason="Reason", return_deadline=tomorrow)
        record = self.service.create_return(ReturnDraftInput(
            user_id="alice", purchase_id=purchase.purchase_id, reason="Reason", return_deadline=tomorrow,
            policy_source="Условия из чека, введены пользователем",
        ))
        self.assertEqual(record.deadline_status, "WITHIN_PROVIDED_DEADLINE")
        self.assertIn("не подтверждены", record.explanation)

    def test_router_exposes_typed_end_to_end_personal_flow(self):
        app = FastAPI()
        app.include_router(create_personal_router(lambda: self.procurement))
        with TestClient(app) as client:
            pref = client.put("/api/personal/preferences?user_id=alice", json={"preferred_brands": ["Aster"]})
            self.assertEqual(pref.status_code, 200, pref.text)
            payload = PersonalPurchaseInput(user_id="alice", product_id=4, unit_price=24000,
                                            purchased_at=datetime.now(timezone.utc) - timedelta(days=30), repeat_after_days=20)
            purchase = client.post("/api/personal/purchases", json=payload.model_dump(mode="json"))
            self.assertEqual(purchase.status_code, 201, purchase.text)
            self.assertEqual(len(client.get("/api/personal/reorder-recommendations?user_id=alice&due_only=true").json()), 1)
            self.assertEqual(client.get("/api/personal/purchases?user_id=bob").json(), [])
            unknown = client.post("/api/personal/compatibility", json={"product_id": 4})
            self.assertEqual(unknown.status_code, 200, unknown.text)
            self.assertEqual(unknown.json()["verdict"], "UNKNOWN")
            draft = client.post("/api/personal/returns", json={"user_id": "alice", "purchase_id": purchase.json()["purchase_id"], "reason": "Reason"})
            self.assertEqual(draft.status_code, 201, draft.text)
            returned = client.post(f"/api/personal/returns/{draft.json()['return_id']}/cancel?user_id=alice")
            self.assertEqual(returned.status_code, 200, returned.text)
            self.assertEqual(returned.json()["status"], "CANCELLED")
            invalid = client.post("/api/personal/compatibility", json={"product_id": 99999})
            self.assertEqual(invalid.status_code, 404)
            bundle = client.post("/api/personal/bundles", json={"items": [{"product_id": 4}], "budget_total": 30000})
            self.assertEqual(bundle.status_code, 200, bundle.text)
            self.assertEqual(bundle.json()["outcome"], "READY_FOR_REVIEW")
            self.assertEqual(client.put("/api/personal/preferences?user_id=alice", json={"preferred_brands": [" "]}).status_code, 422)
            self.assertEqual(client.get("/api/personal/preferences?user_id=%20%20").status_code, 422)
            self.assertEqual(client.get("/api/personal/reorder-recommendations?due_only=not-a-bool").status_code, 422)
            injection_owner = "alice' OR 1=1 --"
            self.assertEqual(client.get("/api/personal/purchases", params={"user_id": injection_owner}).json(), [])


if __name__ == "__main__":
    unittest.main()
