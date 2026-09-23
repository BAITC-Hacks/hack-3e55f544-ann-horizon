"""Local B2C records in additive tables on the shared procurement database."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from backend.models.personal_extended import PersonalPreferences, PersonalPurchase, ReturnDraft


_SCHEMA = """
CREATE TABLE IF NOT EXISTS personal_preferences (
    user_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS personal_purchases (
    purchase_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id),
    purchased_at TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_personal_purchases_owner ON personal_purchases(user_id,purchased_at DESC);
CREATE TABLE IF NOT EXISTS personal_return_drafts (
    return_id TEXT PRIMARY KEY,
    purchase_id TEXT NOT NULL REFERENCES personal_purchases(purchase_id),
    user_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    status TEXT NOT NULL CHECK(status IN ('DRAFT','CANCELLED')),
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_personal_returns_owner ON personal_return_drafts(user_id,created_at DESC);
"""


class PersonalExtendedRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        with self._connection() as connection:
            # The procurement repository owns its schema/version and catalog seed.
            if connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'").fetchone() is None:
                raise RuntimeError("Initialize the procurement repository before the personal repository")
            connection.executescript(_SCHEMA)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
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

    @staticmethod
    def _audit(connection, user_id: str, action: str, entity_type: str, entity_id: str, details: dict):
        connection.execute(
            "INSERT INTO audit_log(actor,action,entity_type,entity_id,occurred_at,details_json) VALUES(?,?,?,?,?,?)",
            (user_id, action, entity_type, entity_id, datetime.now(timezone.utc).isoformat(), json.dumps(details)),
        )

    def get_preferences(self, user_id: str) -> PersonalPreferences | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload_json FROM personal_preferences WHERE user_id=?", (user_id,)).fetchone()
        return PersonalPreferences.model_validate_json(row[0]) if row else None

    def save_preferences(self, record: PersonalPreferences) -> PersonalPreferences:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO personal_preferences(user_id,payload_json,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                (record.user_id, record.model_dump_json(), record.updated_at.isoformat()),
            )
            self._audit(connection, record.user_id, "personal_preferences_saved", "personal_preferences", record.user_id, {})
        return record

    def add_purchase(self, record: PersonalPurchase) -> PersonalPurchase:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO personal_purchases(purchase_id,user_id,product_id,purchased_at,quantity,payload_json) VALUES(?,?,?,?,?,?)",
                (record.purchase_id, record.user_id, record.product_id, record.purchased_at.isoformat(), record.quantity, record.model_dump_json()),
            )
            self._audit(connection, record.user_id, "personal_purchase_recorded", "personal_purchase", record.purchase_id,
                        {"product_id": record.product_id, "quantity": record.quantity, "source": "manual"})
        return record

    def get_purchase(self, purchase_id: str, user_id: str) -> PersonalPurchase | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM personal_purchases WHERE purchase_id=? AND user_id=?", (purchase_id, user_id),
            ).fetchone()
        return PersonalPurchase.model_validate_json(row[0]) if row else None

    def list_purchases(self, user_id: str) -> list[PersonalPurchase]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM personal_purchases WHERE user_id=? ORDER BY purchased_at DESC,purchase_id", (user_id,),
            ).fetchall()
        # ISO timestamps with different offsets do not sort chronologically as
        # SQL text; compare parsed aware datetimes and preserve the original zone.
        return sorted([PersonalPurchase.model_validate_json(row[0]) for row in rows],
                      key=lambda item: (item.purchased_at, item.purchase_id), reverse=True)

    def add_return(self, record: ReturnDraft) -> ReturnDraft:
        with self._connection() as connection:
            # Reserve the local draft quantity atomically; this is not a stock reservation.
            connection.execute("BEGIN IMMEDIATE")
            purchase = connection.execute(
                "SELECT quantity FROM personal_purchases WHERE purchase_id=? AND user_id=?",
                (record.purchase_id, record.user_id),
            ).fetchone()
            if purchase is None:
                raise LookupError("Personal purchase not found")
            drafted = connection.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM personal_return_drafts WHERE purchase_id=? AND user_id=? AND status='DRAFT'",
                (record.purchase_id, record.user_id),
            ).fetchone()[0]
            if drafted + record.quantity > purchase[0]:
                raise ValueError("Return draft quantity exceeds the remaining recorded purchase quantity")
            connection.execute(
                "INSERT INTO personal_return_drafts(return_id,purchase_id,user_id,quantity,status,created_at,payload_json) VALUES(?,?,?,?,?,?,?)",
                (record.return_id, record.purchase_id, record.user_id, record.quantity, record.status,
                 record.created_at.isoformat(), record.model_dump_json()),
            )
            self._audit(connection, record.user_id, "personal_return_drafted", "personal_return", record.return_id,
                        {"purchase_id": record.purchase_id, "quantity": record.quantity, "externally_submitted": False})
        return record

    def list_returns(self, user_id: str) -> list[ReturnDraft]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM personal_return_drafts WHERE user_id=? ORDER BY created_at DESC,return_id", (user_id,),
            ).fetchall()
        return [ReturnDraft.model_validate_json(row[0]) for row in rows]

    def cancel_return(self, return_id: str, user_id: str) -> ReturnDraft:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload_json FROM personal_return_drafts WHERE return_id=? AND user_id=?", (return_id, user_id),
            ).fetchone()
            if row is None:
                raise LookupError("Return draft not found")
            record = ReturnDraft.model_validate_json(row[0])
            if record.status == "CANCELLED":
                return record
            record = record.model_copy(update={"status": "CANCELLED"})
            connection.execute("UPDATE personal_return_drafts SET status='CANCELLED',payload_json=? WHERE return_id=?",
                               (record.model_dump_json(), return_id))
            self._audit(connection, user_id, "personal_return_cancelled", "personal_return", return_id, {})
        return record
