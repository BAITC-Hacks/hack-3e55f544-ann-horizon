from backend.integrations.catalog import CatalogAdapter, SampleCatalogAdapter
from backend.models.analytics import ProcurementOverview
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
    OfferMatch,
    DemandForecast,
    InventoryItem,
    PriceSummary,
    Product,
    PurchaseOrder,
    PurchaseOrderSummary,
    PurchasePlan,
    PurchaseRequest,
    ReorderRecommendation,
    ReceivingRecord,
    ReceivingRequest,
    StoredPlanSummary,
    SupplierAssessment,
    ValidationFinding,
)
from backend.services.catalog import CatalogService
from backend.services.analytics import AnalyticsService
from backend.services.matching import ProductMatchingService
from backend.services.optimization import AllocationResult, OptimizationService
from backend.services.pricing import PricingService
from backend.services.forecast import DemandForecastService
from backend.services.inventory import InventoryRepository, InventoryService
from backend.services.persistence import PersistenceService, ProcurementPersistenceRepository
from backend.services.reorder import ReorderService
from backend.services.suppliers import SupplierService
from backend.services.validation import ValidationService


class ProcurementTools:
    """Typed tools. Each delegates to a service; agents do not read persistence directly."""

    def __init__(
        self,
        adapter: CatalogAdapter | None = None,
        inventory_repository: InventoryRepository | None = None,
        persistence_repository: ProcurementPersistenceRepository | None = None,
    ) -> None:
        self.catalog = CatalogService(adapter or SampleCatalogAdapter())
        self._matching = ProductMatchingService(self.catalog)
        self._pricing = PricingService()
        self._suppliers = SupplierService()
        self._optimization = OptimizationService()
        self._validation = ValidationService(self.catalog)
        self._inventory = InventoryService(inventory_repository) if inventory_repository else None
        self._forecast = DemandForecastService(self._inventory) if self._inventory else None
        self._reorder = ReorderService()
        self._persistence = PersistenceService(persistence_repository) if persistence_repository else None

    def find_products(self, query: str) -> list[Product]:
        return self.catalog.search_products(query)

    def match_products(self, request: PurchaseRequest, products: list[Product]) -> list[OfferMatch]:
        return self._matching.match(request, products)

    def summarize_prices(self, matches: list[OfferMatch], currency: str) -> PriceSummary:
        offers = [
            match.offer
            for match in matches
            if match.hard_requirements_met and match.offer.currency == currency
        ]
        return self._pricing.summarize(offers, currency, self.catalog.price_history())

    def assess_suppliers(self, matches: list[OfferMatch]) -> list[SupplierAssessment]:
        suppliers = {match.supplier.id: match.supplier for match in matches}
        return [self._suppliers.assess(suppliers[key]) for key in sorted(suppliers)]

    def optimize(self, request: PurchaseRequest, matches: list[OfferMatch]) -> AllocationResult:
        return self._optimization.allocate(request, matches)

    def validate(self, request: PurchaseRequest, plan: PurchasePlan) -> list[ValidationFinding]:
        return self._validation.validate(request, plan)

    def list_inventory(self) -> list[InventoryItem]:
        if self._inventory is None:
            raise RuntimeError("Inventory storage is not configured for this catalog adapter.")
        return self._inventory.list_inventory()

    def forecast_demand(self, item: InventoryItem) -> DemandForecast:
        if self._forecast is None:
            raise RuntimeError("Demand history storage is not configured for this catalog adapter.")
        return self._forecast.forecast(item)

    def recommend_reorder(
        self,
        item: InventoryItem,
        forecast: DemandForecast,
    ) -> ReorderRecommendation:
        offers = [
            offer
            for offer in self.catalog.list_offers()
            if offer.product_id == item.product_id and offer.quantity_available > 0
        ]
        lead_time = min((offer.delivery_days for offer in offers), default=None)
        return self._reorder.recommend(item, forecast, lead_time)

    def save_plan(self, plan: PurchasePlan) -> PurchasePlan:
        return self._require_persistence().save_plan(plan)

    def list_plans(self, limit: int = 50) -> list[StoredPlanSummary]:
        return self._require_persistence().list_plans(limit)

    def list_audit_events(self, limit: int = 100) -> list[AuditEvent]:
        return self._require_persistence().list_audit_events(limit)

    def list_approvals(self, status: str | None = None, limit: int = 100) -> list[ApprovalRecord]:
        return self._require_persistence().list_approvals(status, limit)

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        return self._require_persistence().get_approval(approval_id)

    def decide_approval(self, approval_id: str, decision: ApprovalDecision) -> ApprovalRecord:
        return self._require_persistence().decide_approval(approval_id, decision)

    def log_reorder_analysis(self, recommendations: list[ReorderRecommendation]) -> None:
        self._require_persistence().log_reorder_analysis(recommendations)

    def get_plan(self, plan_id: str) -> PurchasePlan | None:
        return self._require_persistence().get_plan(plan_id)

    def create_purchase_order(self, plan_id: str, buyer_note: str | None = None) -> PurchaseOrder:
        return self._require_persistence().create_purchase_order(plan_id, buyer_note)

    def get_purchase_order(self, order_id: str) -> PurchaseOrder | None:
        return self._require_persistence().get_purchase_order(order_id)

    def list_purchase_orders(self, limit: int = 100) -> list[PurchaseOrderSummary]:
        return self._require_persistence().list_purchase_orders(limit)

    def update_delivery(self, order_id: str, update: DeliveryUpdate) -> DeliveryEvent:
        return self._require_persistence().update_delivery(order_id, update)

    def list_delivery_events(self, order_id: str) -> list[DeliveryEvent]:
        return self._require_persistence().list_delivery_events(order_id)

    def receive_order(self, order_id: str, request: ReceivingRequest) -> list[ReceivingRecord]:
        return self._require_persistence().receive_order(order_id, request)

    def list_receiving_records(self, order_id: str) -> list[ReceivingRecord]:
        return self._require_persistence().list_receiving_records(order_id)

    def create_invoice(self, order_id: str, submission: InvoiceSubmission) -> PurchaseInvoice:
        return self._require_persistence().create_invoice(order_id, submission)

    def get_invoice(self, invoice_id: str) -> PurchaseInvoice | None:
        return self._require_persistence().get_invoice(invoice_id)

    def list_invoices(self, order_id: str) -> list[PurchaseInvoice]:
        return self._require_persistence().list_invoices(order_id)

    def review_invoice(self, invoice_id: str) -> PurchaseInvoice:
        return self._require_persistence().review_invoice(invoice_id)

    def procurement_finance_summary(self) -> ProcurementFinanceSummary:
        return self._require_persistence().procurement_finance_summary()

    def procurement_overview(self) -> ProcurementOverview:
        return AnalyticsService(self._require_persistence()).overview()

    def add_wishlist_item(self, request: WishlistEntryInput) -> WishlistEntry:
        return self._require_persistence().add_wishlist_item(request)

    def list_wishlist(self, user_id: str) -> list[WishlistEntry]:
        return self._require_persistence().list_wishlist(user_id)

    def remove_wishlist_item(self, wishlist_id: str, user_id: str) -> bool:
        return self._require_persistence().remove_wishlist_item(wishlist_id, user_id)

    def create_price_watch(self, request: PriceWatchInput) -> PriceWatch:
        return self._require_persistence().create_price_watch(request)

    def list_price_watches(self, user_id: str) -> list[PriceWatch]:
        return self._require_persistence().list_price_watches(user_id)

    def update_price_watch_status(
        self, watch_id: str, user_id: str, update: PriceWatchStatusUpdate
    ) -> PriceWatch:
        return self._require_persistence().update_price_watch_status(watch_id, user_id, update)

    def evaluate_price_watches(self, user_id: str | None = None) -> PriceWatchEvaluation:
        return self._require_persistence().evaluate_price_watches(user_id)

    def list_price_watch_events(self, watch_id: str, user_id: str) -> list[PriceWatchEvent]:
        return self._require_persistence().list_price_watch_events(watch_id, user_id)

    def create_purchase_reminder(self, request: PurchaseReminderInput) -> PurchaseReminder:
        return self._require_persistence().create_purchase_reminder(request)

    def list_purchase_reminders(self, user_id: str, due_only: bool = False) -> list[PurchaseReminder]:
        return self._require_persistence().list_purchase_reminders(user_id, due_only)

    def update_purchase_reminder(
        self, reminder_id: str, user_id: str, update: PurchaseReminderUpdate
    ) -> PurchaseReminder:
        return self._require_persistence().update_purchase_reminder(reminder_id, user_id, update)

    def _require_persistence(self) -> PersistenceService:
        if self._persistence is None:
            raise RuntimeError("Persistent storage is not configured for this catalog adapter.")
        return self._persistence
