# Project audit

## Final status — 2026-09-23

This file retains the dated checkpoints below; their counts/status statements describe the code at those checkpoints. At final completion the local B2B/B2C/Firebird demo includes 10 products, 5 suppliers, 21 offers, 84 synthetic price observations and the 66-row supplied Firebird dataset. The completed UI covers procurement, contractor matching, wishlist/price/reminders/personal history, bundles/compatibility/returns, catalog, inventory/forecast/reorder, plans/approvals, orders/delivery/receiving/invoices, audit and analytics. Final run: `python -m unittest discover -s tests -v` — 65 passed.

The existing local SQLite database was updated through the explicit additive demo-catalog importer (4 products, 2 suppliers, 12 offers); previous entries, prices and stock were retained. Current automated test totals and browser walkthrough are documented in `README.md`. `enable-ai.ps1` now installs the SDK and accepts a newly rotated key through hidden local PowerShell input, then enables API intake and reviewer runs. Keys posted in chat were not stored or used, so a live model call remains unverified until a new key is configured locally.

## Scope

The supplied archive was extracted to `C:\Hahaton\procurement-ai-starter`. This audit records the starter as found before Phase 1 changes. It is a small Python-only starter; there is no Git repository in the archive and no frontend.

## Architecture and existing components

- `backend/run_agent.py` loads `.env`, builds an OpenAI Agents SDK agent and runs a hard-coded laptop request.
- `backend/agents/manager.py` defines one Manager Agent with three tools: product search, budget check and delivery check.
- `backend/tools/procurement.py` reads JSON files directly at import time and contains the three tool implementations. There is no repository or service layer.
- `backend/models/purchase.py` contains Pydantic request, offer and plan models. The plan has no allocation lines or deterministic validation.
- `backend/api.py` exposes only `/` and `/health`; there is no procurement endpoint.
- `data/` contains 3 laptop products, 3 suppliers and 4 offers. Supplier records contain demo reliability/rating values, but no delivery or defect history. There are no SSDs, inventory, orders or historical prices.
- `tests/` contains instructions only; there are no executable tests.
- `requirements.txt` lists OpenAI Agents SDK, FastAPI, Uvicorn, Pydantic, dotenv, pandas and OR-Tools. No package versions are pinned.
- Windows setup and run scripts are present. README describes a key-dependent agent and correctly says it does not place orders.

## Baseline checks

- Python 3.14.2 and Node.js 24.19.0 are available. There is no frontend to run.
- No `.venv`, `.env`, or `OPENAI_API_KEY` is present.
- No listed Python dependencies are installed in the active interpreter.
- `python -m pytest -q` cannot run because pytest is absent. `python -m unittest discover -v` discovers 0 tests.
- `python backend/run_agent.py` fails immediately because `python-dotenv` is absent. The FastAPI app cannot be imported because FastAPI is absent.
- No existing runnable test suite or local database was found.

## Gaps and risks

- The starter does not deliver a complete procurement workflow and is coupled to an external LLM and API key even for the demo.
- Tools bypass services and repositories, and JSON is parsed globally at module import time.
- Search only finds exact substring matches in product name/category; it does not extract a request, compare required specs, allocate across suppliers, or validate a plan.
- Current samples cover laptops only. The example SSD workflow cannot be demonstrated from the supplied catalog.
- Supplier reliability fields are synthetic sample values, not evidence of delivery history. The app must label them as demo data and must not imply verified supplier history.
- Prices have no shipping/tax fields. Totals must be described as merchandise subtotals; shipping and tax are unknown and excluded.
- A generated plan must remain a recommendation/draft. This starter has no approval, order, payment or external supplier integration.

## Phase plan

### Phase 0 — Audit

Completed by this document. No existing tests or runnable baseline behavior were available to preserve.

### Phase 1 — Core MVP (completed)

1. Keep the existing Python/FastAPI shape and add a deterministic offline workflow that does not require an API key.
2. Add typed request/context and purchase-plan models, plus a Russian/English intake parser for product, quantity, budget, currency, required specs and delivery limit.
3. Add JSON repositories and catalog/search services behind adapter interfaces; keep the sample data explicitly marked DEMO.
4. Implement product matching, supplier evidence reporting, exact Decimal price calculations, weighted allocation across offers, and deterministic plan validation.
5. Orchestrate only relevant steps through a Manager Agent and expose read/search and procurement-plan API endpoints plus a local CLI demo.
6. Add focused automated tests for parsing, search/matching, exact totals, multi-supplier allocation, hard constraints, validation, and an end-to-end B2B scenario.
7. Update README and maintain a `CHANGELOG.md` phase entry. Do not implement database persistence, approvals, orders, inventory forecasting, finance or a frontend in this phase.

### Next phases

- Phase 2: database persistence and procurement entities.
- Later: inventory/forecast, risk/compliance/approvals, ordering/delivery, finance, B2C, frontend and hardening.

## Phase 1 result

- Current flow: FastAPI → Manager Agent → intake/search/matching/supplier/pricing/optimization/validator agents → typed tools → services → catalog repository → replaceable adapter → local JSON.
- The sample catalog now has 6 linked products, 3 suppliers and 9 offers. SSD 1TB data supports a complete quantity-split scenario. All sample fields remain `DEMO DATA`.
- Core runtime dependencies installed in `.venv`: Python 3.14.2, FastAPI 0.141.1, Pydantic 2.13.5 and Uvicorn 0.53.0.
- 13 `unittest` cases pass. CLI demo succeeds. HTTP checks for `GET /api/products` and `POST /api/chat` both returned 200 with the expected 300 units and 7,340,000 KZT merchandise subtotal.
- Optional OpenAI Agents SDK intake is isolated in `requirements-ai.txt` and disabled by default. It extracts request fields only; pricing, optimization and validation are deterministic.
- Remaining limits are intentional next-phase work: no database, real supplier history, shipping/tax quotes, approval service, order execution, finance, inventory forecasting or frontend.

## Technology decisions

Retain Python, FastAPI, Pydantic and the existing JSON sample catalog. Use `Decimal` for money. Separate repositories, services, tools/agents and API boundaries. The local sample adapter is replaceable; external APIs, real suppliers, order execution and payments remain out of scope.

## Phase 2 result

- SQLite schema version 1 now contains products, suppliers, offers, inventory, demand history, procurement plans, purchase orders/items, purchase history and audit log.
- `SQLiteCatalogAdapter` loads the linked sample data into SQLite once. API requests read the database; each chat or structured procurement request stores the result as a plan and appends an audit event.
- Inventory GET is read-only. Seed SSD inventory has 42 on hand, 10 reserved and 32 available. Orders and purchase history remain empty; plans do not reserve or change stock.
- The API smoke scenario returned 6 products, the SSD inventory row, a ready 300-unit plan for 7,340,000 KZT, one saved plan and a `procurement_plan_created` audit event.
- 14 automated tests pass, including SQLite integrity and persistence checks.
- Next: Phase 3 demand history, forecasting and reorder recommendations.

## Phase 3 result

- The existing SQLite `demand_history` table seeds four months of linked synthetic data only for a fully demo catalog with no history.
- Forecast uses the latest four monthly periods. The SSD 1TB sample averages 34 units/month; at 32 available, reorder point 50 and 3-day lead time, it recommends 22 units.
- `POST /api/reorders` builds and stores validated review plans for the affected products and writes audit events. It does not reserve/decrement inventory or create a purchase order.
- 15 `unittest` cases pass, including missing-history handling and reorder workflow generation.
- Next: Phase 4 evidence-based risk, compliance and human approval.

## Updated audit status — 2026-09-23

This status update follows implementation of Phases 1–3 and rechecks the current code before Phase 4. Historical baseline findings and per-phase results above describe their respective points in time.

### Current architecture

- FastAPI API → local `ManagerAgent` orchestrator → focused Python workflow agents → typed procurement tools → services → SQLite repositories/adapters. The JSON catalog remains linked demo seed data.
- The deterministic local path covers intake, catalog search, product matching, supplier evidence, exact Decimal price analysis, allocation, validation, inventory scan, moving-average forecast and reorder-plan drafts.
- SQLite schema v1 covers catalog, inventory, demand history, plans, purchase orders/items, purchase history and audit events. The current workflows do not create orders or mutate inventory.
- The API exposes health, catalog, inventory, forecast, reorder analysis, procurement plan/chat, saved plan and audit-log routes. The local demo has no authentication or tenant isolation.
- Demo fixtures are synthetic and linked, but smaller than the brief's suggested 10–30 products, 5–10 suppliers and 20+ offers. Supplier execution, price history, incoming stock, payment terms, shipping/tax quotes and real external adapters are not available.

### Agents SDK finding and implementation constraint

- Before this update, `backend/integrations/llm_intake.py` constructed one `Agent` in code and ran it through `Runner`; this optional structured intake was the only Agents SDK runtime integration. The domain workflow agents were regular deterministic Python classes, not SDK `Agent` instances.
- The SDK remains an optional dependency in `requirements-ai.txt`; the local demo works without it or an API key. No configured or manually-created OpenAI Platform agents are part of the project.
- User requirement for subsequent implementation: define and instantiate any SDK agents programmatically inside this repository using the current OpenAI Agents SDK. No manual agent setup in OpenAI Platform. Keep arithmetic, policy checks, allocation, state changes and validation deterministic in tools/services; SDK calls are optional and require `OPENAI_API_KEY`.

### Phase 4 status at audit handoff

- At this handoff point Phase 4 had only the initial risk, compliance and approval DTOs; its completed implementation is recorded below.
- Current automated baseline at handoff: 15 `unittest` cases passed after Phase 3. A live model call had not been verified because no API key was configured; this was not required for offline workflows.

## Phase 4 result — risk, compliance, approval and Agents SDK

- Deterministic Risk, Compliance and Approval agents are wired to services. Price risk is unknown without price history; supplier history is not inferred from demo ratings.
- Configurable business policy is loaded from `data/procurement_policy.json`; configured checks include quote count, supplier allowlist, blocked categories, a KZT budget ceiling, approval thresholds and reviewer-role mapping.
- SQLite schema v2 migrates existing v1 databases, stores approval records, updates plan summaries and logs decisions. API now supports listing pending/decided approvals and recording decisions. Role allowlist and requester self-approval checks are implemented; identity is still unauthenticated in this local demo.
- `backend/integrations/agents_sdk.py` constructs the Intake Agent, Manager Agent and 12 specialist reviewer agents in project code. The Manager exposes specialists through the current Agents SDK `Agent.as_tool()` API. No manual OpenAI Platform agent setup is used. SDK intake and plan review are opt-in; only the narrative `ai_summary` can come from the model.
- Agents SDK version 0.22.3 was installed in the project virtual environment to verify the constructors and current `Agent.as_tool()` call shape. No API key was configured, so no live model run was made.
- 18 `unittest` cases pass, including programmatic SDK construction, offline behavior, approval decisions and persistence.
- HTTP smoke checks returned 200 for `POST /api/chat`, `GET /api/procurement/approvals?status=PENDING` and `POST /api/procurement/approvals/{approval_id}/decision`; the demo SSD plan stayed `READY_FOR_REVIEW` at 7,340,000 KZT while its approval moved to `APPROVED`.
- Next: Phase 5 draft purchase orders, delivery/replanning and receiving.

## Added requirement — Smart Contractor Matching (Firebird)

- The user supplied the anonymized CSV and HTML preview after the initial audit. The project copy `data/hackathon-dataset-anonymized.csv` has the same SHA-256 as the supplied CSV; the HTML file was used as a preview reference and is not needed at runtime.
- Source CSV contains 66 contractor profiles: 13 have `synthetic=true`; the remaining source rows and all `city_imputed` / `price_imputed` flags are preserved. City counts are Almaty 50, Astana 15 and Abroad 1. The data source is therefore marked as anonymized source plus synthetic records, not as fully real-world verified inventory.
- `ContractorMatchingService` ranks deterministically and returns at most three cards from city, event date, format, category, budget and optional duration/language. It excludes busy dates within the supplied 2026-09-23 through 2026-12-31 calendar and explains price headroom, supported request fields and profile description.
- API: `POST /api/contractors/search`, `GET /api/contractors/demo-scenarios`. Outcomes differentiate category absent from candidates that exist but fail filters. The service is recommendation-only; it does not book, contact or notify contractors.
- Six focused tests cover dataset flags/counts, repeatability, explanations, date changes, sparse/no-match outcomes, date bounds and demo scenarios. Live HTTP returned three explained cards and all four scenario outcomes matched expectations.

## Phase 5 result — local order, delivery and receiving workflow

- SQLite schema version 3 migrates the earlier purchase-order tables, adds local draft metadata and persists manual delivery events and receiving records.
- Approved or approval-pending procurement plans can be converted into a local draft with copied line quantities/prices. Approval moves a pending draft to `APPROVED` or `CANCELLED`; no code path creates an external supplier order.
- Delivery status transitions are validated per supplier and aggregated to the local order. Events require manual input and are included in the audit log.
- Replanning uses the existing procurement request and excludes delayed/cancelled suppliers, targeting only the quantity allocated to those suppliers. If remaining catalog offers cannot cover it, the replacement plan reports `BLOCKED` and its available quantity.
- Receiving records actual, damaged and accepted quantities. On partially delayed orders, lines from suppliers marked `DELIVERED` can be received while delayed lines remain unavailable. Accepted units update local on-hand inventory and purchase history; damaged units are retained in receiving/audit records.
- API now includes order draft/list/detail, delivery-event, receiving and replan routes; see `README.md` for request examples.
- Full offline suite: 27 `unittest` cases passed, including a schema v2→v3 migration. A live HTTP walkthrough completed plan creation, finance approval, local order, delivery updates, delayed-supplier replan and goods receipt; the final order status was `RECEIVED` and `external_order_created` stayed false.

## Phase 6 result — invoice reconciliation and procurement finance

- SQLite schema version 4 migrates schemas v1–v3 and adds invoice headers and line mappings.
- Manual invoice entry is limited to suppliers and order items on a local order already marked ordered/in transit/delivered. Duplicate invoice numbers are rejected per supplier (case-insensitive).
- `InvoiceReconciliationService` performs deterministic three-way checks across local order, invoice and manual receiving: supplier/line reference, quantity, unit price, currency, line subtotal, tax+shipping total, received quantity and accepted quantity. Unreceived amounts remain `PENDING_RECEIVING`; mismatches are `VARIANCE`; only clean rows become `MATCHED`.
- Pending invoices can be re-reviewed after receiving; findings and both recording/review actions are persisted and audited. Payment state is always `NOT_PAID`.
- `GET /api/procurement/analytics/finance` reports order line subtotals, invoice totals by currency/supplier and reconciliation status, plus received/accepted/damaged units. Values are not converted across currencies and matched does not mean paid.
- Full offline suite now has 28 tests, including v1/v2 migration to v4, pending→matched invoice review after receiving, price variance, duplicate invoice protection and finance aggregation.
- No OCR, tax-rule engine, accounting export, payment execution or live financial integration is configured.

## Phase 7 result — B2C wishlist, local price watch and reminders

- SQLite schema version 5 adds wishlist, price-watch/event and reminder storage and migrates older local databases on startup.
- Wishlist supports per-`user_id` product or offer entries, duplicate prevention and current price from the local offer catalog.
- Manual price-watch evaluation creates persisted/audited `PRICE_DROP` and `TARGET_REACHED` events. It reads only local SQLite offers and has no background job or external feed.
- Timezone-aware reminders are stored locally; `DUE` is computed on read and reminders can be completed or cancelled. No notification is sent.
- API routes are listed in `README.md`; `user_id` remains caller-provided and is not authenticated.
- The prior 28-test suite predates this phase. No new B2C tests or Phase 7 runtime walkthrough were performed.

## Current status

- The supplied contractor dataset and Smart Contractor Matching plus procurement Phases 1–7 are implemented in the local demo.
- Manual delivery, receiving, invoices, wishlist, price checks and reminders use local/manual data. There is no external order execution, booking, OCR/accounting/payment, live marketplace feed, notification scheduler, authentication or tenant isolation.
- OpenAI Agents SDK agents are created programmatically inside this project; no manual OpenAI Platform configuration is used. Live model execution remains unverified without `OPENAI_API_KEY`.
- The 28-test result predates Phase 7; the updated migration expectation and new B2C API are not yet verified by a test run.
- The responsive local web interface is now implemented; next work is browser/runtime verification and production hardening.

## Phase 8 result — local web interface

- Added a responsive Russian-language frontend served from `/` and same-origin static assets under `/static`; no separate frontend build or third-party JavaScript dependency is required.
- The UI connects the B2B/B2C procurement planner, demo approval/local draft actions, Smart Contractor Matching Firebird, wishlist, price-watch events and reminders to their existing API routes.
- The procurement screen can save a local draft from a generated plan. Contractor results preserve source/imputation labels and show explanations.
- The frontend uses a fixed `demo-user`; no login or tenant isolation is implemented. Browser/runtime verification has not been performed.

