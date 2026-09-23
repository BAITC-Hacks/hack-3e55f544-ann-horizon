# Changelog

## Final completion — 2026-09-23

- Added responsive local B2B UI for catalog, inventory, forecast/reorder, saved plans/approvals, local orders, manual delivery, partial receiving, invoice reconciliation, audit and finance/operations analytics.
- Added personal preferences and purchase memory, cycle-based reorder suggestions, deterministic known/unknown compatibility checks, budget-aware bundles and local return drafts.
- Added 84 synthetic historical price observations and a 90-day median anomaly analysis; expanded the linked catalog to 10 products, 5 suppliers and 21 offers. An explicit importer preserved existing prices and inventory.
- Improved exact catalog search for named/SKU requests and added new-category Russian quantity parsing.
- Added overview analytics, plan detail and a corrected partial-receiving transition for split supplier deliveries.
- Added Docker/Compose and run instructions. Images were not built in this environment.
- Final offline suite result and browser flow are recorded in `README.md`; see `FINAL_REVIEW.md` for scope and remaining limitations.

## Phase 1 — Core MVP

Implemented:

- Offline Manager Agent and intake for Russian/English procurement requests.
- Typed purchase request, user context, product, supplier, offer, pricing, plan and validation models.
- Catalog repository and replaceable adapter with linked, explicitly marked DEMO sample products and offers.
- Search, product matching, supplier evidence, exact Decimal pricing, weighted allocation and deterministic plan validation.
- Multi-supplier B2B purchase plan, API endpoints and Windows CLI/API launch scripts.
- Optional structured intake through OpenAI Agents SDK; network/model calls are opt-in.

Tests:

- 13 `unittest` cases pass against local sample data.
- CLI demo completes successfully.
- FastAPI HTTP smoke check: product list and procurement chat both return 200; chat returns 300 units and 7,340,000 KZT.

Known limitations:

- Demo data only; shipping and taxes are absent and excluded from totals.
- Supplier delivery/defect/return history is unavailable.
- No database, approval workflow, order execution, inventory forecasting, finance or frontend.

Next:

- Phase 2 — database persistence and procurement entities.

## Phase 2 — Database

Implemented:

- Versioned SQLite schema for products, suppliers, offers, inventory, demand history, procurement plans, purchase orders/items, purchase history and audit log.
- One-time validated seed from the linked `DEMO DATA` JSON catalog, including inventory whose available quantity is `on_hand - reserved`.
- SQLite catalog adapter; FastAPI uses it for products, suppliers and offers.
- Procurement API persists both ready and blocked plans with an audit event. The source text is omitted from persisted plan JSON.
- Read endpoints for inventory, saved plans and audit events.

Tests:

- 14 `unittest` cases pass, including SQLite seed/reference integrity, plan persistence, audit logging and a check that no purchase order is created.
- Windows setup and CLI launch scripts run. API HTTP smoke check returned 200 for products, inventory, chat, saved plans and audit log.

Known limitations:

- Inventory rows and purchase history are sample/schema data; the procurement workflow does not reserve or decrement stock.
- Order and purchase history tables are prepared for later phases and remain empty.
- The local API has no authentication or tenant isolation.

Next:

- Phase 3 — inventory thresholds, demand forecast and reorder recommendation.

## Phase 3 — Inventory, forecast and reorder

Implemented:

- Four-month synthetic monthly demand history for linked demo products; seed runs only when all catalog products are marked `DEMO DATA` and history is empty.
- Moving-average demand forecast, average daily demand and supplier lead-time demand calculation.
- Inventory Agent, Demand Forecast Agent and Automatic Reorder Agent.
- `GET /api/forecast/{product_id}` and `POST /api/reorders`.
- Reorder run creates and stores validated purchase-plan drafts plus audit events. It does not reserve stock, create an order or contact a supplier.

Tests:

- 15 `unittest` cases pass, including moving average, reorder quantity, missing-history behavior, workflow generation and unchanged stock.

Known limitations:

- Forecast history and stock are synthetic demo data. Missing history is not fabricated for non-demo catalogs.
- Human approval and order execution remain later phases.

Next:

- Phase 4 — evidence-based risk, configurable compliance and human approval.

## Phase 4 — Risk, compliance, approval and code-defined Agents SDK

Implemented:

- Evidence-backed risk assessments for supplier history, delivery limits, missing price history, availability and supplier concentration. Missing evidence is reported as unknown.
- Typed, configurable policy from `data/procurement_policy.json`: minimum supplier quotes, supplier allowlist, blocked categories, currency budget limits, approval thresholds and reviewer-role mapping.
- Approval records are persisted in SQLite. Plans above the configured approval threshold start pending; decisions enforce configured role matching and prevent requester self-approval.
- API endpoints for listing approvals and submitting decisions. Approval requests/decisions are written to the audit log; no order is created.
- SQLite schema version 2 migration adds approval records and plan approval status.
- OpenAI Agents SDK Intake, Manager and 12 specialist reviewer agents are constructed programmatically in `backend/integrations/agents_sdk.py`. Manager exposes specialists with the current `Agent.as_tool()` pattern. LLM plan review is opt-in and returns only a narrative `ai_summary`; deterministic plan fields remain unchanged.
- No manual agent creation or configuration in OpenAI Platform.

Tests:

- 18 `unittest` cases pass, including SDK agent construction without network calls, plan review opt-in, approval role checks, self-approval rejection, SQLite migration/persistence and API workflow.
- HTTP smoke check returned 200 for plan creation, pending approvals and approval decision; the plan remained a draft at 7,340,000 KZT.

Known limitations:

- Seed catalog, prices, inventory and supplier data remain synthetic demo data.
- Approver IDs are sample configuration values; this local API has no authenticated identity or tenant isolation.
- Live model execution was not checked because no `OPENAI_API_KEY` is configured.
- Approval records do not trigger order execution.

Next at Phase 4 completion:

- Phase 5 — draft purchase orders, delivery events, replanning and receiving workflows.

## Smart Contractor Matching — Firebird

Implemented:

- Deterministic event-contractor matching for city, event date/type, category, KZT budget and optional duration/language; returns no more than three ranked cards with profile-specific explanations.
- Uploaded anonymized CSV is retained at `data/hackathon-dataset-anonymized.csv`: 66 profiles total, 13 marked synthetic. Source flags for synthetic profiles and imputed city/prices are preserved and surfaced.
- Date availability is filtered using the supplied calendar (2026-09-23 through 2026-12-31). Outcomes distinguish a missing category in a city from existing candidates that fail constraints.
- API routes: `POST /api/contractors/search` and `GET /api/contractors/demo-scenarios`. Demo coverage includes a dense autumn category, rare category, no-result case and a two-date comparison.
- Recommendations only; there is no booking, inquiry or notification flow.

Tests and verification:

- Contractor scenarios are covered by six deterministic tests.
- Live HTTP smoke returned 200 and three explained cards for the dense scenario; all four demo scenarios returned expected match counts/outcomes.

## Phase 5 — Local orders, delivery and receiving

Implemented:

- SQLite schema version 3 migrates schema v1/v2 order tables with draft metadata and adds delivery-event and receiving-record history.
- A ready, approved or approval-pending procurement plan can create a local order draft; approval state gates shipment status updates. `external_order_created` remains false.
- Manual supplier status/ETA/tracking events are validated against transition order, retained as history and audited. Delivery completion is aggregated across each order's suppliers.
- A delayed or cancelled supplier can trigger a replacement plan for only that supplier's allocated quantity. That supplier is filtered out; other suppliers’ allocated quantities remain outside the replacement request.
- Manual receiving records received and damaged counts. A partially delayed order can receive lines from suppliers marked `DELIVERED`; only accepted quantities increase local on-hand inventory and purchase history. Full receiving events are audited.
- Routes cover order draft/list/detail, delivery events, receipt recording/listing and replanning.

Tests and verification:

- Full offline suite: 27 `unittest` cases pass, including migration from schema v1/v2, contractor ranking and the order→approval→delivery→replan→receiving workflow.
- Live HTTP smoke completed a 300-unit plan, finance approval, local draft, delayed-supplier replan, delivery updates and goods receipt. The final order status was `RECEIVED`; no external order was created.

Known limitations:

- Delivery facts are manual operator input; no supplier, carrier, booking, email or notification connection is configured.
- Inventory updates at receiving are local records and do not reserve stock when a plan or order draft is created.
- Added `enable-ai.ps1` to install Agents SDK and configure model-backed intake/review using hidden local key entry. Keys sent in chat were not used; live model execution remains unverified until a newly rotated key is configured locally.

Next:

- Phase 6 — invoices/finance and further workflow hardening; frontend and B2C price watch remain future scope.

## Phase 6 — Invoice reconciliation and procurement analytics

Implemented:

- SQLite schema version 4 migrates versions 1–3 and stores invoice headers and line mappings.
- Manual invoice entry verifies that supplier/order-line references belong to the selected local order and rejects duplicate invoice numbers for a supplier.
- Deterministic three-way matching checks invoice quantity and unit price against the order and manual receiving records, then checks subtotal and total arithmetic. Unreceived quantities remain `PENDING_RECEIVING`; mismatches become `VARIANCE`; clean invoices become `MATCHED`.
- Pending invoices can be reviewed again after receiving. Each entry and review is audited. Payment state is read-only `NOT_PAID`; no payment action exists.
- Finance summary groups order subtotals and invoice totals by currency and supplier, with invoice status counts and received/accepted/damaged unit counts.
- Routes: invoice create/list/detail/review and `GET /api/procurement/analytics/finance`.

Tests and verification:

- The 28-test offline suite covers invoice pending→matched, price variance, duplicate prevention, finance totals, and schema v1/v2 migration to v4.
- Live HTTP verification completed an order-to-receipt walkthrough in Phase 5; this phase's invoice/summary repository workflow is covered by isolated SQLite tests.

Known limitations:

- Invoices are manually entered; no OCR, electronic invoice provider or accounting ledger is connected.
- Tax/shipping values are taken from the entered invoice and checked arithmetically only. No tax calculation, currency conversion or payment execution is provided.

Next:

- Phase 7 — B2C wishlist and price watch, followed by frontend and production hardening.

## Phase 7 — B2C wishlist, local price watch and reminders

Implemented:

- SQLite schema version 5 adds per-user wishlist entries, price watches, persisted price-change events and purchase reminders; earlier schemas migrate forward.
- Wishlist entries validate product/offer ownership and currency, prevent duplicate product/offer entries per `user_id`, and show the latest available local demo price.
- Price watches take an initial local offer snapshot and can be manually evaluated against current SQLite demo offers. Price drops and target-price hits are stored as events and audited.
- Timezone-aware reminders support a catalog product or free-text product query, quantity, due-state calculation on read, and completion/cancellation.
- FastAPI routes expose create/list/delete wishlist, create/list/status/events/evaluate price watches, and create/list/close reminders.

Limitations:

- Price checks are manual against the local demo catalog. No marketplace feed, background scheduler, push/email notification or authentication/tenant isolation is connected.
- This phase was not covered by a new automated test run; the existing 28-test suite predates these endpoints.

Next:

- Build and validate the local web interface, then harden authentication, tenant isolation and production integrations.

## Phase 8 — Local web interface

Implemented:

- FastAPI serves a responsive Russian-language interface at `/`; static assets are local and require no separate frontend build or third-party runtime dependency.
- Procurement form sends a request to the existing chat planner and shows line-level quantities, suppliers, prices, findings, a clearly labeled demo approval action and local draft creation.
- Firebird contractor search captures city, date, event format, category, budget, duration and language, then displays up to three explained cards with source/imputation flags.
- Personal-shopping screens support wishlist entry/removal, price-watch creation/manual evaluation/history/status and timezone-aware reminder completion/cancellation.
- The UI labels catalog and user identity as demo data. It does not create supplier orders, contractor bookings, payment actions or outbound notifications.

Limitations:

- The frontend has not had browser/runtime verification. It uses a fixed `demo-user`; authentication and tenant isolation remain future hardening work.

