import unittest
import asyncio
import os
import json
import sqlite3
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.agents.intake import IntakeAgent
from backend.agents.manager import ManagerAgent
from backend.api import (
    ChatRequest,
    chat,
    create_local_order_draft,
    decide_approval,
    forecast_product,
    get_manager,
    get_repository,
    health,
    list_products,
    record_delivery_event,
    replan_order,
    run_reorder_analysis,
)
from backend.integrations.catalog import SQLiteCatalogAdapter
from backend.integrations.llm_intake import OpenAIIntakeAgent
from backend.models.purchase import (
    ApprovalDecision, DeliveryUpdate, InventoryItem, InvoiceLineInput, InvoiceSubmission,
    PurchaseRequest, ReceivingLineInput, ReceivingRequest, ReplanRequest, OrderDraftUpdate, UserContext,
)
from backend.repositories.procurement import SQLiteProcurementRepository
from backend.services.forecast import DemandForecastService
from backend.services.inventory import InventoryService
from backend.services.reorder import ReorderService
from backend.services.pricing import PricingService
from backend.tools.procurement import ProcurementTools


class IntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intake = IntakeAgent()

    def test_parses_business_ssd_request(self) -> None:
        request = self.intake.parse(
            "Нужно закупить 300 SSD минимум 1 TB по цене до 25 000 ₸ за штуку, доставка максимум 7 дней."
        )

        self.assertEqual(request.product_query, "ssd")
        self.assertEqual(request.quantity, 300)
        self.assertEqual(request.required_specs["ssd_gb"], 1024)
        self.assertEqual(request.budget_per_unit, Decimal("25000"))
        self.assertIsNone(request.budget_total)
        self.assertEqual(request.currency, "KZT")
        self.assertEqual(request.max_delivery_days, 7)

    def test_parses_laptop_specs_and_total_budget(self) -> None:
        request = self.intake.parse(
            "Нужно закупить 100 ноутбуков. Бюджет 50 000 000 ₸. RAM минимум 32 GB, SSD минимум 1 TB, срок поставки максимум 10 дней."
        )

        self.assertEqual(request.product_query, "laptop")
        self.assertEqual(request.quantity, 100)
        self.assertEqual(request.required_specs, {"ram_gb": 32, "ssd_gb": 1024})
        self.assertEqual(request.budget_total, Decimal("50000000"))
        self.assertEqual(request.max_delivery_days, 10)

    def test_personal_request_defaults_to_one_unit_and_unit_budget(self) -> None:
        context = UserContext(user_type="personal", organization_id=None, currency="KZT")
        request = self.intake.parse("Мне нужен ноутбук до 500 000 ₸ для работы", context)

        self.assertEqual(request.quantity, 1)
        self.assertEqual(request.budget_per_unit, Decimal("500000"))
        self.assertEqual(request.user_context.user_type, "personal")

    def test_parses_units_written_with_russian_abbreviation(self) -> None:
        request = self.intake.parse("Нужно 100 x ноутбуков с RAM не меньше 16 ГБ и сроком максимум за 9 дней")
        self.assertEqual(request.quantity, 100)
        self.assertEqual(request.required_specs["ram_gb"], 16)
        self.assertEqual(request.max_delivery_days, 9)


class PricingTests(unittest.TestCase):
    def test_subtotal_uses_decimal_arithmetic(self) -> None:
        self.assertEqual(PricingService.line_subtotal(Decimal("24500.25"), 3), Decimal("73500.75"))


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ManagerAgent()

    def test_ssd_request_creates_valid_multi_supplier_review_plan(self) -> None:
        plan = self.manager.plan_text(
            "Нужно закупить 300 SSD минимум 1 TB по цене до 25 000 ₸ за штуку, доставка максимум 7 дней.",
            UserContext(user_type="business", organization_id="demo-org"),
        )

        self.assertEqual(plan.status, "READY_FOR_REVIEW")
        self.assertEqual(plan.quantity_requested, 300)
        self.assertEqual(plan.quantity_planned, 300)
        self.assertEqual(plan.merchandise_subtotal, Decimal("7340000"))
        self.assertEqual(len(plan.lines), 3)
        self.assertEqual(sum(line.quantity for line in plan.lines), 300)
        self.assertTrue(all(line.unit_price <= Decimal("25000") for line in plan.lines))
        self.assertTrue(all(line.delivery_days <= 7 for line in plan.lines))
        self.assertFalse(plan.external_order_created)
        self.assertTrue(plan.requires_human_review)
        self.assertTrue(any(item.code == "shipping_tax_unknown" for item in plan.findings))
        self.assertTrue(any(item.data_status == "insufficient_data" for item in plan.supplier_assessments))
        self.assertEqual(plan.approval_status, "PENDING")
        self.assertEqual(plan.approval_role, "finance")
        self.assertTrue(plan.approval_required)
        self.assertEqual(plan.compliance_status, "COMPLIANT")
        self.assertTrue(any(item.risk_type == "price" for item in plan.risks))
        self.assertTrue(all(item.source_label == "DEMO DATA" for item in plan.price_summary.history_comparisons))
        self.assertFalse(plan.external_order_created)

    def test_laptop_request_obeys_specs_delivery_and_total_budget(self) -> None:
        request = PurchaseRequest(
            product_query="laptop",
            quantity=100,
            budget_total=Decimal("50000000"),
            max_delivery_days=10,
            required_specs={"ram_gb": 32, "ssd_gb": 1024},
            user_context=UserContext(user_type="business"),
        )
        plan = self.manager.plan(request)

        self.assertEqual(plan.status, "READY_FOR_REVIEW")
        self.assertEqual(plan.quantity_planned, 100)
        self.assertLessEqual(plan.merchandise_subtotal, Decimal("50000000"))
        self.assertTrue(all(line.delivery_days <= 10 for line in plan.lines))
        self.assertTrue(all(line.product_id in {1, 3} for line in plan.lines))

    def test_over_budget_request_is_blocked(self) -> None:
        plan = self.manager.plan(
            PurchaseRequest(
                product_query="ssd",
                quantity=50,
                budget_per_unit=Decimal("20000"),
                currency="KZT",
                max_delivery_days=7,
                required_specs={"ssd_gb": 1024},
            )
        )

        self.assertEqual(plan.status, "BLOCKED")
        self.assertEqual(plan.quantity_planned, 0)
        self.assertTrue(any(item.code == "quantity_shortage" for item in plan.findings))

    def test_insufficient_inventory_never_reports_a_complete_plan(self) -> None:
        plan = self.manager.plan(
            PurchaseRequest(
                product_query="ssd",
                quantity=500,
                budget_per_unit=Decimal("25000"),
                currency="KZT",
                max_delivery_days=7,
                required_specs={"ssd_gb": 1024},
            )
        )

        self.assertEqual(plan.status, "BLOCKED")
        self.assertLess(plan.quantity_planned, plan.quantity_requested)

    def test_validator_recomputes_line_subtotal(self) -> None:
        plan = self.manager.plan_text(
            "Нужно закупить 300 SSD минимум 1 TB по цене до 25 000 ₸ за штуку, доставка максимум 7 дней."
        )
        forged_line = plan.lines[0].model_copy(update={"merchandise_subtotal": Decimal("1")})
        forged_plan = plan.model_copy(
            update={
                "lines": [forged_line, *plan.lines[1:]],
                "merchandise_subtotal": Decimal("1") + sum(
                    (line.merchandise_subtotal for line in plan.lines[1:]), Decimal("0")
                ),
                "total_cost": Decimal("1") + sum(
                    (line.merchandise_subtotal for line in plan.lines[1:]), Decimal("0")
                ),
            }
        )

        findings = self.manager.validator.validate(plan.request, forged_plan)
        self.assertIn("subtotal_mismatch", {item.code for item in findings})


class OptionalLLMTests(unittest.TestCase):
    def test_llm_intake_requires_explicit_api_key(self) -> None:
        environment = dict(os.environ)
        environment.pop("OPENAI_API_KEY", None)
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY is required"):
                asyncio.run(OpenAIIntakeAgent().parse("Buy an SSD", UserContext()))

    def test_sdk_plan_review_requires_explicit_api_key(self) -> None:
        from backend.integrations.agents_sdk import review_plan_with_agents_sdk

        environment = dict(os.environ)
        environment.pop("OPENAI_API_KEY", None)
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY is required"):
                asyncio.run(review_plan_with_agents_sdk(ManagerAgent().plan_text("Buy one SSD")))

    def test_sdk_bundle_constructs_manager_and_specialists_in_project_code(self) -> None:
        try:
            from agents import Agent
        except ImportError:
            self.skipTest("Optional Agents SDK is not installed")

        from backend.integrations.agents_sdk import build_procurement_agent_set

        agent_set = build_procurement_agent_set()
        self.assertIsInstance(agent_set.manager, Agent)
        self.assertIsInstance(agent_set.intake, Agent)
        self.assertGreaterEqual(len(agent_set.specialists), 10)
        self.assertEqual(agent_set.manager.name, "Procurement Manager Agent")

    def test_sdk_review_summary_does_not_replace_deterministic_plan_values(self) -> None:
        manager = ManagerAgent(use_agents_sdk_review=True)
        with patch(
            "backend.integrations.agents_sdk.review_plan_with_agents_sdk",
            new=AsyncMock(return_value="Проверенный текстовый итог."),
        ):
            plan = asyncio.run(
                manager.plan_text_async(
                    "Нужно купить 300 SSD минимум 1 TB до 25 000 ₸ за штуку, срок максимум 7 дней"
                )
            )
        self.assertEqual(plan.ai_summary, "Проверенный текстовый итог.")
        self.assertEqual(plan.quantity_planned, 300)
        self.assertEqual(plan.merchandise_subtotal, Decimal("7340000"))


class ApiTests(unittest.TestCase):
    def test_replan_endpoint_targets_only_delayed_supplier_quantity(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        db_path = project_root / "data" / f"api-replan-test-{uuid.uuid4().hex}.db"
        environment = dict(os.environ)
        environment["PROCUREMENT_DB_PATH"] = str(db_path)
        with patch.dict(os.environ, environment, clear=True):
            get_manager.cache_clear()
            get_repository.cache_clear()
            try:
                manager = get_manager()
                plan = manager.plan_text(
                    "Нужно закупить 300 SSD минимум 1 TB по цене до 25 000 ₸ за штуку, доставка максимум 7 дней."
                )
                saved = manager.tools.save_plan(plan)
                approval = manager.tools.list_approvals("PENDING")[0]
                decide_approval(
                    approval.approval_id,
                    ApprovalDecision(decision="approved", reviewer_id="demo-finance", reviewer_role="finance"),
                )
                order = create_local_order_draft(saved.plan_id, OrderDraftUpdate())
                supplier_ids = sorted({item.supplier_id for item in order.items})
                for supplier_id in supplier_ids:
                    record_delivery_event(order.order_id, DeliveryUpdate(supplier_id=supplier_id, status="ORDERED"))
                delayed_supplier = supplier_ids[0]
                record_delivery_event(
                    order.order_id,
                    DeliveryUpdate(supplier_id=delayed_supplier, status="DELAYED", note="Manual delay"),
                )
                result = replan_order(order.order_id, ReplanRequest())
                expected_quantity = sum(item.quantity for item in order.items if item.supplier_id == delayed_supplier)
                self.assertEqual(result.excluded_supplier_ids, [delayed_supplier])
                self.assertEqual(result.replaced_quantity, expected_quantity)
                self.assertEqual(result.replacement_plan.request.quantity, expected_quantity)
                self.assertTrue(all(line.supplier_id != delayed_supplier for line in result.replacement_plan.lines))
            finally:
                get_manager.cache_clear()
                get_repository.cache_clear()
                for suffix in ("", "-wal", "-shm"):
                    Path(f"{db_path}{suffix}").unlink(missing_ok=True)

    def test_local_api_contract_runs_without_llm(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        db_path = project_root / "data" / f"api-test-{uuid.uuid4().hex}.db"
        environment = dict(os.environ)
        environment["PROCUREMENT_LLM_INTAKE"] = "0"
        environment["PROCUREMENT_DB_PATH"] = str(db_path)
        with patch.dict(os.environ, environment, clear=True):
            get_manager.cache_clear()
            get_repository.cache_clear()
            try:
                self.assertEqual(health()["mode"], "local-demo")
                self.assertEqual(len(list_products()), 10)
                plan = asyncio.run(
                    chat(
                        ChatRequest(
                            message="Нужно закупить 300 SSD минимум 1 TB до 25 000 ₸ за штуку, срок до 7 дней",
                            user_context=UserContext(user_type="business"),
                        )
                    )
                )
                self.assertEqual(plan.status, "READY_FOR_REVIEW")
                self.assertEqual(plan.quantity_planned, 300)
                self.assertEqual(plan.total_cost, Decimal("7340000"))
                self.assertTrue(plan.plan_id)
                self.assertEqual(len(get_repository().list_plans()), 1)
                pending = get_repository().list_approvals("PENDING")
                self.assertEqual(len(pending), 1)
                approved = decide_approval(
                    pending[0].approval_id,
                    ApprovalDecision(
                        decision="approved", reviewer_id="demo-finance", reviewer_role="finance"
                    ),
                )
                self.assertEqual(approved.status, "APPROVED")
                self.assertEqual(get_repository().list_plans()[0].approval_status, "APPROVED")
                forecast = forecast_product(4)
                self.assertEqual(forecast.average_monthly_demand, Decimal("34.00"))
                reorder_rows = run_reorder_analysis()
                ssd_workflow = next(item for item in reorder_rows if item.recommendation.product_id == 4)
                ssd = ssd_workflow.recommendation
                self.assertEqual(ssd.available, 32)
                self.assertEqual(ssd.expected_lead_time_demand, 4)
                self.assertEqual(ssd.recommended_quantity, 22)
                self.assertEqual(ssd_workflow.purchase_plan.quantity_planned, 22)
                self.assertEqual(ssd_workflow.purchase_plan.status, "READY_FOR_REVIEW")
                self.assertTrue(ssd_workflow.purchase_plan.plan_id)
                self.assertEqual(
                    next(item for item in get_repository().list_inventory() if item.product_id == 4).available,
                    32,
                )
                self.assertEqual(get_repository().list_audit_events()[0].action, "reorder_recommendation_created")
                self.assertEqual(len(get_repository().list_plans()), 3)
            finally:
                get_manager.cache_clear()
                get_repository.cache_clear()
                db_path.unlink(missing_ok=True)


class DatabaseTests(unittest.TestCase):
    def test_schema_v1_and_v2_purchase_orders_migrate_to_v5(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        for starting_version in (1, 2):
            with self.subTest(starting_version=starting_version):
                db_path = project_root / "data" / f"migration-v{starting_version}-test-{uuid.uuid4().hex}.db"
                try:
                    connection = sqlite3.connect(db_path)
                    connection.execute(
                        """CREATE TABLE purchase_orders (
                        id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES procurement_plans(id),
                        status TEXT NOT NULL, external_order_created INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL)"""
                    )
                    connection.execute(f"PRAGMA user_version={starting_version}")
                    connection.close()
                    SQLiteProcurementRepository(db_path)
                    connection = sqlite3.connect(db_path)
                    version = connection.execute("PRAGMA user_version").fetchone()[0]
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(purchase_orders)")}
                    delivery_table = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='delivery_events'"
                    ).fetchone()
                    receiving_table = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='receiving_records'"
                    ).fetchone()
                    invoice_table = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='invoices'"
                    ).fetchone()
                    invoice_lines_table = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='invoice_lines'"
                    ).fetchone()
                    price_watch_table = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='price_watches'"
                    ).fetchone()
                    reminder_table = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='purchase_reminders'"
                    ).fetchone()
                    connection.close()
                    self.assertEqual(version, 5)
                    self.assertTrue({"buyer_note", "updated_at"}.issubset(columns))
                    self.assertIsNotNone(delivery_table)
                    self.assertIsNotNone(receiving_table)
                    self.assertIsNotNone(invoice_table)
                    self.assertIsNotNone(invoice_lines_table)
                    self.assertIsNotNone(price_watch_table)
                    self.assertIsNotNone(reminder_table)
                finally:
                    for suffix in ("", "-wal", "-shm"):
                        Path(f"{db_path}{suffix}").unlink(missing_ok=True)

    def test_invoice_three_way_reconciliation_and_finance_summary(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        db_path = project_root / "data" / f"invoice-test-{uuid.uuid4().hex}.db"
        try:
            repo = SQLiteProcurementRepository(db_path)
            tools = ProcurementTools(SQLiteCatalogAdapter(repo), persistence_repository=repo)
            manager = ManagerAgent(tools)
            plan = manager.plan_text(
                "Нужно закупить 300 SSD минимум 1 TB по цене до 25 000 ₸ за штуку, доставка максимум 7 дней."
            )
            saved = repo.save_plan(plan)
            approval = repo.list_approvals("PENDING")[0]
            repo.decide_approval(
                approval.approval_id,
                ApprovalDecision(decision="approved", reviewer_id="demo-finance", reviewer_role="finance"),
            )
            order = repo.create_purchase_order(saved.plan_id)
            supplier_ids = sorted({item.supplier_id for item in order.items})
            for supplier_id in supplier_ids:
                repo.update_delivery(order.order_id, DeliveryUpdate(supplier_id=supplier_id, status="ORDERED"))
                repo.update_delivery(order.order_id, DeliveryUpdate(supplier_id=supplier_id, status="DELIVERED"))
            first_item = order.items[0]
            first_supplier_items = [item for item in order.items if item.supplier_id == first_item.supplier_id]
            first_submission_lines = [
                InvoiceLineInput(order_item_id=item.id, quantity=item.quantity, unit_price=item.unit_price)
                for item in first_supplier_items
            ]
            subtotal = sum((item.quantity * item.unit_price for item in first_supplier_items), Decimal("0"))
            pending_invoice = repo.create_invoice(
                order.order_id,
                InvoiceSubmission(
                    supplier_id=first_item.supplier_id, invoice_number=" INV-2026-001 ",
                    invoice_date="2026-09-23", currency="kzt", subtotal=subtotal,
                    tax_amount=Decimal("500"), shipping_amount=Decimal("100"),
                    total_amount=subtotal + Decimal("600"), items=first_submission_lines,
                ),
            )
            self.assertEqual(pending_invoice.status, "PENDING_RECEIVING")
            self.assertEqual(pending_invoice.payment_status, "NOT_PAID")
            self.assertTrue(any(item.code == "invoice_quantity_exceeds_received" for item in pending_invoice.findings))
            with self.assertRaisesRegex(ValueError, "already exists"):
                repo.create_invoice(
                    order.order_id,
                    InvoiceSubmission(
                        supplier_id=first_item.supplier_id, invoice_number="inv-2026-001",
                        invoice_date="2026-09-23", subtotal=subtotal, total_amount=subtotal,
                        items=first_submission_lines,
                    ),
                )

            repo.receive_order(
                order.order_id,
                ReceivingRequest(items=[ReceivingLineInput(
                    order_item_id=item.id, quantity_received=item.quantity, damaged_quantity=0
                ) for item in first_supplier_items]),
            )
            matched_invoice = repo.review_invoice(pending_invoice.invoice_id)
            self.assertEqual(matched_invoice.status, "MATCHED")
            self.assertTrue(any(item.code == "invoice_three_way_match" for item in matched_invoice.findings))

            other_item = next(item for item in order.items if item.supplier_id != first_item.supplier_id)
            other_supplier_lines = [InvoiceLineInput(
                order_item_id=other_item.id, quantity=other_item.quantity,
                unit_price=other_item.unit_price + Decimal("1"),
            )]
            wrong_subtotal = other_item.quantity * (other_item.unit_price + Decimal("1"))
            variance_invoice = repo.create_invoice(
                order.order_id,
                InvoiceSubmission(
                    supplier_id=other_item.supplier_id, invoice_number="INV-2026-002",
                    invoice_date="2026-09-23", subtotal=wrong_subtotal, total_amount=wrong_subtotal,
                    items=other_supplier_lines,
                ),
            )
            self.assertEqual(variance_invoice.status, "VARIANCE")
            self.assertTrue(any(item.code == "invoice_unit_price_mismatch" for item in variance_invoice.findings))
            self.assertEqual(len(repo.list_invoices(order.order_id)), 2)
            self.assertIsNotNone(repo.get_invoice(matched_invoice.invoice_id))

            summary = repo.procurement_finance_summary()
            self.assertEqual(summary.order_count, 1)
            self.assertEqual(summary.invoice_count, 2)
            self.assertEqual(summary.invoice_status_counts, {"MATCHED": 1, "VARIANCE": 1})
            kzt = next(item for item in summary.currency_totals if item.currency == "KZT")
            self.assertEqual(kzt.ordered_subtotal, Decimal("7340000"))
            self.assertEqual(kzt.matched_invoice_total, subtotal + Decimal("600"))
            self.assertEqual(kzt.variance_invoice_total, wrong_subtotal)
            self.assertEqual(kzt.pending_invoice_total, Decimal("0"))
            self.assertEqual(summary.received_unit_count, sum(item.quantity for item in first_supplier_items))
            actions = [item.action for item in repo.list_audit_events(20)]
            self.assertIn("purchase_invoice_recorded", actions)
            self.assertIn("purchase_invoice_reconciled", actions)
        finally:
            for suffix in ("", "-wal", "-shm"):
                Path(f"{db_path}{suffix}").unlink(missing_ok=True)

    def test_sqlite_seeds_linked_catalog_and_persists_audited_plan(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        db_path = project_root / "data" / f"repository-test-{uuid.uuid4().hex}.db"
        try:
            repo = SQLiteProcurementRepository(db_path)
            self.assertEqual(len(repo.list_products()), 10)
            self.assertEqual(len(repo.list_suppliers()), 5)
            self.assertEqual(len(repo.list_offers()), 21)
            ssd_stock = next(item for item in repo.list_inventory() if item.product_id == 4)
            self.assertEqual(ssd_stock.available, 32)

            tools = ProcurementTools(SQLiteCatalogAdapter(repo))
            plan = ManagerAgent(tools).plan_text(
                "Нужно закупить 300 SSD минимум 1 TB по цене до 25 000 ₸ за штуку, доставка максимум 7 дней."
            )
            saved = repo.save_plan(plan)

            self.assertEqual(saved.plan_id, repo.list_plans()[0].plan_id)
            self.assertEqual(repo.list_plans()[0].status, "READY_FOR_REVIEW")
            self.assertEqual(repo.list_audit_events()[0].action, "procurement_plan_created")
            approvals = repo.list_approvals("PENDING")
            self.assertEqual(len(approvals), 1)
            self.assertEqual(approvals[0].required_role, "finance")
            with self.assertRaises(PermissionError):
                repo.decide_approval(
                    approvals[0].approval_id,
                    ApprovalDecision(decision="approved", reviewer_id="demo-manager", reviewer_role="manager"),
                )
            with self.assertRaises(PermissionError):
                repo.decide_approval(
                    approvals[0].approval_id,
                    ApprovalDecision(decision="approved", reviewer_id="demo-user", reviewer_role="finance"),
                )
            decided = repo.decide_approval(
                approvals[0].approval_id,
                ApprovalDecision(
                    decision="approved", reviewer_id="demo-finance", reviewer_role="finance", comment="Reviewed"
                ),
            )
            self.assertEqual(decided.status, "APPROVED")
            self.assertEqual(repo.list_plans()[0].approval_status, "APPROVED")
            self.assertEqual(repo.list_audit_events()[0].action, "approval_approved")
            with sqlite3.connect(repo.db_path) as connection:
                row = connection.execute("SELECT plan_json FROM procurement_plans").fetchone()
                saved_plan = json.loads(row[0])
                external_orders = connection.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0]
            connection.close()
            self.assertNotIn("source_text", saved_plan["request"])
            self.assertEqual(external_orders, 0)
        finally:
            for suffix in ("", "-wal", "-shm"):
                Path(f"{db_path}{suffix}").unlink(missing_ok=True)

    def test_local_order_delivery_replan_and_receiving_workflow(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        db_path = project_root / "data" / f"phase5-test-{uuid.uuid4().hex}.db"
        try:
            repo = SQLiteProcurementRepository(db_path)
            tools = ProcurementTools(SQLiteCatalogAdapter(repo), persistence_repository=repo)
            manager = ManagerAgent(tools)
            plan = manager.plan_text(
                "Нужно закупить 300 SSD минимум 1 TB по цене до 25 000 ₸ за штуку, доставка максимум 7 дней."
            )
            saved = repo.save_plan(plan)
            order = repo.create_purchase_order(saved.plan_id, "LOCAL DRAFT only")
            self.assertEqual(order.status, "PENDING_APPROVAL")
            self.assertFalse(order.external_order_created)

            approval = repo.list_approvals("PENDING")[0]
            repo.decide_approval(
                approval.approval_id,
                ApprovalDecision(decision="approved", reviewer_id="demo-finance", reviewer_role="finance"),
            )
            order = repo.get_purchase_order(order.order_id)
            self.assertEqual(order.status, "APPROVED")

            failed_supplier = order.items[0].supplier_id
            replanned = manager.plan(saved.request, excluded_supplier_ids={failed_supplier})
            self.assertTrue(all(line.supplier_id != failed_supplier for line in replanned.lines))
            self.assertTrue(any("исключило поставщиков" in line for line in replanned.explanation))

            supplier_ids = sorted({item.supplier_id for item in order.items})
            for supplier_id in supplier_ids:
                repo.update_delivery(order.order_id, DeliveryUpdate(supplier_id=supplier_id, status="ORDERED"))
            delayed = repo.update_delivery(
                order.order_id,
                DeliveryUpdate(supplier_id=failed_supplier, status="DELAYED", note="Ручная отметка задержки"),
            )
            self.assertEqual(delayed.status, "DELAYED")
            self.assertEqual(repo.get_purchase_order(order.order_id).status, "DELAYED")
            failed_item = next(item for item in order.items if item.supplier_id == failed_supplier)
            with self.assertRaisesRegex(ValueError, "must be marked DELIVERED"):
                repo.receive_order(order.order_id, ReceivingRequest(items=[ReceivingLineInput(
                    order_item_id=failed_item.id, quantity_received=1
                )]))
            for supplier_id in supplier_ids:
                if supplier_id != failed_supplier:
                    repo.update_delivery(order.order_id, DeliveryUpdate(supplier_id=supplier_id, status="DELIVERED"))

            before = {item.product_id: item.on_hand for item in repo.list_inventory()}
            available_lines = [item for item in order.items if item.supplier_id != failed_supplier]
            partial_items = [ReceivingLineInput(
                order_item_id=item.id, quantity_received=max(1, item.quantity // 2),
                damaged_quantity=1 if item.quantity // 2 > 1 else 0,
            ) for item in available_lines]
            partial = repo.receive_order(
                order.order_id,
                ReceivingRequest(items=partial_items),
            )
            self.assertGreaterEqual(partial[0].accepted_quantity, 0)
            self.assertEqual(repo.get_purchase_order(order.order_id).status, "DELAYED")

            repo.update_delivery(
                order.order_id, DeliveryUpdate(supplier_id=failed_supplier, status="DELIVERED")
            )

            receipt_items = []
            for item in order.items:
                received_so_far = sum(
                    row.received_quantity for row in repo.list_receiving_records(order.order_id)
                    if row.order_item_id == item.id
                )
                remaining = item.quantity - received_so_far
                if remaining:
                    receipt_items.append(ReceivingLineInput(
                        order_item_id=item.id, quantity_received=remaining,
                    damaged_quantity=1 if remaining > 1 else 0,
                ))
            final_receipts = repo.receive_order(
                order.order_id, ReceivingRequest(note="Ручная проверка партии", items=receipt_items)
            )
            self.assertEqual(repo.get_purchase_order(order.order_id).status, "RECEIVED")
            self.assertEqual(len(repo.list_receiving_records(order.order_id)), len(final_receipts) + len(partial))
            self.assertGreater(sum(item.damaged_quantity for item in final_receipts), 0)
            added_by_product = {}
            for record in [*partial, *final_receipts]:
                added_by_product[record.product_id] = added_by_product.get(record.product_id, 0) + record.accepted_quantity
            after = {item.product_id: item.on_hand for item in repo.list_inventory()}
            for product_id, accepted in added_by_product.items():
                self.assertEqual(after[product_id] - before[product_id], accepted)
            self.assertFalse(repo.get_purchase_order(order.order_id).external_order_created)
            actions = [item.action for item in repo.list_audit_events(20)]
            self.assertIn("local_order_draft_created", actions)
            self.assertIn("delivery_status_recorded", actions)
            self.assertIn("goods_received", actions)
        finally:
            for suffix in ("", "-wal", "-shm"):
                Path(f"{db_path}{suffix}").unlink(missing_ok=True)


class ReorderTests(unittest.TestCase):
    def test_missing_history_only_reorders_to_threshold(self) -> None:
        class EmptyHistoryRepository:
            def list_demand_history(self, product_id: int, limit: int = 12):
                return []

        item = InventoryItem(
            product_id=4,
            product_name="SSD NVMe 1TB",
            on_hand=42,
            reserved=10,
            available=32,
            reorder_point=50,
        )
        forecast = DemandForecastService(InventoryService(EmptyHistoryRepository())).forecast(item)
        recommendation = ReorderService.recommend(item, forecast, lead_time_days=3)

        self.assertEqual(forecast.status, "insufficient_data")
        self.assertIsNone(forecast.average_monthly_demand)
        self.assertEqual(recommendation.expected_lead_time_demand, 0)
        self.assertEqual(recommendation.recommended_quantity, 18)


class ToolLayerTests(unittest.TestCase):
    def test_sample_adapter_exposes_only_linked_catalog_records(self) -> None:
        tools = ProcurementTools()
        products = tools.find_products("ssd")
        matches = tools.match_products(
            PurchaseRequest(product_query="ssd", required_specs={"ssd_gb": 1024}),
            products,
        )

        self.assertEqual({product.id for product in products}, {4, 5, 6})
        self.assertTrue(any(match.match_type == "unsuitable" for match in matches))
        self.assertTrue(all(match.offer.data_source == "DEMO DATA" for match in matches))


if __name__ == "__main__":
    unittest.main()
