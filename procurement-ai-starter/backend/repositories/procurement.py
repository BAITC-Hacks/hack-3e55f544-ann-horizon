import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from backend.models.analytics import MerchandiseCurrencySnapshot, ProcurementAnalyticsSnapshot

from backend.models.purchase import (
    ApprovalDecision,
    ApprovalRecord,
    AuditEvent,
    CurrencyFinanceSummary,
    DeliveryEvent,
    DeliveryUpdate,
    DemandRecord,
    InventoryItem,
    InvoiceFinding,
    InvoiceLineInput,
    InvoiceLineRecord,
    InvoiceSubmission,
    Offer,
    ProcurementFinanceSummary,
    PriceWatch,
    PriceWatchEvent,
    PriceWatchInput,
    PriceWatchEvaluation,
    PriceWatchStatusUpdate,
    PriceHistoryRecord,
    Product,
    PurchaseInvoice,
    PurchaseReminder,
    PurchaseReminderInput,
    PurchaseReminderUpdate,
    PurchaseOrder,
    PurchaseOrderItemRecord,
    PurchaseOrderSummary,
    PurchasePlan,
    ReceivingRecord,
    ReceivingRequest,
    ReorderRecommendation,
    StoredPlanSummary,
    Supplier,
    SupplierFinanceSummary,
    WishlistEntry,
    WishlistEntryInput,
)
from backend.services.finance import InvoiceReconciliationService
from backend.services.personal import PriceWatchService, PurchaseReminderService
from backend.repositories.catalog import JsonCatalogRepository


class _DecimalSum:
    """SQLite aggregate for exact money stored as decimal text, without float coercion."""

    def __init__(self) -> None:
        self.total = Decimal("0")

    def step(self, value: str | None) -> None:
        if value is not None:
            self.total += Decimal(value)

    def finalize(self) -> str:
        return str(self.total)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    brand TEXT,
    model TEXT,
    sku TEXT,
    ram_gb INTEGER,
    ssd_gb INTEGER,
    capacity_gb INTEGER,
    interface TEXT,
    data_source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    reliability REAL,
    rating REAL,
    successful_deliveries INTEGER,
    late_deliveries INTEGER,
    average_delay_days REAL,
    defect_rate REAL,
    return_rate REAL,
    data_source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    unit_price TEXT NOT NULL,
    quantity_available INTEGER NOT NULL CHECK(quantity_available >= 0),
    delivery_days INTEGER NOT NULL CHECK(delivery_days >= 0),
    warranty_months INTEGER NOT NULL CHECK(warranty_months >= 0),
    minimum_order_quantity INTEGER NOT NULL CHECK(minimum_order_quantity > 0),
    shipping_cost TEXT,
    tax_rate TEXT,
    currency TEXT NOT NULL,
    data_source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_offers_product ON offers(product_id);
CREATE INDEX IF NOT EXISTS idx_offers_supplier ON offers(supplier_id);
CREATE TABLE IF NOT EXISTS inventory (
    product_id INTEGER PRIMARY KEY REFERENCES products(id),
    on_hand INTEGER NOT NULL CHECK(on_hand >= 0),
    reserved INTEGER NOT NULL CHECK(reserved >= 0 AND reserved <= on_hand),
    reorder_point INTEGER NOT NULL CHECK(reorder_point >= 0),
    data_source TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demand_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    period_start TEXT NOT NULL,
    consumed_quantity INTEGER NOT NULL CHECK(consumed_quantity >= 0),
    data_source TEXT NOT NULL,
    UNIQUE(product_id, period_start)
);
CREATE TABLE IF NOT EXISTS procurement_plans (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('READY_FOR_REVIEW', 'BLOCKED')),
    user_id TEXT NOT NULL,
    user_type TEXT NOT NULL CHECK(user_type IN ('personal', 'business')),
    product_query TEXT NOT NULL,
    quantity_requested INTEGER NOT NULL CHECK(quantity_requested > 0),
    quantity_planned INTEGER NOT NULL CHECK(quantity_planned >= 0),
    merchandise_subtotal TEXT NOT NULL,
    currency TEXT NOT NULL,
    source_label TEXT NOT NULL,
    approval_status TEXT NOT NULL DEFAULT 'NOT_EVALUATED',
    plan_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_procurement_plans_created ON procurement_plans(created_at DESC);
CREATE TABLE IF NOT EXISTS approval_records (
    approval_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL UNIQUE REFERENCES procurement_plans(id),
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED')),
    required_role TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_by TEXT,
    decided_role TEXT,
    decision_comment TEXT,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_approval_records_status ON approval_records(status, created_at DESC);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES procurement_plans(id),
    status TEXT NOT NULL,
    external_order_created INTEGER NOT NULL DEFAULT 0 CHECK(external_order_created IN (0, 1)),
    buyer_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_purchase_orders_plan ON purchase_orders(plan_id);
CREATE TABLE IF NOT EXISTS purchase_order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL REFERENCES purchase_orders(id),
    offer_id INTEGER NOT NULL REFERENCES offers(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price TEXT NOT NULL,
    merchandise_subtotal TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS delivery_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL REFERENCES purchase_orders(id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    status TEXT NOT NULL,
    expected_at TEXT,
    actual_at TEXT,
    tracking_number TEXT,
    note TEXT,
    source_label TEXT NOT NULL DEFAULT 'MANUAL INPUT',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_delivery_events_order ON delivery_events(order_id, id DESC);
CREATE TABLE IF NOT EXISTS receiving_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receiving_id TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL REFERENCES purchase_orders(id),
    order_item_id INTEGER NOT NULL REFERENCES purchase_order_items(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    expected_quantity INTEGER NOT NULL CHECK(expected_quantity >= 0),
    received_quantity INTEGER NOT NULL CHECK(received_quantity > 0),
    damaged_quantity INTEGER NOT NULL CHECK(damaged_quantity >= 0),
    accepted_quantity INTEGER NOT NULL CHECK(accepted_quantity >= 0),
    received_at TEXT NOT NULL,
    note TEXT,
    source_label TEXT NOT NULL DEFAULT 'MANUAL INPUT'
);
CREATE INDEX IF NOT EXISTS idx_receiving_records_order ON receiving_records(order_id, id DESC);
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES purchase_orders(id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    invoice_number TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    currency TEXT NOT NULL,
    subtotal TEXT NOT NULL,
    tax_amount TEXT NOT NULL,
    shipping_amount TEXT NOT NULL,
    total_amount TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PENDING_RECEIVING', 'MATCHED', 'VARIANCE')),
    payment_status TEXT NOT NULL DEFAULT 'NOT_PAID' CHECK(payment_status='NOT_PAID'),
    findings_json TEXT NOT NULL,
    note TEXT,
    source_label TEXT NOT NULL DEFAULT 'MANUAL INPUT',
    created_at TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    UNIQUE(supplier_id, invoice_number)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_invoice_supplier_number_nocase
    ON invoices(supplier_id, invoice_number COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_invoices_order ON invoices(order_id, created_at DESC);
CREATE TABLE IF NOT EXISTS invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
    order_item_id INTEGER NOT NULL REFERENCES purchase_order_items(id),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price TEXT NOT NULL,
    line_total TEXT NOT NULL,
    UNIQUE(invoice_id, order_item_id)
);
CREATE TABLE IF NOT EXISTS wishlist_items (
    wishlist_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id),
    offer_id INTEGER REFERENCES offers(id),
    target_price TEXT,
    currency TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wishlist_user_product_offer
    ON wishlist_items(user_id, product_id, IFNULL(offer_id, 0));
CREATE TABLE IF NOT EXISTS price_watches (
    watch_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id),
    offer_id INTEGER REFERENCES offers(id),
    target_price TEXT NOT NULL,
    baseline_price TEXT NOT NULL,
    last_observed_price TEXT NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'TRIGGERED', 'PAUSED')),
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_watches_user_status ON price_watches(user_id,status);
CREATE TABLE IF NOT EXISTS price_watch_events (
    event_id TEXT PRIMARY KEY,
    watch_id TEXT NOT NULL REFERENCES price_watches(watch_id),
    user_id TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id),
    event_type TEXT NOT NULL CHECK(event_type IN ('PRICE_DROP', 'TARGET_REACHED')),
    previous_price TEXT,
    current_price TEXT NOT NULL,
    target_price TEXT NOT NULL,
    currency TEXT NOT NULL,
    change_amount TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_watch_events_watch ON price_watch_events(watch_id,occurred_at DESC);
CREATE TABLE IF NOT EXISTS purchase_reminders (
    reminder_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    product_id INTEGER REFERENCES products(id),
    product_query TEXT,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    remind_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('OPEN', 'COMPLETED', 'CANCELLED')),
    note TEXT,
    created_at TEXT NOT NULL,
    closed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_purchase_reminders_user_due ON purchase_reminders(user_id,status,remind_at);
CREATE TABLE IF NOT EXISTS purchase_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT REFERENCES purchase_orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    quantity INTEGER NOT NULL CHECK(quantity >= 0),
    unit_price TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    data_source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    details_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_log_occurred ON audit_log(occurred_at DESC);
"""


class SQLiteProcurementRepository:
    """SQLite persistence for catalog records, plans and audit events."""

    def __init__(self, db_path: str | Path | None = None, data_dir: Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[2]
        configured_path = db_path or os.getenv("PROCUREMENT_DB_PATH") or "data/procurement.db"
        candidate = Path(configured_path)
        self._db_path = candidate if candidate.is_absolute() else project_root / candidate
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._data_dir = data_dir
        self._initialize()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def list_price_history(self) -> list[PriceHistoryRecord]:
        """Read immutable synthetic history only for matching demo catalog offers."""
        records = JsonCatalogRepository(self._data_dir).list_price_history()
        offers = {offer.id: offer for offer in self.list_offers()}
        return [
            record for record in records
            if (offer := offers.get(record.offer_id)) is not None
            and offer.data_source == "DEMO DATA"
            and (offer.product_id, offer.supplier_id, offer.currency) == (
                record.product_id, record.supplier_id, record.currency
            )
        ]

    def import_demo_catalog_additions(self) -> dict[str, int]:
        """Explicit, additive demo upgrade; preserve every existing price and stock value."""
        source = JsonCatalogRepository(self._data_dir)
        groups = (
            ("products", source.list_products(), ("name", "category", "sku")),
            ("suppliers", source.list_suppliers(), ("name",)),
            ("offers", source.list_offers(), ("product_id", "supplier_id", "currency")),
        )
        added: dict[str, int] = {}
        with self._connection() as connection:
            for table, records, identity in groups:
                added[table] = 0
                for record in records:
                    payload = record.model_dump()
                    existing = connection.execute(f"SELECT * FROM {table} WHERE id=?", (record.id,)).fetchone()
                    if existing is not None:
                        if existing["data_source"] != "DEMO DATA" or any(
                            existing[column] != payload[column] for column in identity
                        ):
                            raise ValueError(f"Demo catalog conflicts with existing {table} id {record.id}; no records were imported")
                        continue
                    columns = ",".join(payload)
                    placeholders = ",".join("?" for _ in payload)
                    values = tuple(str(value) if isinstance(value, Decimal) else value for value in payload.values())
                    connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", values)
                    added[table] += 1
            if any(added.values()):
                self._insert_audit(
                    connection, "system", "demo_catalog_additions_imported", "catalog", "demo",
                    {**added, "source": "DEMO DATA", "mode": "explicit additive import"},
                    datetime.now(timezone.utc).isoformat(),
                )
        return added

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 5:
                raise RuntimeError(f"Database version {version} is newer than this application supports.")
            connection.executescript(_SCHEMA)
            plan_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(procurement_plans)").fetchall()
            }
            if "approval_status" not in plan_columns:
                connection.execute(
                    "ALTER TABLE procurement_plans ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'NOT_EVALUATED'"
                )
            order_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(purchase_orders)").fetchall()
            }
            if "buyer_note" not in order_columns:
                connection.execute("ALTER TABLE purchase_orders ADD COLUMN buyer_note TEXT")
            if "updated_at" not in order_columns:
                connection.execute("ALTER TABLE purchase_orders ADD COLUMN updated_at TEXT")
                connection.execute("UPDATE purchase_orders SET updated_at=created_at WHERE updated_at IS NULL")
            connection.execute("PRAGMA user_version=5")
            product_count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            if product_count == 0:
                self._seed_sample_data(connection)
            self._seed_sample_demand_if_empty(connection)

    def _seed_sample_data(self, connection: sqlite3.Connection) -> None:
        source = JsonCatalogRepository(self._data_dir)
        connection.executemany(
            """INSERT INTO products
            (id,name,category,brand,model,sku,ram_gb,ssd_gb,capacity_gb,interface,data_source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (p.id, p.name, p.category, p.brand, p.model, p.sku, p.ram_gb, p.ssd_gb,
                 p.capacity_gb, p.interface, p.data_source)
                for p in source.list_products()
            ],
        )
        connection.executemany(
            """INSERT INTO suppliers
            (id,name,reliability,rating,successful_deliveries,late_deliveries,average_delay_days,defect_rate,return_rate,data_source)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                (s.id, s.name, s.reliability, s.rating, s.successful_deliveries, s.late_deliveries,
                 s.average_delay_days, s.defect_rate, s.return_rate, s.data_source)
                for s in source.list_suppliers()
            ],
        )
        connection.executemany(
            """INSERT INTO offers
            (id,product_id,supplier_id,unit_price,quantity_available,delivery_days,warranty_months,
             minimum_order_quantity,shipping_cost,tax_rate,currency,data_source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (o.id, o.product_id, o.supplier_id, str(o.unit_price), o.quantity_available, o.delivery_days,
                 o.warranty_months, o.minimum_order_quantity,
                 str(o.shipping_cost) if o.shipping_cost is not None else None,
                 str(o.tax_rate) if o.tax_rate is not None else None, o.currency, o.data_source)
                for o in source.list_offers()
            ],
        )
        inventory_samples = (
            (1, 40, 5, 20),
            (2, 18, 2, 12),
            (3, 8, 3, 10),
            (4, 42, 10, 50),
            (5, 20, 5, 10),
            (6, 70, 6, 30),
            (7, 12, 1, 4),
            (8, 30, 2, 10),
            (9, 45, 3, 12),
            (10, 16, 2, 6),
        )
        now = datetime.now(timezone.utc).isoformat()
        connection.executemany(
            "INSERT INTO inventory(product_id,on_hand,reserved,reorder_point,data_source,updated_at) VALUES (?,?,?,?,?,?)",
            [(product_id, on_hand, reserved, reorder, "DEMO DATA", now)
             for product_id, on_hand, reserved, reorder in inventory_samples
             if product_id in {product.id for product in source.list_products()}],
        )
        connection.execute(
            """INSERT INTO audit_log(actor,action,entity_type,entity_id,occurred_at,details_json)
            VALUES (?,?,?,?,?,?)""",
            ("system", "seed_demo_catalog", "catalog", "demo", now,
             json.dumps({"products": len(source.list_products()), "suppliers": len(source.list_suppliers()),
                         "offers": len(source.list_offers()), "source": "DEMO DATA"})),
        )

    @staticmethod
    def _seed_sample_demand_if_empty(connection: sqlite3.Connection) -> None:
        count = connection.execute("SELECT COUNT(*) FROM demand_history").fetchone()[0]
        if count:
            return
        product_counts = connection.execute(
            """SELECT COUNT(*) AS total,
            SUM(CASE WHEN data_source='DEMO DATA' THEN 1 ELSE 0 END) AS demo_count
            FROM products"""
        ).fetchone()
        if not product_counts["total"] or product_counts["total"] != product_counts["demo_count"]:
            return
        records = (
            (1, "2026-05-01", 8), (1, "2026-06-01", 10), (1, "2026-07-01", 9), (1, "2026-08-01", 12),
            (2, "2026-05-01", 4), (2, "2026-06-01", 5), (2, "2026-07-01", 4), (2, "2026-08-01", 6),
            (3, "2026-05-01", 1), (3, "2026-06-01", 2), (3, "2026-07-01", 2), (3, "2026-08-01", 3),
            (4, "2026-05-01", 30), (4, "2026-06-01", 36), (4, "2026-07-01", 32), (4, "2026-08-01", 38),
            (5, "2026-05-01", 6), (5, "2026-06-01", 8), (5, "2026-07-01", 7), (5, "2026-08-01", 9),
            (6, "2026-05-01", 5), (6, "2026-06-01", 4), (6, "2026-07-01", 6), (6, "2026-08-01", 5),
            (7, "2026-05-01", 2), (7, "2026-06-01", 3), (7, "2026-07-01", 2), (7, "2026-08-01", 3),
            (8, "2026-05-01", 5), (8, "2026-06-01", 4), (8, "2026-07-01", 6), (8, "2026-08-01", 5),
            (9, "2026-05-01", 6), (9, "2026-06-01", 7), (9, "2026-07-01", 6), (9, "2026-08-01", 8),
            (10, "2026-05-01", 3), (10, "2026-06-01", 2), (10, "2026-07-01", 4), (10, "2026-08-01", 3),
        )
        connection.executemany(
            "INSERT INTO demand_history(product_id,period_start,consumed_quantity,data_source) VALUES (?,?,?,?)",
            [(product_id, period, quantity, "DEMO DATA") for product_id, period, quantity in records
             if connection.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone()],
        )

    def list_products(self) -> list[Product]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM products ORDER BY id").fetchall()
        return [Product.model_validate(dict(row)) for row in rows]

    def list_suppliers(self) -> list[Supplier]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM suppliers ORDER BY id").fetchall()
        return [Supplier.model_validate(dict(row)) for row in rows]

    def list_offers(self) -> list[Offer]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM offers ORDER BY id").fetchall()
        return [Offer.model_validate(dict(row)) for row in rows]

    def list_inventory(self) -> list[InventoryItem]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT p.id AS product_id,p.name AS product_name,i.on_hand,i.reserved,
                (i.on_hand-i.reserved) AS available,i.reorder_point,i.data_source
                FROM inventory i JOIN products p ON p.id=i.product_id ORDER BY p.id"""
            ).fetchall()
        return [InventoryItem.model_validate(dict(row)) for row in rows]

    def list_demand_history(self, product_id: int, limit: int = 12) -> list[DemandRecord]:
        if product_id <= 0 or limit < 1 or limit > 120:
            raise ValueError("product_id must be positive and limit must be from 1 to 120")
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT id,product_id,period_start,consumed_quantity,data_source
                FROM demand_history WHERE product_id=? ORDER BY period_start DESC LIMIT ?""",
                (product_id, limit),
            ).fetchall()
        return [DemandRecord.model_validate(dict(row)) for row in rows]

    def save_plan(self, plan: PurchasePlan) -> PurchasePlan:
        plan_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        saved = plan.model_copy(update={"plan_id": plan_id})
        plan_json = json.dumps(
            saved.model_dump(mode="json", exclude={"request": {"source_text"}}),
            ensure_ascii=False,
        )
        request = plan.request
        details = {
            "status": plan.status,
            "product_query": request.product_query,
            "quantity_requested": request.quantity,
            "quantity_planned": plan.quantity_planned,
            "offer_ids": plan.selected_offer_ids,
            "source": plan.source_label,
        }
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO procurement_plans
                (id,created_at,status,user_id,user_type,product_query,quantity_requested,quantity_planned,
                 merchandise_subtotal,currency,source_label,approval_status,plan_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (plan_id, created_at, plan.status, request.user_context.user_id,
                 request.user_context.user_type, request.product_query, plan.quantity_requested,
                 plan.quantity_planned, str(plan.merchandise_subtotal), plan.currency,
                 plan.source_label, saved.approval_status, plan_json),
            )
            if saved.approval_required and saved.approval_status == "PENDING" and saved.approval_id and saved.approval_role:
                connection.execute(
                    """INSERT INTO approval_records
                    (approval_id,plan_id,status,required_role,requested_by,amount,currency,created_at)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (saved.approval_id, plan_id, "PENDING", saved.approval_role,
                     request.user_context.user_id, str(saved.total_cost), saved.currency, created_at),
                )
                connection.execute(
                    """INSERT INTO audit_log(actor,action,entity_type,entity_id,occurred_at,details_json)
                    VALUES (?,?,?,?,?,?)""",
                    (request.user_context.user_id, "approval_requested", "approval", saved.approval_id,
                     created_at, json.dumps({"plan_id": plan_id, "required_role": saved.approval_role,
                                             "amount": str(saved.total_cost), "currency": saved.currency})),
                )
            connection.execute(
                """INSERT INTO audit_log(actor,action,entity_type,entity_id,occurred_at,details_json)
                VALUES (?,?,?,?,?,?)""",
                (request.user_context.user_id, "procurement_plan_created", "procurement_plan",
                 plan_id, created_at, json.dumps(details, ensure_ascii=False)),
            )
        return saved

    def list_plans(self, limit: int = 50) -> list[StoredPlanSummary]:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be from 1 to 200")
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT id AS plan_id,status,created_at,user_type,product_query,quantity_requested,
                quantity_planned,merchandise_subtotal,currency,source_label,approval_status
                FROM procurement_plans ORDER BY created_at DESC,id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        summaries = []
        for row in rows:
            entry = dict(row)
            entry["merchandise_subtotal"] = Decimal(entry["merchandise_subtotal"])
            summaries.append(StoredPlanSummary.model_validate(entry))
        return summaries

    def list_audit_events(self, limit: int = 100) -> list[AuditEvent]:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be from 1 to 500")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            AuditEvent(
                id=row["id"], actor=row["actor"], action=row["action"],
                entity_type=row["entity_type"], entity_id=row["entity_id"],
                occurred_at=row["occurred_at"], details=json.loads(row["details_json"]),
            )
            for row in rows
        ]

    def get_plan(self, plan_id: str) -> PurchasePlan | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT plan_json FROM procurement_plans WHERE id=?", (plan_id,)
            ).fetchone()
        return PurchasePlan.model_validate(json.loads(row["plan_json"])) if row else None

    def create_purchase_order(self, plan_id: str, buyer_note: str | None = None) -> PurchaseOrder:
        now = datetime.now(timezone.utc).isoformat()
        order_id = str(uuid.uuid4())
        with self._connection() as connection:
            plan_row = connection.execute(
                "SELECT plan_json FROM procurement_plans WHERE id=?", (plan_id,)
            ).fetchone()
            if plan_row is None:
                raise LookupError("Procurement plan not found")
            plan = PurchasePlan.model_validate(json.loads(plan_row["plan_json"]))
            if plan.status != "READY_FOR_REVIEW" or not plan.lines:
                raise ValueError("Only a ready procurement plan with selected items can become a local order draft")
            if plan.approval_status in {"REJECTED", "BLOCKED"}:
                raise ValueError("A rejected or blocked plan cannot become an order draft")
            if connection.execute("SELECT 1 FROM purchase_orders WHERE plan_id=?", (plan_id,)).fetchone():
                raise ValueError("A local order draft already exists for this plan")
            status = "PENDING_APPROVAL" if plan.approval_status == "PENDING" else (
                "APPROVED" if plan.approval_status == "APPROVED" else "DRAFT"
            )
            connection.execute(
                """INSERT INTO purchase_orders
                (id,plan_id,status,external_order_created,buyer_note,created_at,updated_at)
                VALUES (?,?,?,0,?,?,?)""",
                (order_id, plan_id, status, buyer_note, now, now),
            )
            connection.executemany(
                """INSERT INTO purchase_order_items
                (order_id,offer_id,product_id,supplier_id,quantity,unit_price,merchandise_subtotal)
                VALUES (?,?,?,?,?,?,?)""",
                [
                    (order_id, line.offer_id, line.product_id, line.supplier_id,
                     line.quantity, str(line.unit_price), str(line.merchandise_subtotal))
                    for line in plan.lines
                ],
            )
            self._insert_audit(
                connection, plan.request.user_context.user_id, "local_order_draft_created",
                "purchase_order", order_id,
                {"plan_id": plan_id, "status": status, "external_order_created": False}, now,
            )
            row = connection.execute("SELECT * FROM purchase_orders WHERE id=?", (order_id,)).fetchone()
            return self._purchase_order_from_row(connection, row)

    def get_purchase_order(self, order_id: str) -> PurchaseOrder | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM purchase_orders WHERE id=?", (order_id,)).fetchone()
            return self._purchase_order_from_row(connection, row) if row else None

    def list_purchase_orders(self, limit: int = 100) -> list[PurchaseOrderSummary]:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be from 1 to 500")
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT o.*,COUNT(i.id) AS item_count FROM purchase_orders o
                LEFT JOIN purchase_order_items i ON i.order_id=o.id
                GROUP BY o.id ORDER BY o.created_at DESC,o.id DESC LIMIT ?""", (limit,)
            ).fetchall()
        return [
            PurchaseOrderSummary(
                order_id=row["id"], plan_id=row["plan_id"], status=row["status"],
                external_order_created=bool(row["external_order_created"]), buyer_note=row["buyer_note"],
                created_at=row["created_at"], updated_at=row["updated_at"], item_count=row["item_count"],
            )
            for row in rows
        ]

    @staticmethod
    def _purchase_order_from_row(
        connection: sqlite3.Connection, row: sqlite3.Row
    ) -> PurchaseOrder:
        items = connection.execute(
            """SELECT i.*,p.name AS product_name,s.name AS supplier_name
            FROM purchase_order_items i JOIN products p ON p.id=i.product_id
            JOIN suppliers s ON s.id=i.supplier_id WHERE i.order_id=? ORDER BY i.id""",
            (row["id"],),
        ).fetchall()
        return PurchaseOrder(
            order_id=row["id"], plan_id=row["plan_id"], status=row["status"],
            external_order_created=bool(row["external_order_created"]), buyer_note=row["buyer_note"],
            items=[
                PurchaseOrderItemRecord(
                    id=item["id"], order_id=item["order_id"], offer_id=item["offer_id"],
                    product_id=item["product_id"], supplier_id=item["supplier_id"],
                    quantity=item["quantity"], unit_price=Decimal(item["unit_price"]),
                    merchandise_subtotal=Decimal(item["merchandise_subtotal"]),
                    product_name=item["product_name"], supplier_name=item["supplier_name"],
                )
                for item in items
            ],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def update_delivery(self, order_id: str, update: DeliveryUpdate) -> DeliveryEvent:
        now = datetime.now(timezone.utc).isoformat()
        event_id = str(uuid.uuid4())
        with self._connection() as connection:
            order = connection.execute("SELECT * FROM purchase_orders WHERE id=?", (order_id,)).fetchone()
            if order is None:
                raise LookupError("Purchase order not found")
            if order["status"] in {"PENDING_APPROVAL", "CANCELLED", "RECEIVED"}:
                raise ValueError(f"Delivery cannot be updated while order is {order['status']}")
            supplier_item = connection.execute(
                "SELECT 1 FROM purchase_order_items WHERE order_id=? AND supplier_id=? LIMIT 1",
                (order_id, update.supplier_id),
            ).fetchone()
            if supplier_item is None:
                raise ValueError("Supplier is not part of this order")
            previous = connection.execute(
                "SELECT status FROM delivery_events WHERE order_id=? AND supplier_id=? ORDER BY id DESC LIMIT 1",
                (order_id, update.supplier_id),
            ).fetchone()
            current = previous["status"] if previous else None
            allowed = {
                None: {"ORDERED"},
                "ORDERED": {"ORDERED", "SHIPPED", "DELAYED", "DELIVERED", "CANCELLED"},
                "SHIPPED": {"SHIPPED", "DELAYED", "DELIVERED", "CANCELLED"},
                "DELAYED": {"DELAYED", "SHIPPED", "DELIVERED", "CANCELLED"},
                "DELIVERED": {"DELIVERED"},
                "CANCELLED": {"CANCELLED"},
            }
            if update.status not in allowed[current]:
                raise ValueError(f"Invalid delivery transition from {current or 'NOT_REPORTED'} to {update.status}")
            connection.execute(
                """INSERT INTO delivery_events
                (event_id,order_id,supplier_id,status,expected_at,actual_at,tracking_number,note,source_label,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (event_id, order_id, update.supplier_id, update.status, update.expected_at,
                 update.actual_at, update.tracking_number, update.note, update.source_label, now),
            )
            latest = connection.execute(
                """SELECT e.status FROM delivery_events e
                JOIN (SELECT supplier_id,MAX(id) AS latest_id FROM delivery_events
                      WHERE order_id=? GROUP BY supplier_id) x ON x.latest_id=e.id""",
                (order_id,),
            ).fetchall()
            all_suppliers = connection.execute(
                "SELECT COUNT(DISTINCT supplier_id) FROM purchase_order_items WHERE order_id=?", (order_id,)
            ).fetchone()[0]
            statuses = [row["status"] for row in latest]
            if len(statuses) == all_suppliers and all(status == "CANCELLED" for status in statuses):
                order_status = "CANCELLED"
            elif any(status == "DELAYED" for status in statuses) or any(status == "CANCELLED" for status in statuses):
                order_status = "DELAYED"
            elif len(statuses) == all_suppliers and all(status == "DELIVERED" for status in statuses):
                order_status = "DELIVERED"
            elif any(status == "SHIPPED" for status in statuses):
                order_status = "SHIPPED"
            else:
                order_status = "ORDERED"
            connection.execute(
                "UPDATE purchase_orders SET status=?,updated_at=? WHERE id=?", (order_status, now, order_id)
            )
            self._insert_audit(
                connection, "demo-user", "delivery_status_recorded", "purchase_order", order_id,
                {"supplier_id": update.supplier_id, "status": update.status, "source": update.source_label}, now,
            )
        return DeliveryEvent(
            event_id=event_id, order_id=order_id, supplier_id=update.supplier_id, status=update.status,
            expected_at=update.expected_at, actual_at=update.actual_at, tracking_number=update.tracking_number,
            note=update.note, source_label=update.source_label, created_at=now,
        )

    def list_delivery_events(self, order_id: str) -> list[DeliveryEvent]:
        with self._connection() as connection:
            if connection.execute("SELECT 1 FROM purchase_orders WHERE id=?", (order_id,)).fetchone() is None:
                raise LookupError("Purchase order not found")
            rows = connection.execute(
                "SELECT * FROM delivery_events WHERE order_id=? ORDER BY id", (order_id,)
            ).fetchall()
        return [
            DeliveryEvent(
                event_id=row["event_id"], order_id=row["order_id"], supplier_id=row["supplier_id"],
                status=row["status"], expected_at=row["expected_at"], actual_at=row["actual_at"],
                tracking_number=row["tracking_number"], note=row["note"],
                source_label=row["source_label"], created_at=row["created_at"],
            ) for row in rows
        ]

    def receive_order(self, order_id: str, request: ReceivingRequest) -> list[ReceivingRecord]:
        now = request.received_at or datetime.now(timezone.utc).isoformat()
        new_records: list[ReceivingRecord] = []
        if len({item.order_item_id for item in request.items}) != len(request.items):
            raise ValueError("Each order item can appear only once in a receiving request")
        with self._connection() as connection:
            order = connection.execute("SELECT * FROM purchase_orders WHERE id=?", (order_id,)).fetchone()
            if order is None:
                raise LookupError("Purchase order not found")
            if order["status"] not in {"ORDERED", "SHIPPED", "DELAYED", "DELIVERED", "RECEIVED"}:
                raise ValueError("Receiving can be recorded only for a delivered order or delivered supplier lines")
            for line in request.items:
                item = connection.execute(
                    "SELECT * FROM purchase_order_items WHERE id=? AND order_id=?",
                    (line.order_item_id, order_id),
                ).fetchone()
                if item is None:
                    raise ValueError(f"Order item {line.order_item_id} does not belong to this order")
                supplier_delivery = connection.execute(
                    """SELECT status FROM delivery_events WHERE order_id=? AND supplier_id=?
                    ORDER BY id DESC LIMIT 1""",
                    (order_id, item["supplier_id"]),
                ).fetchone()
                if supplier_delivery is None or supplier_delivery["status"] != "DELIVERED":
                    raise ValueError(
                        f"Supplier {item['supplier_id']} must be marked DELIVERED before receiving its items"
                    )
                already_received = connection.execute(
                    "SELECT COALESCE(SUM(received_quantity),0) FROM receiving_records WHERE order_item_id=?",
                    (line.order_item_id,),
                ).fetchone()[0]
                remaining = item["quantity"] - already_received
                if line.quantity_received > remaining:
                    raise ValueError(
                        f"Received quantity exceeds remaining amount for order item {line.order_item_id} ({remaining})"
                    )
                receiving_id = str(uuid.uuid4())
                accepted = line.quantity_received - line.damaged_quantity
                connection.execute(
                    """INSERT INTO receiving_records
                    (receiving_id,order_id,order_item_id,product_id,expected_quantity,received_quantity,
                     damaged_quantity,accepted_quantity,received_at,note,source_label)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (receiving_id, order_id, line.order_item_id, item["product_id"], item["quantity"],
                     line.quantity_received, line.damaged_quantity, accepted, now, request.note, "MANUAL INPUT"),
                )
                inventory = connection.execute(
                    "SELECT product_id FROM inventory WHERE product_id=?", (item["product_id"],)
                ).fetchone()
                if inventory:
                    connection.execute(
                        "UPDATE inventory SET on_hand=on_hand+?,data_source='MANUAL INPUT',updated_at=? WHERE product_id=?",
                        (accepted, now, item["product_id"]),
                    )
                else:
                    connection.execute(
                        """INSERT INTO inventory(product_id,on_hand,reserved,reorder_point,data_source,updated_at)
                        VALUES (?, ?, 0, 0, 'MANUAL INPUT', ?)""", (item["product_id"], accepted, now)
                    )
                if accepted:
                    connection.execute(
                        """INSERT INTO purchase_history(order_id,product_id,supplier_id,quantity,unit_price,occurred_at,data_source)
                        VALUES (?,?,?,?,?,?,?)""",
                        (order_id, item["product_id"], item["supplier_id"], accepted,
                         item["unit_price"], now, "MANUAL INPUT"),
                    )
                new_records.append(ReceivingRecord(
                    receiving_id=receiving_id, order_id=order_id, order_item_id=line.order_item_id,
                    product_id=item["product_id"], expected_quantity=item["quantity"],
                    received_quantity=line.quantity_received, damaged_quantity=line.damaged_quantity,
                    accepted_quantity=accepted, received_at=now, note=request.note,
                ))
            totals = connection.execute(
                """SELECT i.id,i.quantity,COALESCE(SUM(r.received_quantity),0) AS received
                FROM purchase_order_items i LEFT JOIN receiving_records r ON r.order_item_id=i.id
                WHERE i.order_id=? GROUP BY i.id""", (order_id,)
            ).fetchall()
            if all(row["received"] >= row["quantity"] for row in totals):
                order_status = "RECEIVED"
            else:
                # A received supplier shipment does not imply that other suppliers
                # have delivered their part of a split purchase order.
                order_status = order["status"]
            connection.execute(
                "UPDATE purchase_orders SET status=?,updated_at=? WHERE id=?", (order_status, now, order_id)
            )
            self._insert_audit(
                connection, "demo-user", "goods_received", "purchase_order", order_id,
                {"receiving_ids": [item.receiving_id for item in new_records],
                 "accepted_quantity": sum(item.accepted_quantity for item in new_records),
                 "damaged_quantity": sum(item.damaged_quantity for item in new_records)}, now,
            )
        return new_records

    def list_receiving_records(self, order_id: str) -> list[ReceivingRecord]:
        with self._connection() as connection:
            if connection.execute("SELECT 1 FROM purchase_orders WHERE id=?", (order_id,)).fetchone() is None:
                raise LookupError("Purchase order not found")
            rows = connection.execute(
                "SELECT * FROM receiving_records WHERE order_id=? ORDER BY id", (order_id,)
            ).fetchall()
        return [
            ReceivingRecord(
                receiving_id=row["receiving_id"], order_id=row["order_id"],
                order_item_id=row["order_item_id"], product_id=row["product_id"],
                expected_quantity=row["expected_quantity"], received_quantity=row["received_quantity"],
                damaged_quantity=row["damaged_quantity"], accepted_quantity=row["accepted_quantity"],
                received_at=row["received_at"], note=row["note"], source_label=row["source_label"],
            ) for row in rows
        ]

    def create_invoice(self, order_id: str, submission: InvoiceSubmission) -> PurchaseInvoice:
        now = datetime.now(timezone.utc).isoformat()
        invoice_id = str(uuid.uuid4())
        with self._connection() as connection:
            order = connection.execute(
                """SELECT o.status,o.external_order_created,p.plan_json
                FROM purchase_orders o JOIN procurement_plans p ON p.id=o.plan_id WHERE o.id=?""",
                (order_id,),
            ).fetchone()
            if order is None:
                raise LookupError("Purchase order not found")
            if order["status"] in {"DRAFT", "PENDING_APPROVAL", "APPROVED", "CANCELLED"}:
                raise ValueError("Invoice can be recorded only after the order is marked ORDERED")
            if order["external_order_created"]:
                raise ValueError("External order records are not supported by this local invoice workflow")
            supplier = connection.execute(
                "SELECT id,name FROM suppliers WHERE id=?", (submission.supplier_id,)
            ).fetchone()
            if supplier is None:
                raise ValueError("Supplier not found")
            duplicate = connection.execute(
                """SELECT 1 FROM invoices WHERE supplier_id=? AND invoice_number=? COLLATE NOCASE""",
                (submission.supplier_id, submission.invoice_number),
            ).fetchone()
            if duplicate:
                raise ValueError("An invoice with this number already exists for the supplier")
            item_rows = connection.execute(
                """SELECT i.id,i.order_id,i.offer_id,i.product_id,i.supplier_id,i.quantity,
                i.unit_price,i.merchandise_subtotal,p.name AS product_name,s.name AS supplier_name
                FROM purchase_order_items i JOIN products p ON p.id=i.product_id
                JOIN suppliers s ON s.id=i.supplier_id WHERE i.order_id=? ORDER BY i.id""",
                (order_id,),
            ).fetchall()
            order_items = [
                PurchaseOrderItemRecord(
                    id=row["id"], order_id=row["order_id"], offer_id=row["offer_id"],
                    product_id=row["product_id"], supplier_id=row["supplier_id"], quantity=row["quantity"],
                    unit_price=Decimal(row["unit_price"]),
                    merchandise_subtotal=Decimal(row["merchandise_subtotal"]),
                    product_name=row["product_name"], supplier_name=row["supplier_name"],
                ) for row in item_rows
            ]
            supplier_order_items = [item for item in order_items if item.supplier_id == submission.supplier_id]
            if not supplier_order_items:
                raise ValueError("Supplier is not part of this order")
            receipts = connection.execute(
                """SELECT order_item_id,SUM(received_quantity) AS received,SUM(accepted_quantity) AS accepted
                FROM receiving_records WHERE order_id=? GROUP BY order_item_id""", (order_id,)
            ).fetchall()
            received_quantities = {
                row["order_item_id"]: (row["received"] or 0, row["accepted"] or 0) for row in receipts
            }
            plan = PurchasePlan.model_validate(json.loads(order["plan_json"]))
            evaluation = InvoiceReconciliationService().evaluate(
                submission, supplier_order_items, received_quantities, plan.currency
            )
            connection.execute(
                """INSERT INTO invoices
                (invoice_id,order_id,supplier_id,invoice_number,invoice_date,currency,subtotal,tax_amount,
                 shipping_amount,total_amount,status,payment_status,findings_json,note,source_label,created_at,reviewed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'NOT_PAID',?,?,'MANUAL INPUT',?,?)""",
                (invoice_id, order_id, submission.supplier_id, submission.invoice_number,
                 submission.invoice_date, submission.currency, str(submission.subtotal),
                 str(submission.tax_amount), str(submission.shipping_amount), str(submission.total_amount),
                 evaluation.status, json.dumps([item.model_dump(mode="json") for item in evaluation.findings],
                                               ensure_ascii=False), submission.note, now, now),
            )
            connection.executemany(
                """INSERT INTO invoice_lines(invoice_id,order_item_id,quantity,unit_price,line_total)
                VALUES (?,?,?,?,?)""",
                [(invoice_id, line.order_item_id, line.quantity, str(line.unit_price), str(line.line_total))
                 for line in evaluation.lines],
            )
            self._insert_audit(
                connection, "demo-user", "purchase_invoice_recorded", "purchase_invoice", invoice_id,
                {"order_id": order_id, "supplier_id": submission.supplier_id,
                 "invoice_number": submission.invoice_number, "status": evaluation.status,
                 "total_amount": str(submission.total_amount), "currency": submission.currency,
                 "payment_status": "NOT_PAID"}, now,
            )
            row = connection.execute("SELECT * FROM invoices WHERE invoice_id=?", (invoice_id,)).fetchone()
            return self._purchase_invoice_from_row(connection, row)

    def get_invoice(self, invoice_id: str) -> PurchaseInvoice | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM invoices WHERE invoice_id=?", (invoice_id,)).fetchone()
            return self._purchase_invoice_from_row(connection, row) if row else None

    def list_invoices(self, order_id: str) -> list[PurchaseInvoice]:
        with self._connection() as connection:
            if connection.execute("SELECT 1 FROM purchase_orders WHERE id=?", (order_id,)).fetchone() is None:
                raise LookupError("Purchase order not found")
            rows = connection.execute(
                "SELECT * FROM invoices WHERE order_id=? ORDER BY invoice_date,invoice_number",
                (order_id,),
            ).fetchall()
            return [self._purchase_invoice_from_row(connection, row) for row in rows]

    def review_invoice(self, invoice_id: str) -> PurchaseInvoice:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            invoice = connection.execute(
                "SELECT * FROM invoices WHERE invoice_id=?", (invoice_id,)
            ).fetchone()
            if invoice is None:
                raise LookupError("Invoice not found")
            item_rows = connection.execute(
                """SELECT i.id,i.order_id,i.offer_id,i.product_id,i.supplier_id,i.quantity,
                i.unit_price,i.merchandise_subtotal,p.name AS product_name,s.name AS supplier_name
                FROM purchase_order_items i JOIN products p ON p.id=i.product_id
                JOIN suppliers s ON s.id=i.supplier_id WHERE i.order_id=? AND i.supplier_id=? ORDER BY i.id""",
                (invoice["order_id"], invoice["supplier_id"]),
            ).fetchall()
            order_items = [
                PurchaseOrderItemRecord(
                    id=row["id"], order_id=row["order_id"], offer_id=row["offer_id"],
                    product_id=row["product_id"], supplier_id=row["supplier_id"], quantity=row["quantity"],
                    unit_price=Decimal(row["unit_price"]),
                    merchandise_subtotal=Decimal(row["merchandise_subtotal"]),
                    product_name=row["product_name"], supplier_name=row["supplier_name"],
                ) for row in item_rows
            ]
            line_rows = connection.execute(
                "SELECT order_item_id,quantity,unit_price FROM invoice_lines WHERE invoice_id=? ORDER BY id",
                (invoice_id,),
            ).fetchall()
            submission = InvoiceSubmission(
                supplier_id=invoice["supplier_id"], invoice_number=invoice["invoice_number"],
                invoice_date=invoice["invoice_date"], currency=invoice["currency"],
                subtotal=Decimal(invoice["subtotal"]), tax_amount=Decimal(invoice["tax_amount"]),
                shipping_amount=Decimal(invoice["shipping_amount"]), total_amount=Decimal(invoice["total_amount"]),
                items=[InvoiceLineInput(
                    order_item_id=row["order_item_id"], quantity=row["quantity"],
                    unit_price=Decimal(row["unit_price"]),
                ) for row in line_rows], note=invoice["note"],
            )
            receipts = connection.execute(
                """SELECT order_item_id,SUM(received_quantity) AS received,SUM(accepted_quantity) AS accepted
                FROM receiving_records WHERE order_id=? GROUP BY order_item_id""", (invoice["order_id"],)
            ).fetchall()
            received_quantities = {
                row["order_item_id"]: (row["received"] or 0, row["accepted"] or 0) for row in receipts
            }
            plan_row = connection.execute(
                """SELECT p.plan_json FROM procurement_plans p
                JOIN purchase_orders o ON o.plan_id=p.id WHERE o.id=?""", (invoice["order_id"],)
            ).fetchone()
            plan = PurchasePlan.model_validate(json.loads(plan_row["plan_json"]))
            evaluation = InvoiceReconciliationService().evaluate(
                submission, order_items, received_quantities, plan.currency
            )
            connection.execute(
                "UPDATE invoices SET status=?,findings_json=?,reviewed_at=? WHERE invoice_id=?",
                (evaluation.status,
                 json.dumps([item.model_dump(mode="json") for item in evaluation.findings], ensure_ascii=False),
                 now, invoice_id),
            )
            self._insert_audit(
                connection, "demo-user", "purchase_invoice_reconciled", "purchase_invoice", invoice_id,
                {"order_id": invoice["order_id"], "status": evaluation.status,
                 "payment_status": invoice["payment_status"]}, now,
            )
            row = connection.execute("SELECT * FROM invoices WHERE invoice_id=?", (invoice_id,)).fetchone()
            return self._purchase_invoice_from_row(connection, row)

    @staticmethod
    def _purchase_invoice_from_row(connection: sqlite3.Connection, row: sqlite3.Row) -> PurchaseInvoice:
        supplier = connection.execute(
            "SELECT name FROM suppliers WHERE id=?", (row["supplier_id"],)
        ).fetchone()
        lines = connection.execute(
            "SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY id", (row["invoice_id"],)
        ).fetchall()
        return PurchaseInvoice(
            invoice_id=row["invoice_id"], order_id=row["order_id"], supplier_id=row["supplier_id"],
            supplier_name=supplier["name"] if supplier else None, invoice_number=row["invoice_number"],
            invoice_date=row["invoice_date"], currency=row["currency"],
            subtotal=Decimal(row["subtotal"]), tax_amount=Decimal(row["tax_amount"]),
            shipping_amount=Decimal(row["shipping_amount"]), total_amount=Decimal(row["total_amount"]),
            status=row["status"], payment_status=row["payment_status"],
            findings=[InvoiceFinding.model_validate(item) for item in json.loads(row["findings_json"])],
            items=[InvoiceLineRecord(
                id=line["id"], invoice_id=line["invoice_id"], order_item_id=line["order_item_id"],
                quantity=line["quantity"], unit_price=Decimal(line["unit_price"]),
                line_total=Decimal(line["line_total"]),
            ) for line in lines], note=row["note"], source_label=row["source_label"],
            created_at=row["created_at"], reviewed_at=row["reviewed_at"],
        )

    def procurement_analytics_snapshot(self) -> ProcurementAnalyticsSnapshot:
        with self._connection() as connection:
            # All queries see the same read snapshot even if a delivery is updated concurrently.
            connection.execute("BEGIN")
            connection.create_aggregate("decimal_sum", 1, _DecimalSum)
            counts = connection.execute("""
                SELECT
                (SELECT COUNT(*) FROM purchase_orders) AS order_count,
                (SELECT COUNT(*) FROM purchase_orders WHERE status NOT IN ('RECEIVED','CANCELLED')) AS active_order_count,
                (SELECT COUNT(*) FROM approval_records WHERE status='PENDING') AS pending_approval_count,
                (SELECT COUNT(*) FROM inventory WHERE on_hand-reserved>0 AND on_hand-reserved<=reorder_point) AS low_stock_count,
                (SELECT COUNT(*) FROM inventory WHERE on_hand-reserved=0) AS stockout_count
            """).fetchone()
            delays = connection.execute("""
                WITH latest AS (
                    SELECT MAX(id) AS event_id FROM delivery_events GROUP BY order_id,supplier_id
                )
                SELECT COUNT(DISTINCT e.supplier_id) AS suppliers,COUNT(*) AS shipments
                FROM delivery_events e JOIN latest l ON l.event_id=e.id
                JOIN purchase_orders o ON o.id=e.order_id
                WHERE e.status='DELAYED' AND o.status NOT IN ('RECEIVED','CANCELLED')
            """).fetchone()
            reorder_count = connection.execute("""
                SELECT
                (SELECT COUNT(*) FROM audit_log WHERE action='reorder_analysis_completed') +
                (SELECT COUNT(DISTINCT legacy.occurred_at) FROM audit_log legacy
                 WHERE legacy.action IN ('reorder_recommendation_created','reorder_analysis_no_action')
                 AND NOT EXISTS (
                    SELECT 1 FROM audit_log complete WHERE complete.action='reorder_analysis_completed'
                    AND complete.occurred_at=legacy.occurred_at
                 ))
            """).fetchone()[0]
            receipts = connection.execute("""
                SELECT COALESCE(SUM(received_quantity),0) AS received,
                COALESCE(SUM(accepted_quantity),0) AS accepted,
                COALESCE(SUM(damaged_quantity),0) AS damaged FROM receiving_records
            """).fetchone()
            currency_rows = connection.execute("""
                SELECT p.currency,COUNT(DISTINCT o.id) AS order_count,
                COALESCE(decimal_sum(i.merchandise_subtotal),'0') AS merchandise_total
                FROM purchase_orders o JOIN procurement_plans p ON p.id=o.plan_id
                LEFT JOIN purchase_order_items i ON i.order_id=o.id
                WHERE o.status<>'CANCELLED' GROUP BY p.currency ORDER BY p.currency
            """).fetchall()
            return ProcurementAnalyticsSnapshot(
                generated_at=datetime.now(timezone.utc), **dict(counts),
                delayed_supplier_count=delays["suppliers"], delayed_shipment_count=delays["shipments"],
                reorder_analysis_count=reorder_count,
                received_unit_count=receipts["received"], accepted_unit_count=receipts["accepted"],
                damaged_unit_count=receipts["damaged"],
                currency_merchandise_totals=[MerchandiseCurrencySnapshot(
                    currency=row["currency"], order_count=row["order_count"],
                    order_merchandise_total=Decimal(row["merchandise_total"]),
                ) for row in currency_rows],
            )

    def procurement_finance_summary(self) -> ProcurementFinanceSummary:
        with self._connection() as connection:
            order_rows = connection.execute(
                """SELECT p.currency,i.supplier_id,s.name AS supplier_name,i.merchandise_subtotal
                FROM purchase_order_items i JOIN purchase_orders o ON o.id=i.order_id
                JOIN procurement_plans p ON p.id=o.plan_id JOIN suppliers s ON s.id=i.supplier_id
                WHERE o.status <> 'CANCELLED'"""
            ).fetchall()
            invoice_rows = connection.execute(
                """SELECT i.supplier_id,s.name AS supplier_name,i.currency,i.total_amount,i.status
                FROM invoices i JOIN suppliers s ON s.id=i.supplier_id"""
            ).fetchall()
            receipt_totals = connection.execute(
                """SELECT COALESCE(SUM(received_quantity),0) AS received,
                COALESCE(SUM(accepted_quantity),0) AS accepted,
                COALESCE(SUM(damaged_quantity),0) AS damaged FROM receiving_records"""
            ).fetchone()
            order_count = connection.execute(
                "SELECT COUNT(*) FROM purchase_orders WHERE status <> 'CANCELLED'"
            ).fetchone()[0]
            invoice_count = connection.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
            status_rows = connection.execute(
                "SELECT status,COUNT(*) AS item_count FROM invoices GROUP BY status"
            ).fetchall()

        currency_values: dict[str, dict[str, Decimal]] = {}
        supplier_values: dict[tuple[int, str, str], dict[str, Decimal]] = {}
        for row in order_rows:
            currency = row["currency"]
            totals = currency_values.setdefault(currency, {
                "ordered": Decimal("0"), "invoiced": Decimal("0"), "matched": Decimal("0"),
                "variance": Decimal("0"), "pending": Decimal("0"),
            })
            value = Decimal(row["merchandise_subtotal"])
            totals["ordered"] += value
            key = (row["supplier_id"], row["supplier_name"], currency)
            supplier_values.setdefault(key, {"ordered": Decimal("0"), "invoiced": Decimal("0")})["ordered"] += value
        for row in invoice_rows:
            currency = row["currency"]
            totals = currency_values.setdefault(currency, {
                "ordered": Decimal("0"), "invoiced": Decimal("0"), "matched": Decimal("0"),
                "variance": Decimal("0"), "pending": Decimal("0"),
            })
            value = Decimal(row["total_amount"])
            totals["invoiced"] += value
            if row["status"] == "MATCHED":
                totals["matched"] += value
            elif row["status"] == "VARIANCE":
                totals["variance"] += value
            else:
                totals["pending"] += value
            supplier_key = (row["supplier_id"], row["supplier_name"], currency)
            supplier_values.setdefault(supplier_key, {"ordered": Decimal("0"), "invoiced": Decimal("0")})["invoiced"] += value
        status_counts = {row["status"]: row["item_count"] for row in status_rows}
        return ProcurementFinanceSummary(
            order_count=order_count, invoice_count=invoice_count, invoice_status_counts=status_counts,
            currency_totals=[CurrencyFinanceSummary(
                currency=currency, ordered_subtotal=values["ordered"], invoiced_total=values["invoiced"],
                matched_invoice_total=values["matched"], variance_invoice_total=values["variance"],
                pending_invoice_total=values["pending"],
            ) for currency, values in sorted(currency_values.items())],
            supplier_totals=[SupplierFinanceSummary(
                supplier_id=key[0], supplier_name=key[1], currency=key[2],
                ordered_subtotal=values["ordered"], invoiced_total=values["invoiced"],
            ) for key, values in sorted(supplier_values.items())],
            received_unit_count=receipt_totals["received"],
            accepted_unit_count=receipt_totals["accepted"],
            damaged_unit_count=receipt_totals["damaged"],
        )

    @staticmethod
    def _current_offer_for_price(
        connection: sqlite3.Connection, product_id: int, currency: str, offer_id: int | None = None
    ) -> sqlite3.Row | None:
        query = """SELECT o.id AS offer_id,o.supplier_id,o.unit_price,s.name AS supplier_name
        FROM offers o JOIN suppliers s ON s.id=o.supplier_id
        WHERE o.product_id=? AND o.currency=? AND o.quantity_available>0"""
        params: tuple = (product_id, currency)
        if offer_id is not None:
            query += " AND o.id=?"
            params += (offer_id,)
        rows = connection.execute(query, params).fetchall()
        if not rows:
            return None
        return min(rows, key=lambda row: (Decimal(row["unit_price"]), row["offer_id"]))

    def add_wishlist_item(self, request: WishlistEntryInput) -> WishlistEntry:
        now = datetime.now(timezone.utc).isoformat()
        wishlist_id = str(uuid.uuid4())
        with self._connection() as connection:
            product = connection.execute("SELECT id FROM products WHERE id=?", (request.product_id,)).fetchone()
            if product is None:
                raise LookupError("Product not found")
            current = self._current_offer_for_price(
                connection, request.product_id, request.currency, request.offer_id
            )
            if request.offer_id is not None:
                selected = connection.execute(
                    "SELECT product_id,currency FROM offers WHERE id=?", (request.offer_id,)
                ).fetchone()
                if selected is None or selected["product_id"] != request.product_id:
                    raise ValueError("Offer does not belong to the selected product")
                if selected["currency"] != request.currency:
                    raise ValueError("Offer currency does not match wishlist currency")
            duplicate = connection.execute(
                """SELECT 1 FROM wishlist_items WHERE user_id=? AND product_id=?
                AND IFNULL(offer_id,0)=IFNULL(?,0)""",
                (request.user_id, request.product_id, request.offer_id),
            ).fetchone()
            if duplicate:
                raise ValueError("This product or offer is already on the user's wishlist")
            connection.execute(
                """INSERT INTO wishlist_items
                (wishlist_id,user_id,product_id,offer_id,target_price,currency,note,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (wishlist_id, request.user_id, request.product_id, request.offer_id,
                 str(request.target_price) if request.target_price is not None else None,
                 request.currency, request.note, now),
            )
            self._insert_audit(
                connection, request.user_id, "wishlist_item_added", "wishlist_item", wishlist_id,
                {"product_id": request.product_id, "offer_id": request.offer_id}, now,
            )
            row = connection.execute(
                """SELECT w.*,p.name AS product_name FROM wishlist_items w
                JOIN products p ON p.id=w.product_id WHERE w.wishlist_id=?""", (wishlist_id,)
            ).fetchone()
            return self._wishlist_from_row(connection, row, current)

    @classmethod
    def _wishlist_from_row(
        cls, connection: sqlite3.Connection, row: sqlite3.Row, current: sqlite3.Row | None = None
    ) -> WishlistEntry:
        if current is None:
            current = cls._current_offer_for_price(
                connection, row["product_id"], row["currency"], row["offer_id"]
            )
        return WishlistEntry(
            wishlist_id=row["wishlist_id"], user_id=row["user_id"], product_id=row["product_id"],
            product_name=row["product_name"], offer_id=row["offer_id"],
            supplier_id=current["supplier_id"] if row["offer_id"] is not None and current else None,
            supplier_name=current["supplier_name"] if row["offer_id"] is not None and current else None,
            current_price=Decimal(current["unit_price"]) if current else None,
            target_price=Decimal(row["target_price"]) if row["target_price"] is not None else None,
            currency=row["currency"], note=row["note"], created_at=row["created_at"],
        )

    def list_wishlist(self, user_id: str) -> list[WishlistEntry]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT w.*,p.name AS product_name FROM wishlist_items w
                JOIN products p ON p.id=w.product_id WHERE w.user_id=? ORDER BY w.created_at,w.wishlist_id""",
                (user_id,),
            ).fetchall()
            return [self._wishlist_from_row(connection, row) for row in rows]

    def remove_wishlist_item(self, wishlist_id: str, user_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT wishlist_id FROM wishlist_items WHERE wishlist_id=? AND user_id=?",
                (wishlist_id, user_id),
            ).fetchone()
            if row is None:
                return False
            connection.execute("DELETE FROM wishlist_items WHERE wishlist_id=?", (wishlist_id,))
            self._insert_audit(
                connection, user_id, "wishlist_item_removed", "wishlist_item", wishlist_id, {}, now,
            )
            return True

    def create_price_watch(self, request: PriceWatchInput) -> PriceWatch:
        now = datetime.now(timezone.utc).isoformat()
        watch_id = str(uuid.uuid4())
        with self._connection() as connection:
            product = connection.execute("SELECT id FROM products WHERE id=?", (request.product_id,)).fetchone()
            if product is None:
                raise LookupError("Product not found")
            if request.offer_id is not None:
                selected = connection.execute(
                    "SELECT product_id,currency FROM offers WHERE id=?", (request.offer_id,)
                ).fetchone()
                if selected is None or selected["product_id"] != request.product_id:
                    raise ValueError("Offer does not belong to the selected product")
                if selected["currency"] != request.currency:
                    raise ValueError("Offer currency does not match price watch currency")
            current = self._current_offer_for_price(
                connection, request.product_id, request.currency, request.offer_id
            )
            if current is None:
                raise ValueError("No in-stock offer is available in the selected currency")
            baseline = Decimal(current["unit_price"])
            connection.execute(
                """INSERT INTO price_watches
                (watch_id,user_id,product_id,offer_id,target_price,baseline_price,last_observed_price,
                 currency,status,note,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,'ACTIVE',?,?,?)""",
                (watch_id, request.user_id, request.product_id, request.offer_id, str(request.target_price),
                 str(baseline), str(baseline), request.currency, request.note, now, now),
            )
            self._insert_audit(
                connection, request.user_id, "price_watch_created", "price_watch", watch_id,
                {"product_id": request.product_id, "target_price": str(request.target_price),
                 "baseline_price": str(baseline), "currency": request.currency}, now,
            )
            row = connection.execute(
                """SELECT w.*,p.name AS product_name FROM price_watches w
                JOIN products p ON p.id=w.product_id WHERE w.watch_id=?""", (watch_id,)
            ).fetchone()
            return self._price_watch_from_row(row)

    @staticmethod
    def _price_watch_from_row(row: sqlite3.Row) -> PriceWatch:
        return PriceWatch(
            watch_id=row["watch_id"], user_id=row["user_id"], product_id=row["product_id"],
            product_name=row["product_name"], offer_id=row["offer_id"],
            target_price=Decimal(row["target_price"]), baseline_price=Decimal(row["baseline_price"]),
            last_observed_price=Decimal(row["last_observed_price"]) if row["last_observed_price"] is not None else None,
            currency=row["currency"], status=row["status"], note=row["note"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def list_price_watches(self, user_id: str) -> list[PriceWatch]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT w.*,p.name AS product_name FROM price_watches w
                JOIN products p ON p.id=w.product_id WHERE w.user_id=? ORDER BY w.created_at,w.watch_id""",
                (user_id,),
            ).fetchall()
        return [self._price_watch_from_row(row) for row in rows]

    def update_price_watch_status(
        self, watch_id: str, user_id: str, update: PriceWatchStatusUpdate
    ) -> PriceWatch:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            row = connection.execute(
                """SELECT w.*,p.name AS product_name FROM price_watches w
                JOIN products p ON p.id=w.product_id WHERE w.watch_id=? AND w.user_id=?""",
                (watch_id, user_id),
            ).fetchone()
            if row is None:
                raise LookupError("Price watch not found")
            connection.execute(
                "UPDATE price_watches SET status=?,updated_at=? WHERE watch_id=?",
                (update.status, now, watch_id),
            )
            self._insert_audit(
                connection, user_id, "price_watch_status_changed", "price_watch", watch_id,
                {"status": update.status}, now,
            )
            updated = connection.execute(
                """SELECT w.*,p.name AS product_name FROM price_watches w
                JOIN products p ON p.id=w.product_id WHERE w.watch_id=?""", (watch_id,)
            ).fetchone()
            return self._price_watch_from_row(updated)

    def evaluate_price_watches(self, user_id: str | None = None) -> PriceWatchEvaluation:
        now = datetime.now(timezone.utc).isoformat()
        alerts: list[PriceWatchEvent] = []
        with self._connection() as connection:
            query = """SELECT w.*,p.name AS product_name FROM price_watches w
            JOIN products p ON p.id=w.product_id WHERE w.status='ACTIVE'"""
            params: tuple = ()
            if user_id is not None:
                query += " AND w.user_id=?"
                params = (user_id,)
            rows = connection.execute(query + " ORDER BY w.created_at,w.watch_id", params).fetchall()
            for row in rows:
                current = self._current_offer_for_price(
                    connection, row["product_id"], row["currency"], row["offer_id"]
                )
                if current is None:
                    continue
                previous = Decimal(row["last_observed_price"] or row["baseline_price"])
                current_price = Decimal(current["unit_price"])
                target = Decimal(row["target_price"])
                decision = PriceWatchService.evaluate(previous, current_price, target, row["status"])
                if decision.event_type:
                    event_id = str(uuid.uuid4())
                    connection.execute(
                        """INSERT INTO price_watch_events
                        (event_id,watch_id,user_id,product_id,event_type,previous_price,current_price,
                         target_price,currency,change_amount,occurred_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (event_id, row["watch_id"], row["user_id"], row["product_id"], decision.event_type,
                         str(previous), str(current_price), str(target), row["currency"],
                         str(decision.change_amount), now),
                    )
                    self._insert_audit(
                        connection, row["user_id"], "price_watch_alert_created", "price_watch_event", event_id,
                        {"watch_id": row["watch_id"], "event_type": decision.event_type,
                         "previous_price": str(previous), "current_price": str(current_price),
                         "target_price": str(target)}, now,
                    )
                    alerts.append(PriceWatchEvent(
                        event_id=event_id, watch_id=row["watch_id"], user_id=row["user_id"],
                        product_id=row["product_id"], product_name=row["product_name"],
                        event_type=decision.event_type, previous_price=previous,
                        current_price=current_price, target_price=target, currency=row["currency"],
                        change_amount=decision.change_amount, occurred_at=now,
                    ))
                connection.execute(
                    """UPDATE price_watches SET status=?,last_observed_price=?,updated_at=?
                    WHERE watch_id=?""",
                    (decision.next_status, str(current_price), now, row["watch_id"]),
                )
        return PriceWatchEvaluation(evaluated_count=len(rows), alert_count=len(alerts), alerts=alerts)

    def list_price_watch_events(self, watch_id: str, user_id: str) -> list[PriceWatchEvent]:
        with self._connection() as connection:
            watch = connection.execute(
                "SELECT 1 FROM price_watches WHERE watch_id=? AND user_id=?", (watch_id, user_id)
            ).fetchone()
            if watch is None:
                raise LookupError("Price watch not found")
            rows = connection.execute(
                """SELECT e.*,p.name AS product_name FROM price_watch_events e
                JOIN products p ON p.id=e.product_id WHERE e.watch_id=? ORDER BY e.occurred_at,e.event_id""",
                (watch_id,),
            ).fetchall()
        return [PriceWatchEvent(
            event_id=row["event_id"], watch_id=row["watch_id"], user_id=row["user_id"],
            product_id=row["product_id"], product_name=row["product_name"], event_type=row["event_type"],
            previous_price=Decimal(row["previous_price"]) if row["previous_price"] is not None else None,
            current_price=Decimal(row["current_price"]), target_price=Decimal(row["target_price"]),
            currency=row["currency"], change_amount=Decimal(row["change_amount"]), occurred_at=row["occurred_at"],
        ) for row in rows]

    def create_purchase_reminder(self, request: PurchaseReminderInput) -> PurchaseReminder:
        now = datetime.now(timezone.utc)
        reminder_id = str(uuid.uuid4())
        product_name = None
        with self._connection() as connection:
            if request.product_id is not None:
                product = connection.execute(
                    "SELECT name FROM products WHERE id=?", (request.product_id,)
                ).fetchone()
                if product is None:
                    raise LookupError("Product not found")
                product_name = product["name"]
            remind_at = request.remind_at.astimezone(timezone.utc).isoformat()
            connection.execute(
                """INSERT INTO purchase_reminders
                (reminder_id,user_id,product_id,product_query,quantity,remind_at,status,note,created_at)
                VALUES (?,?,?,?,?,?,'OPEN',?,?)""",
                (reminder_id, request.user_id, request.product_id,
                 request.product_query if request.product_id is None else None,
                 request.quantity, remind_at, request.note, now.isoformat()),
            )
            self._insert_audit(
                connection, request.user_id, "purchase_reminder_created", "purchase_reminder", reminder_id,
                {"product_id": request.product_id, "product_query": request.product_query,
                 "quantity": request.quantity, "remind_at": remind_at}, now.isoformat(),
            )
            row = connection.execute(
                """SELECT r.*,p.name AS product_name FROM purchase_reminders r
                LEFT JOIN products p ON p.id=r.product_id WHERE r.reminder_id=?""", (reminder_id,)
            ).fetchone()
            return self._purchase_reminder_from_row(row)

    @staticmethod
    def _purchase_reminder_from_row(row: sqlite3.Row) -> PurchaseReminder:
        remind_at = datetime.fromisoformat(row["remind_at"])
        return PurchaseReminder(
            reminder_id=row["reminder_id"], user_id=row["user_id"], product_id=row["product_id"],
            product_name=row["product_name"], product_query=row["product_query"], quantity=row["quantity"],
            remind_at=remind_at,
            status=PurchaseReminderService.status(row["status"], remind_at), note=row["note"],
            created_at=row["created_at"], closed_at=row["closed_at"],
        )

    def list_purchase_reminders(self, user_id: str, due_only: bool = False) -> list[PurchaseReminder]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT r.*,p.name AS product_name FROM purchase_reminders r
                LEFT JOIN products p ON p.id=r.product_id WHERE r.user_id=?
                ORDER BY r.remind_at,r.reminder_id""", (user_id,),
            ).fetchall()
            result = [self._purchase_reminder_from_row(row) for row in rows]
        return [item for item in result if not due_only or item.status == "DUE"]

    def update_purchase_reminder(
        self, reminder_id: str, user_id: str, update: PurchaseReminderUpdate
    ) -> PurchaseReminder:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            row = connection.execute(
                """SELECT r.*,p.name AS product_name FROM purchase_reminders r
                LEFT JOIN products p ON p.id=r.product_id WHERE r.reminder_id=? AND r.user_id=?""",
                (reminder_id, user_id),
            ).fetchone()
            if row is None:
                raise LookupError("Purchase reminder not found")
            if row["status"] != "OPEN":
                raise ValueError("Purchase reminder has already been closed")
            connection.execute(
                """UPDATE purchase_reminders SET status=?,note=COALESCE(?,note),closed_at=?
                WHERE reminder_id=?""",
                (update.status, update.note, now, reminder_id),
            )
            self._insert_audit(
                connection, user_id, f"purchase_reminder_{update.status.casefold()}",
                "purchase_reminder", reminder_id, {"status": update.status}, now,
            )
            updated = connection.execute(
                """SELECT r.*,p.name AS product_name FROM purchase_reminders r
                LEFT JOIN products p ON p.id=r.product_id WHERE r.reminder_id=?""", (reminder_id,)
            ).fetchone()
            return self._purchase_reminder_from_row(updated)

    @staticmethod
    def _insert_audit(
        connection: sqlite3.Connection, actor: str, action: str, entity_type: str,
        entity_id: str, details: dict, occurred_at: str,
    ) -> None:
        connection.execute(
            """INSERT INTO audit_log(actor,action,entity_type,entity_id,occurred_at,details_json)
            VALUES (?,?,?,?,?,?)""",
            (actor, action, entity_type, entity_id, occurred_at,
             json.dumps(details, ensure_ascii=False)),
        )

    def list_approvals(self, status: str | None = None, limit: int = 100) -> list[ApprovalRecord]:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be from 1 to 500")
        if status is not None and status not in {"PENDING", "APPROVED", "REJECTED"}:
            raise ValueError("status must be PENDING, APPROVED or REJECTED")
        with self._connection() as connection:
            if status:
                rows = connection.execute(
                    "SELECT * FROM approval_records WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM approval_records ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._approval_from_row(row) for row in rows]

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM approval_records WHERE approval_id=?", (approval_id,)
            ).fetchone()
        return self._approval_from_row(row) if row else None

    def decide_approval(self, approval_id: str, decision: ApprovalDecision) -> ApprovalRecord:
        decided_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM approval_records WHERE approval_id=?", (approval_id,)
            ).fetchone()
            if row is None:
                raise LookupError("Approval not found")
            if row["status"] != "PENDING":
                raise ValueError("Approval has already been decided")
            if decision.reviewer_role.casefold() != row["required_role"].casefold():
                raise PermissionError("Reviewer role does not match the required approval role")
            if decision.reviewer_id == row["requested_by"]:
                raise PermissionError("The requester cannot approve their own procurement plan")
            status = "APPROVED" if decision.decision == "approved" else "REJECTED"
            connection.execute(
                """UPDATE approval_records SET status=?,decided_by=?,decided_role=?,decision_comment=?,decided_at=?
                WHERE approval_id=? AND status='PENDING'""",
                (status, decision.reviewer_id, decision.reviewer_role, decision.comment, decided_at, approval_id),
            )
            plan_row = connection.execute(
                "SELECT plan_json FROM procurement_plans WHERE id=?", (row["plan_id"],)
            ).fetchone()
            plan = PurchasePlan.model_validate(json.loads(plan_row["plan_json"]))
            updated_plan = plan.model_copy(update={"approval_status": status})
            connection.execute(
                "UPDATE procurement_plans SET approval_status=?,plan_json=? WHERE id=?",
                (status, json.dumps(
                    updated_plan.model_dump(mode="json", exclude={"request": {"source_text"}}),
                    ensure_ascii=False,
                ), row["plan_id"]),
            )
            connection.execute(
                "UPDATE purchase_orders SET status=?,updated_at=? WHERE plan_id=? AND status='PENDING_APPROVAL'",
                ("APPROVED" if status == "APPROVED" else "CANCELLED", decided_at, row["plan_id"]),
            )
            connection.execute(
                """INSERT INTO audit_log(actor,action,entity_type,entity_id,occurred_at,details_json)
                VALUES (?,?,?,?,?,?)""",
                (decision.reviewer_id, f"approval_{decision.decision}", "approval", approval_id,
                 decided_at, json.dumps({"plan_id": row["plan_id"], "reviewer_role": decision.reviewer_role})),
            )
            decided = connection.execute(
                "SELECT * FROM approval_records WHERE approval_id=?", (approval_id,)
            ).fetchone()
        return self._approval_from_row(decided)

    @staticmethod
    def _approval_from_row(row: sqlite3.Row) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=row["approval_id"], plan_id=row["plan_id"], status=row["status"],
            required_role=row["required_role"], requested_by=row["requested_by"],
            amount=Decimal(row["amount"]), currency=row["currency"], created_at=row["created_at"],
            decided_by=row["decided_by"], decided_role=row["decided_role"],
            decision_comment=row["decision_comment"], decided_at=row["decided_at"],
        )

    def log_reorder_analysis(self, recommendations: list[ReorderRecommendation]) -> None:
        occurred_at = datetime.now(timezone.utc).isoformat()
        if recommendations:
            events = [
                (
                    "system", "reorder_recommendation_created", "reorder_recommendation",
                    str(item.product_id), occurred_at,
                    json.dumps(item.model_dump(mode="json"), ensure_ascii=False),
                )
                for item in recommendations
            ]
        else:
            events = [(
                "system", "reorder_analysis_no_action", "reorder_analysis", "none",
                occurred_at, json.dumps({"recommendation_count": 0, "source": "DEMO DATA"}),
            )]
        with self._connection() as connection:
            self._insert_audit(
                connection, "system", "reorder_analysis_completed", "reorder_analysis", str(uuid.uuid4()),
                {"recommendation_count": len(recommendations), "source": "DEMO DATA"}, occurred_at,
            )
            connection.executemany(
                """INSERT INTO audit_log(actor,action,entity_type,entity_id,occurred_at,details_json)
                VALUES (?,?,?,?,?,?)""",
                events,
            )
