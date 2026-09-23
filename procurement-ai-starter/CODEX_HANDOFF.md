# Project handoff

The local B2B/B2C/Firebird demo is implemented. Read `PROJECT_AUDIT.md`, `README.md`, `CHANGELOG.md`, and `FINAL_REVIEW.md`.

The local procurement demo is offline-first. Agents are defined programmatically in this project through the OpenAI Agents SDK when enabled; no manual OpenAI Platform setup is used. Procurement amounts, policy, invoice reconciliation and workflow state remain deterministic.

The anonymized contractor CSV is at `data/hackathon-dataset-anonymized.csv`; Smart Contractor Matching is recommendation-only. Order, delivery, receiving and invoice inputs are local/manual; no external order, contractor booking, accounting or payment action is performed.

The expanded sample catalog has 10 products, 5 suppliers, 21 offers and 84 synthetic price observations. The existing `data/procurement.db` was expanded additively and its earlier prices and stock were preserved.

A Russian-language local web interface is served from `/`; its procurement, Firebird, B2C and B2B workflows were checked in a browser. The offline test count and final review are recorded in `PROJECT_AUDIT.md` and `FINAL_REVIEW.md`.

This is not a multi-user production deployment: reviewer and user IDs are demo values, and authentication/tenant isolation are absent. A live Agents SDK model call requires a newly rotated `OPENAI_API_KEY`; configure it locally with `enable-ai.ps1`. Keys sent in chat were not stored or used. Docker files are included but no container build was run.
