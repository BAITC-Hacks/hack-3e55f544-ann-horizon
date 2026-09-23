from typing import Protocol

from backend.models.analytics import ProcurementAnalyticsSnapshot

from backend.models.purchase import (
    ApprovalDecision,
    ApprovalRecord,
    AuditEvent,
    DeliveryEvent,
    DeliveryUpdate,
    InvoiceSubmission,
    ProcurementFinanceSummary,
    PriceWatch,
    PriceWatchEvent,
    PriceWatchEvaluation,
    PriceWatchInput,
    PriceWatchStatusUpdate,
    PurchaseReminder,
    PurchaseReminderInput,
    PurchaseReminderUpdate,
    WishlistEntry,
    WishlistEntryInput,
    PurchaseInvoice,
    PurchaseOrder,
    PurchaseOrderSummary,
    PurchasePlan,
    ReceivingRecord,
    ReceivingRequest,
    ReorderRecommendation,
    StoredPlanSummary,
)


class ProcurementPersistenceRepository(Protocol):
    def save_plan(self, plan: PurchasePlan) -> PurchasePlan: ...

    def list_plans(self, limit: int = 50) -> list[StoredPlanSummary]: ...

    def list_audit_events(self, limit: int = 100) -> list[AuditEvent]: ...

    def list_approvals(self, status: str | None = None, limit: int = 100) -> list[ApprovalRecord]: ...

    def get_approval(self, approval_id: str) -> ApprovalRecord | None: ...

    def decide_approval(self, approval_id: str, decision: ApprovalDecision) -> ApprovalRecord: ...

    def log_reorder_analysis(self, recommendations: list[ReorderRecommendation]) -> None: ...

    def get_plan(self, plan_id: str) -> PurchasePlan | None: ...

    def create_purchase_order(self, plan_id: str, buyer_note: str | None = None) -> PurchaseOrder: ...

    def get_purchase_order(self, order_id: str) -> PurchaseOrder | None: ...

    def list_purchase_orders(self, limit: int = 100) -> list[PurchaseOrderSummary]: ...

    def update_delivery(self, order_id: str, update: DeliveryUpdate) -> DeliveryEvent: ...

    def list_delivery_events(self, order_id: str) -> list[DeliveryEvent]: ...

    def receive_order(self, order_id: str, request: ReceivingRequest) -> list[ReceivingRecord]: ...

    def list_receiving_records(self, order_id: str) -> list[ReceivingRecord]: ...

    def create_invoice(self, order_id: str, submission: InvoiceSubmission) -> PurchaseInvoice: ...

    def get_invoice(self, invoice_id: str) -> PurchaseInvoice | None: ...

    def list_invoices(self, order_id: str) -> list[PurchaseInvoice]: ...

    def review_invoice(self, invoice_id: str) -> PurchaseInvoice: ...

    def procurement_finance_summary(self) -> ProcurementFinanceSummary: ...

    def procurement_analytics_snapshot(self) -> ProcurementAnalyticsSnapshot: ...

    def add_wishlist_item(self, request: WishlistEntryInput) -> WishlistEntry: ...

    def list_wishlist(self, user_id: str) -> list[WishlistEntry]: ...

    def remove_wishlist_item(self, wishlist_id: str, user_id: str) -> bool: ...

    def create_price_watch(self, request: PriceWatchInput) -> PriceWatch: ...

    def list_price_watches(self, user_id: str) -> list[PriceWatch]: ...

    def update_price_watch_status(
        self, watch_id: str, user_id: str, update: PriceWatchStatusUpdate
    ) -> PriceWatch: ...

    def evaluate_price_watches(self, user_id: str | None = None) -> PriceWatchEvaluation: ...

    def list_price_watch_events(self, watch_id: str, user_id: str) -> list[PriceWatchEvent]: ...

    def create_purchase_reminder(self, request: PurchaseReminderInput) -> PurchaseReminder: ...

    def list_purchase_reminders(self, user_id: str, due_only: bool = False) -> list[PurchaseReminder]: ...

    def update_purchase_reminder(
        self, reminder_id: str, user_id: str, update: PurchaseReminderUpdate
    ) -> PurchaseReminder: ...


class PersistenceService:
    def __init__(self, repository: ProcurementPersistenceRepository) -> None:
        self._repository = repository

    def save_plan(self, plan: PurchasePlan) -> PurchasePlan:
        return self._repository.save_plan(plan)

    def list_plans(self, limit: int = 50) -> list[StoredPlanSummary]:
        return self._repository.list_plans(limit)

    def list_audit_events(self, limit: int = 100) -> list[AuditEvent]:
        return self._repository.list_audit_events(limit)

    def list_approvals(self, status: str | None = None, limit: int = 100) -> list[ApprovalRecord]:
        return self._repository.list_approvals(status, limit)

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        return self._repository.get_approval(approval_id)

    def decide_approval(self, approval_id: str, decision: ApprovalDecision) -> ApprovalRecord:
        return self._repository.decide_approval(approval_id, decision)

    def log_reorder_analysis(self, recommendations: list[ReorderRecommendation]) -> None:
        self._repository.log_reorder_analysis(recommendations)

    def get_plan(self, plan_id: str) -> PurchasePlan | None:
        return self._repository.get_plan(plan_id)

    def create_purchase_order(self, plan_id: str, buyer_note: str | None = None) -> PurchaseOrder:
        return self._repository.create_purchase_order(plan_id, buyer_note)

    def get_purchase_order(self, order_id: str) -> PurchaseOrder | None:
        return self._repository.get_purchase_order(order_id)

    def list_purchase_orders(self, limit: int = 100) -> list[PurchaseOrderSummary]:
        return self._repository.list_purchase_orders(limit)

    def update_delivery(self, order_id: str, update: DeliveryUpdate) -> DeliveryEvent:
        return self._repository.update_delivery(order_id, update)

    def list_delivery_events(self, order_id: str) -> list[DeliveryEvent]:
        return self._repository.list_delivery_events(order_id)

    def receive_order(self, order_id: str, request: ReceivingRequest) -> list[ReceivingRecord]:
        return self._repository.receive_order(order_id, request)

    def list_receiving_records(self, order_id: str) -> list[ReceivingRecord]:
        return self._repository.list_receiving_records(order_id)

    def create_invoice(self, order_id: str, submission: InvoiceSubmission) -> PurchaseInvoice:
        return self._repository.create_invoice(order_id, submission)

    def get_invoice(self, invoice_id: str) -> PurchaseInvoice | None:
        return self._repository.get_invoice(invoice_id)

    def list_invoices(self, order_id: str) -> list[PurchaseInvoice]:
        return self._repository.list_invoices(order_id)

    def review_invoice(self, invoice_id: str) -> PurchaseInvoice:
        return self._repository.review_invoice(invoice_id)

    def procurement_finance_summary(self) -> ProcurementFinanceSummary:
        return self._repository.procurement_finance_summary()

    def procurement_analytics_snapshot(self) -> ProcurementAnalyticsSnapshot:
        return self._repository.procurement_analytics_snapshot()

    def add_wishlist_item(self, request: WishlistEntryInput) -> WishlistEntry:
        return self._repository.add_wishlist_item(request)

    def list_wishlist(self, user_id: str) -> list[WishlistEntry]:
        return self._repository.list_wishlist(user_id)

    def remove_wishlist_item(self, wishlist_id: str, user_id: str) -> bool:
        return self._repository.remove_wishlist_item(wishlist_id, user_id)

    def create_price_watch(self, request: PriceWatchInput) -> PriceWatch:
        return self._repository.create_price_watch(request)

    def list_price_watches(self, user_id: str) -> list[PriceWatch]:
        return self._repository.list_price_watches(user_id)

    def update_price_watch_status(
        self, watch_id: str, user_id: str, update: PriceWatchStatusUpdate
    ) -> PriceWatch:
        return self._repository.update_price_watch_status(watch_id, user_id, update)

    def evaluate_price_watches(self, user_id: str | None = None) -> PriceWatchEvaluation:
        return self._repository.evaluate_price_watches(user_id)

    def list_price_watch_events(self, watch_id: str, user_id: str) -> list[PriceWatchEvent]:
        return self._repository.list_price_watch_events(watch_id, user_id)

    def create_purchase_reminder(self, request: PurchaseReminderInput) -> PurchaseReminder:
        return self._repository.create_purchase_reminder(request)

    def list_purchase_reminders(self, user_id: str, due_only: bool = False) -> list[PurchaseReminder]:
        return self._repository.list_purchase_reminders(user_id, due_only)

    def update_purchase_reminder(
        self, reminder_id: str, user_id: str, update: PurchaseReminderUpdate
    ) -> PurchaseReminder:
        return self._repository.update_purchase_reminder(reminder_id, user_id, update)
