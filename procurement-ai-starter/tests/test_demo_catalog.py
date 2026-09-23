import sqlite3
import unittest
import uuid
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from backend.repositories.catalog import JsonCatalogRepository
from backend.repositories.procurement import SQLiteProcurementRepository


class DemoCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = Path(__file__).resolve().parents[1] / "data" / f"demo-catalog-test-{uuid.uuid4().hex}.db"
        self.repo = SQLiteProcurementRepository(self.db_path)
        self.addCleanup(self.db_path.unlink, missing_ok=True)

    def restore_original_catalog_fixture(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("DELETE FROM offers WHERE id>=110")
            connection.execute("DELETE FROM inventory WHERE product_id>=7")
            connection.execute("DELETE FROM demand_history WHERE product_id>=7")
            connection.execute("DELETE FROM products WHERE id>=7")
            connection.execute("DELETE FROM suppliers WHERE id>=4")
            connection.execute("UPDATE offers SET unit_price='23999.50',quantity_available=13 WHERE id=105")

    def test_expanded_sample_seed_is_fully_linked_and_explicitly_synthetic(self) -> None:
        source = JsonCatalogRepository()
        products, suppliers, offers = source.list_products(), source.list_suppliers(), source.list_offers()
        self.assertEqual((len(products), len(suppliers), len(offers)), (10, 5, 21))
        self.assertEqual(len({item.id for item in products}), 10)
        self.assertEqual(len({item.id for item in suppliers}), 5)
        self.assertEqual(len({item.id for item in offers}), 21)
        self.assertTrue(all(item.data_source == "DEMO DATA" for item in [*products, *suppliers, *offers]))
        self.assertTrue(all(offer.product_id in {p.id for p in products} for offer in offers))
        self.assertTrue(all(offer.supplier_id in {s.id for s in suppliers} for offer in offers))
        self.assertEqual({p.category for p in products if p.id >= 7}, {"monitor", "keyboard", "mouse", "headset"})
        self.assertEqual(self.repo.list_products(), products)
        self.assertEqual(self.repo.list_suppliers(), suppliers)
        self.assertEqual(self.repo.list_offers(), offers)
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_existing_database_expands_only_on_explicit_import_and_keeps_user_values(self) -> None:
        self.restore_original_catalog_fixture()
        reopened = SQLiteProcurementRepository(self.db_path)
        self.assertEqual((len(reopened.list_products()), len(reopened.list_suppliers()), len(reopened.list_offers())), (6, 3, 9))
        added = reopened.import_demo_catalog_additions()
        self.assertEqual(added, {"products": 4, "suppliers": 2, "offers": 12})
        saved_offer = next(item for item in reopened.list_offers() if item.id == 105)
        self.assertEqual((saved_offer.unit_price, saved_offer.quantity_available), (Decimal("23999.50"), 13))
        self.assertEqual(reopened.import_demo_catalog_additions(), {"products": 0, "suppliers": 0, "offers": 0})
        self.assertEqual(sum(item.action == "demo_catalog_additions_imported" for item in reopened.list_audit_events()), 1)
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_conflicting_existing_identity_rolls_back_all_additions(self) -> None:
        self.restore_original_catalog_fixture()
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("UPDATE suppliers SET name='Real supplier',data_source='VERIFIED' WHERE id=1")
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.repo.import_demo_catalog_additions()
        self.assertEqual((len(self.repo.list_products()), len(self.repo.list_suppliers()), len(self.repo.list_offers())), (6, 3, 9))
        self.assertEqual(sum(item.action == "demo_catalog_additions_imported" for item in self.repo.list_audit_events()), 0)
        self.assertEqual(self.repo.list_suppliers()[0].name, "Real supplier")


if __name__ == "__main__":
    unittest.main()
