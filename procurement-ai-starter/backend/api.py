from functools import lru_cache
import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from dotenv import load_dotenv

from backend.agents.manager import ManagerAgent
from backend.agents.contractor_matching import ContractorMatchingAgent
from backend.integrations.contractors import FileContractorCatalogAdapter
from backend.integrations.catalog import SQLiteCatalogAdapter
from backend.models.purchase import (
    ApprovalDecision,
    ApprovalRecord,
    AuditEvent,
    DeliveryEvent,
    DeliveryUpdate,
    DemandForecast,
    InventoryItem,
    InvoiceSubmission,
    ProcurementFinanceSummary,
    PurchaseInvoice,
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
    Offer,
    Product,
    PurchasePlan,
    PurchaseRequest,
    PurchaseOrder,
    PurchaseOrderSummary,
    OrderDraftUpdate,
    ReplanRequest,
    ReplanResult,
    ReceivingRecord,
    ReceivingRequest,
    ReorderRecommendation,
    ReorderWorkflow,
    StoredPlanSummary,
    Supplier,
    UserContext,
)
from backend.models.contractor import (
    ContractorDemoScenarioResult,
    ContractorSearchRequest,
    ContractorSearchResult,
)
from backend.repositories.procurement import SQLiteProcurementRepository
from backend.tools.procurement import ProcurementTools
from backend.tools.contractors import ContractorTools
from backend.api_personal_extended import create_personal_router
from backend.api_analytics import router as analytics_router

load_dotenv()


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    user_context: UserContext = Field(default_factory=UserContext)


@lru_cache(maxsize=1)
def get_repository() -> SQLiteProcurementRepository:
    return SQLiteProcurementRepository()


@lru_cache(maxsize=1)
def get_manager() -> ManagerAgent:
    adapter = SQLiteCatalogAdapter(get_repository())
    return ManagerAgent(
        tools=ProcurementTools(
            adapter,
            inventory_repository=get_repository(),
            persistence_repository=get_repository(),
        ),
        use_llm_intake=os.getenv("PROCUREMENT_LLM_INTAKE", "0") == "1",
        use_agents_sdk_review=os.getenv("PROCUREMENT_AGENT_REVIEW", "0") == "1",
    )


@lru_cache(maxsize=1)
def get_contractor_agent() -> ContractorMatchingAgent:
    return ContractorMatchingAgent(ContractorTools(FileContractorCatalogAdapter()))


WEB_ROOT = Path(__file__).resolve().parents[1] / "frontend"

app = FastAPI(
    title="Procureline Demo",
    description="Offline-first procurement, contractor matching and personal shopping demo on local catalog data.",
    version="0.4.0",
)
app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
app.include_router(create_personal_router(get_repository))
app.include_router(analytics_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "local-demo"}


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/api/products", response_model=list[Product])
def list_products() -> list[Product]:
    return get_manager().tools.catalog.list_products()


@app.get("/api/products/{product_id}", response_model=Product)
def get_product(product_id: int) -> Product:
    product = get_manager().tools.catalog.product_by_id(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.get("/api/offers", response_model=list[Offer])
def list_offers(product_id: int | None = Query(default=None, gt=0)) -> list[Offer]:
    catalog = get_manager().tools.catalog
    offers = catalog.list_offers()
    if product_id is not None:
        offers = [offer for offer in offers if offer.product_id == product_id]
    return offers


@app.get("/api/suppliers", response_model=list[Supplier])
def list_suppliers() -> list[Supplier]:
    return get_manager().tools.catalog.list_suppliers()


@app.post("/api/contractors/search", response_model=ContractorSearchResult)
def search_contractors(request: ContractorSearchRequest) -> ContractorSearchResult:
    try:
        return get_contractor_agent().recommend(request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/contractors/demo-scenarios", response_model=list[ContractorDemoScenarioResult])
def contractor_demo_scenarios() -> list[ContractorDemoScenarioResult]:
    scenarios = [
        (
            "dense-autumn",
            "Плотная категория на осеннюю дату",
            ContractorSearchRequest(
                city="Алматы", event_date="2026-10-17", event_type="корпоратив", category="Ведущий",
                budget_kzt="1200000", duration_hours="4", language="русский",
            ),
        ),
        (
            "rare-category",
            "Редкая категория с частичным совпадением",
            ContractorSearchRequest(
                city="Алматы", event_date="2026-11-14", event_type="свадьба", category="Флорист",
                budget_kzt="500000", language="русский",
            ),
        ),
        (
            "no-result",
            "Кандидаты есть, но бюджет слишком низкий",
            ContractorSearchRequest(
                city="Алматы", event_date="2026-12-20", event_type="корпоратив", category="Ведущий",
                budget_kzt="1",
            ),
        ),
        (
            "calendar-date-comparison",
            "Та же заявка на другую дату",
            ContractorSearchRequest(
                city="Алматы", event_date="2026-10-18", event_type="корпоратив", category="Ведущий",
                budget_kzt="1200000", duration_hours="4", language="русский",
            ),
        ),
    ]
    try:
        agent = get_contractor_agent()
        return [
            ContractorDemoScenarioResult(
                scenario_id=scenario_id,
                title=title,
                request=request,
                result=agent.recommend(request),
            )
            for scenario_id, title, request in scenarios
        ]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/inventory", response_model=list[InventoryItem])
def list_inventory() -> list[InventoryItem]:
    return get_manager().inventory.scan()


@app.get("/api/forecast/{product_id}", response_model=DemandForecast)
def forecast_product(product_id: int) -> DemandForecast:
    item = next(
        (entry for entry in get_manager().inventory.scan() if entry.product_id == product_id),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return get_manager().forecast.forecast(item)


@app.post("/api/reorders", response_model=list[ReorderWorkflow])
def run_reorder_analysis() -> list[ReorderWorkflow]:
    manager = get_manager()
    workflows = manager.reorder_workflows()
    saved_workflows = []
    for workflow in workflows:
        saved_plan = manager.tools.save_plan(workflow.purchase_plan)
        saved_workflows.append(
            ReorderWorkflow(recommendation=workflow.recommendation, purchase_plan=saved_plan)
        )
    manager.tools.log_reorder_analysis([item.recommendation for item in saved_workflows])
    return saved_workflows


@app.get("/api/procurement/plans", response_model=list[StoredPlanSummary])
def list_plans(limit: int = Query(default=50, ge=1, le=200)) -> list[StoredPlanSummary]:
    return get_manager().tools.list_plans(limit)


@app.get("/api/procurement/plans/{plan_id}", response_model=PurchasePlan)
def get_plan(plan_id: str) -> PurchasePlan:
    plan = get_manager().tools.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@app.get("/api/audit-log", response_model=list[AuditEvent])
def list_audit_log(limit: int = Query(default=100, ge=1, le=500)) -> list[AuditEvent]:
    return get_manager().tools.list_audit_events(limit)


@app.get("/api/procurement/approvals", response_model=list[ApprovalRecord])
def list_approvals(
    status: str | None = Query(default=None, pattern="^(PENDING|APPROVED|REJECTED)$"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ApprovalRecord]:
    return get_manager().tools.list_approvals(status, limit)


@app.post("/api/procurement/approvals/{approval_id}/decision", response_model=ApprovalRecord)
def decide_approval(approval_id: str, decision: ApprovalDecision) -> ApprovalRecord:
    manager = get_manager()
    approval = manager.tools.get_approval(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    configured_role = manager.policy.policy.approver_roles.get(decision.reviewer_id)
    if configured_role is None or configured_role.casefold() != decision.reviewer_role.casefold():
        raise HTTPException(status_code=403, detail="Reviewer is not configured for the claimed role")
    try:
        return manager.tools.decide_approval(approval_id, decision)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/procurement/requests", response_model=PurchasePlan)
def create_procurement_plan(request: PurchaseRequest) -> PurchasePlan:
    plan = get_manager().plan(request)
    return get_manager().tools.save_plan(plan)


@app.post("/api/procurement/plans/{plan_id}/order", response_model=PurchaseOrder)
def create_local_order_draft(plan_id: str, update: OrderDraftUpdate) -> PurchaseOrder:
    try:
        return get_manager().tools.create_purchase_order(plan_id, update.buyer_note)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/procurement/orders", response_model=list[PurchaseOrderSummary])
def list_purchase_orders(limit: int = Query(default=100, ge=1, le=500)) -> list[PurchaseOrderSummary]:
    return get_manager().tools.list_purchase_orders(limit)


@app.get("/api/procurement/orders/{order_id}", response_model=PurchaseOrder)
def get_purchase_order(order_id: str) -> PurchaseOrder:
    order = get_manager().tools.get_purchase_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return order


@app.post("/api/procurement/orders/{order_id}/delivery-events", response_model=DeliveryEvent)
def record_delivery_event(order_id: str, update: DeliveryUpdate) -> DeliveryEvent:
    try:
        return get_manager().tools.update_delivery(order_id, update)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/procurement/orders/{order_id}/delivery-events", response_model=list[DeliveryEvent])
def list_delivery_events(order_id: str) -> list[DeliveryEvent]:
    try:
        return get_manager().tools.list_delivery_events(order_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/procurement/orders/{order_id}/receipts", response_model=list[ReceivingRecord])
def receive_purchase_order(order_id: str, request: ReceivingRequest) -> list[ReceivingRecord]:
    try:
        return get_manager().tools.receive_order(order_id, request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/procurement/orders/{order_id}/receipts", response_model=list[ReceivingRecord])
def list_receiving_records(order_id: str) -> list[ReceivingRecord]:
    try:
        return get_manager().tools.list_receiving_records(order_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/procurement/orders/{order_id}/invoices", response_model=PurchaseInvoice)
def record_purchase_invoice(order_id: str, submission: InvoiceSubmission) -> PurchaseInvoice:
    try:
        return get_manager().tools.create_invoice(order_id, submission)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Invoice number already exists for this supplier") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/procurement/orders/{order_id}/invoices", response_model=list[PurchaseInvoice])
def list_order_invoices(order_id: str) -> list[PurchaseInvoice]:
    try:
        return get_manager().tools.list_invoices(order_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/procurement/invoices/{invoice_id}", response_model=PurchaseInvoice)
def get_purchase_invoice(invoice_id: str) -> PurchaseInvoice:
    invoice = get_manager().tools.get_invoice(invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@app.post("/api/procurement/invoices/{invoice_id}/review", response_model=PurchaseInvoice)
def review_purchase_invoice(invoice_id: str) -> PurchaseInvoice:
    try:
        return get_manager().tools.review_invoice(invoice_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/procurement/analytics/finance", response_model=ProcurementFinanceSummary)
def procurement_finance_analytics() -> ProcurementFinanceSummary:
    return get_manager().tools.procurement_finance_summary()


@app.post("/api/personal/wishlist", response_model=WishlistEntry)
def add_to_wishlist(request: WishlistEntryInput) -> WishlistEntry:
    try:
        return get_manager().tools.add_wishlist_item(request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Wishlist item already exists") from exc
    except ValueError as exc:
        status = 409 if "already" in str(exc).lower() else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.get("/api/personal/wishlist", response_model=list[WishlistEntry])
def list_wishlist(user_id: str = Query(default="demo-user", min_length=1, max_length=100)) -> list[WishlistEntry]:
    return get_manager().tools.list_wishlist(user_id)


@app.delete("/api/personal/wishlist/{wishlist_id}")
def delete_wishlist_item(
    wishlist_id: str,
    user_id: str = Query(default="demo-user", min_length=1, max_length=100),
) -> dict[str, bool]:
    removed = get_manager().tools.remove_wishlist_item(wishlist_id, user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Wishlist item not found")
    return {"removed": True}


@app.post("/api/personal/price-watches", response_model=PriceWatch)
def create_price_watch(request: PriceWatchInput) -> PriceWatch:
    try:
        return get_manager().tools.create_price_watch(request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        status = 409 if "in-stock" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.get("/api/personal/price-watches", response_model=list[PriceWatch])
def list_price_watches(user_id: str = Query(default="demo-user", min_length=1, max_length=100)) -> list[PriceWatch]:
    return get_manager().tools.list_price_watches(user_id)


@app.post("/api/personal/price-watches/evaluate", response_model=PriceWatchEvaluation)
def evaluate_price_watches(
    user_id: str = Query(default="demo-user", min_length=1, max_length=100),
) -> PriceWatchEvaluation:
    return get_manager().tools.evaluate_price_watches(user_id)


@app.post("/api/personal/price-watches/{watch_id}/status", response_model=PriceWatch)
def update_price_watch_status(
    watch_id: str,
    update: PriceWatchStatusUpdate,
    user_id: str = Query(default="demo-user", min_length=1, max_length=100),
) -> PriceWatch:
    try:
        return get_manager().tools.update_price_watch_status(watch_id, user_id, update)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/personal/price-watches/{watch_id}/events", response_model=list[PriceWatchEvent])
def list_price_watch_events(
    watch_id: str,
    user_id: str = Query(default="demo-user", min_length=1, max_length=100),
) -> list[PriceWatchEvent]:
    try:
        return get_manager().tools.list_price_watch_events(watch_id, user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/personal/reminders", response_model=PurchaseReminder)
def create_purchase_reminder(request: PurchaseReminderInput) -> PurchaseReminder:
    try:
        return get_manager().tools.create_purchase_reminder(request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/personal/reminders", response_model=list[PurchaseReminder])
def list_purchase_reminders(
    user_id: str = Query(default="demo-user", min_length=1, max_length=100),
    due_only: bool = False,
) -> list[PurchaseReminder]:
    return get_manager().tools.list_purchase_reminders(user_id, due_only)


@app.post("/api/personal/reminders/{reminder_id}/status", response_model=PurchaseReminder)
def update_purchase_reminder(
    reminder_id: str,
    update: PurchaseReminderUpdate,
    user_id: str = Query(default="demo-user", min_length=1, max_length=100),
) -> PurchaseReminder:
    try:
        return get_manager().tools.update_purchase_reminder(reminder_id, user_id, update)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/procurement/orders/{order_id}/replan", response_model=ReplanResult)
def replan_order(order_id: str, request: ReplanRequest) -> ReplanResult:
    manager = get_manager()
    order = manager.tools.get_purchase_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    events = manager.tools.list_delivery_events(order_id)
    latest_by_supplier = {event.supplier_id: event for event in events}
    failed = {
        supplier_id for supplier_id, event in latest_by_supplier.items()
        if event.status in {"DELAYED", "CANCELLED"}
    }
    excluded = failed | set(request.exclude_supplier_ids)
    if not excluded:
        raise HTTPException(status_code=409, detail="Record a delayed or cancelled delivery before replanning")
    order_supplier_ids = {item.supplier_id for item in order.items}
    unknown_suppliers = excluded - order_supplier_ids
    if unknown_suppliers:
        raise HTTPException(
            status_code=422,
            detail=f"Supplier IDs are not part of this order: {', '.join(map(str, sorted(unknown_suppliers)))}",
        )
    replaced_quantity = sum(item.quantity for item in order.items if item.supplier_id in excluded)
    if replaced_quantity <= 0:
        raise HTTPException(status_code=409, detail="No order quantity is assigned to the excluded suppliers")
    original = manager.tools.get_plan(order.plan_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Source procurement plan not found")
    replacement_request = original.request.model_copy(update={"quantity": replaced_quantity})
    replacement = manager.plan(replacement_request, excluded_supplier_ids=excluded)
    replacement = manager.tools.save_plan(replacement)
    return ReplanResult(
        order_id=order_id, excluded_supplier_ids=sorted(excluded),
        replaced_quantity=replaced_quantity, replacement_plan=replacement,
    )


@app.post("/api/chat", response_model=PurchasePlan)
async def chat(request: ChatRequest) -> PurchasePlan:
    try:
        plan = await get_manager().plan_text_async(request.message, request.user_context)
        return get_manager().tools.save_plan(plan)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
