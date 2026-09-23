# Review of the local demo — 2026-09-23

This review covers the current local architecture and the added personal shopping workflows. It is a code review and focused automated verification, not a claim of production readiness. Final whole-project and browser checks are reported separately by the integration task.

## Security and scope

- The supplied `api.ps1` binds Uvicorn to `127.0.0.1`. Keep this default for the demonstration. The app has no login, authenticated roles or tenant isolation; caller-supplied `user_id` and demo reviewer identities are not security boundaries. Do not expose this configuration as a shared multi-user service.
- New personal queries use SQLite parameters and scope reads/updates by `user_id`. The router rejects missing records and invalid business input. Tests include a SQL-looking owner value, wrong-owner purchases/returns, blank preference values and invalid query parameters. This does not replace authentication.
- Preferences, purchase history and return documents are deliberately small manual records. Document fields contain labels only; no files are uploaded or fetched. Notes are user-entered data. Avoid adding credentials or sensitive details to demo notes.
- Purchase recording, bundle suggestions, repeat-buy recommendations and return drafts do not place orders, charge money, reserve supplier stock, contact a seller or submit a return. `externally_submitted` and `external_order_created` remain false.
- The OpenAI Agents SDK agents are constructed programmatically in the repository. `enable-ai.ps1` installs the SDK, accepts a newly rotated key through hidden local input and enables model-backed intake/review. Keys sent in chat were not stored or used, so live execution remains unverified; no manual OpenAI Platform agent setup is required.

## Architecture and data

- New personal routes follow `API → typed tools → service → repository`. They use the same catalog service/SQLite adapter as procurement; they do not create a separate product catalog.
- `PersonalExtendedRepository` adds `personal_preferences`, `personal_purchases` and `personal_return_drafts` to the shared database. It does not change the procurement schema version or rewrite its tables. Tests verify that catalog contents and the existing schema version survive initialization/reopening.
- Preference, purchase and return changes append to the shared audit log. Return quantity checks and cancellation use transactions; simultaneous active local drafts cannot exceed the recorded purchased quantity.
- Money uses `Decimal`. Recorded purchase prices are explicitly manual data and can differ from current offers. Actual timezone offsets are preserved, and history sorts by aware timestamps; return date checks use the recorded purchase calendar date.

## Correctness and error handling

- Personal repeat buying uses the latest recorded purchase and its explicitly configured cycle. It returns a due/scheduled recommendation and an available local offer when present. Missing offers produce an unknown price, without creating an order or sending a notification.
- Compatibility checks compare interface, form factor, length, available power and socket only when the necessary values are available. Missing facts return `UNKNOWN`; a known failed condition returns `INCOMPATIBLE`. `COMPATIBLE` is scoped to the requested checks and supplied inputs, not manufacturer certification. Catalog interface values cannot be overridden with contradictory input.
- Bundle selection respects item quantities, minimum order sizes, currency, requested minimum specs, shared offer stock and the budget. The combined power requirement includes component quantities. Unknown compatibility yields `REVIEW_REQUIRED`; budget excess or confirmed incompatibility yields `BLOCKED`.
- A multi-item basket without enough host specifications remains `UNKNOWN`, including baskets of independent items. This conservative behavior is visible to the user.
- Return drafts require a saved purchase owned by the supplied user. No store policy is invented. A deadline is accepted only with a user-provided source; the result describes comparison with that date and does not assert a legal right to return.
- Invalid business data returns 422; missing referenced records return 404. Underlying filesystem/database failures can still produce a server error. Deployment-level recovery, monitoring, rate limits and authentication are outside the local demo configuration.

## Performance

- Catalog and owner lookups are appropriate for the current small demo data. New owner-history and return-list indexes are present. Personal history lists remain unpaginated, which is suitable for a local demonstration rather than an unbounded production account.
- Bundle search supports at most eight requested lines, uses deterministic price ordering and a lower-bound pruning calculation, and caps exploration at 100,000 nodes. Excessively broad searches return a controlled validation error asking for narrower queries/product IDs; no approximate result is presented as the optimum.
- Compatibility, bundle selection and personal recommendations do not call a model or external API. Persistent workflow actions use short SQLite transactions. No background polling or scheduler is added by these modules.

## Focused verification

`python -m unittest discover -s tests -p test_personal_extended.py -v` passes 11 tests, including a FastAPI TestClient workflow. Coverage includes persistence and owner scoping, validation, repeat cycles, known/unknown compatibility, budget and shared stock, combined power, timezone ordering, return policy uncertainty and draft quantity protection. The final integration run should include this file with the existing suite.

Two defects found during review were corrected: bundle power had initially been checked per component without summing quantities; purchase timestamps had initially been normalized to UTC, which could alter the original calendar date used by a return deadline.
