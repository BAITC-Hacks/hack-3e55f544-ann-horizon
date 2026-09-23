import uuid
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend.agents.manager import ManagerAgent
from backend.api import get_plan
from backend.integrations.catalog import SQLiteCatalogAdapter
from backend.models.purchase import ApprovalDecision, DeliveryUpdate, ReceivingLineInput, ReceivingRequest
from backend.repositories.procurement import SQLiteProcurementRepository
from backend.tools.procurement import ProcurementTools


class PartialDeliveryTests(unittest.TestCase):
    def test_delivered_supplier_can_be_received_while_other_shipment_is_in_transit(self):
        db_path = Path(__file__).resolve().parents[1] / "data" / f"partial-delivery-test-{uuid.uuid4().hex}.db"
        try:
            repo = SQLiteProcurementRepository(db_path)
            manager = ManagerAgent(ProcurementTools(SQLiteCatalogAdapter(repo), persistence_repository=repo))
            plan = repo.save_plan(manager.plan_text(
                "Нужно закупить 300 SSD минимум 1 TB по цене до 25 000 ₸ за штуку, доставка максимум 7 дней."
            ))
            approval = repo.list_approvals("PENDING")[0]
            repo.decide_approval(approval.approval_id, ApprovalDecision(
                decision="approved", reviewer_id="demo-finance", reviewer_role="finance"
            ))
            order = repo.create_purchase_order(plan.plan_id)
            delivered = order.items[0]
            pending = next(item for item in order.items if item.supplier_id != delivered.supplier_id)
            for supplier_id in {item.supplier_id for item in order.items}:
                repo.update_delivery(order.order_id, DeliveryUpdate(supplier_id=supplier_id, status="ORDERED"))
            repo.update_delivery(order.order_id, DeliveryUpdate(supplier_id=delivered.supplier_id, status="DELIVERED"))
            self.assertEqual(repo.get_purchase_order(order.order_id).status, "ORDERED")
            repo.receive_order(order.order_id, ReceivingRequest(items=[ReceivingLineInput(
                order_item_id=delivered.id, quantity_received=1
            )]))
            self.assertEqual(repo.get_purchase_order(order.order_id).status, "ORDERED")
            repo.update_delivery(order.order_id, DeliveryUpdate(supplier_id=pending.supplier_id, status="SHIPPED"))
            repo.receive_order(order.order_id, ReceivingRequest(items=[ReceivingLineInput(
                order_item_id=delivered.id, quantity_received=1
            )]))
            self.assertEqual(repo.get_purchase_order(order.order_id).status, "SHIPPED")
            with self.assertRaisesRegex(ValueError, "must be marked DELIVERED"):
                repo.receive_order(order.order_id, ReceivingRequest(items=[ReceivingLineInput(
                    order_item_id=pending.id, quantity_received=1
                )]))
            with patch("backend.api.get_manager", return_value=manager):
                self.assertEqual(get_plan(plan.plan_id).plan_id, plan.plan_id)
                with self.assertRaises(HTTPException) as caught:
                    get_plan("missing-plan")
                self.assertEqual(caught.exception.status_code, 404)
        finally:
            for suffix in ("", "-wal", "-shm"):
                Path(f"{db_path}{suffix}").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
