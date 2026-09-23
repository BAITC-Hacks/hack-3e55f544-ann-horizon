"""Programmatic OpenAI Agents SDK definitions for optional language tasks.

No agent configuration is created or managed in OpenAI Platform. The project
constructs the agents below at runtime with the Agents SDK.
"""

import json
import os
from dataclasses import dataclass
from typing import Any

from backend.integrations.llm_intake import IntakeExtraction
from backend.models.purchase import PurchasePlan


@dataclass(frozen=True)
class ProcurementAgentSet:
    intake: Any
    manager: Any
    specialists: dict[str, Any]


def _model_option() -> dict[str, str]:
    model = os.getenv("PROCUREMENT_MODEL")
    return {"model": model} if model else {}


def build_intake_agent() -> Any:
    """Construct the structured intake Agent entirely in project code."""
    try:
        from agents import Agent
    except ImportError as exc:
        raise RuntimeError(
            "Agents SDK is not installed. Install the optional requirements-ai.txt dependencies."
        ) from exc
    return Agent(
        name="Procurement Intake Agent",
        instructions=(
            "Extract only requirements stated by the user into the structured output. "
            "Do not invent budgets, deadlines, brands, specifications, suppliers, catalog facts, or prices. "
            "Use quantity 1 only when no quantity is stated. Preserve the distinction between unit and total budget. "
            "Use the supplied context currency when no currency is stated. Storage and RAM are minimums."
        ),
        output_type=IntakeExtraction,
        **_model_option(),
    )


_SPECIALIST_INSTRUCTIONS = {
    "search": (
        "Catalog Search Reviewer. Summarize only catalog records included in the input. "
        "Do not claim a live marketplace search or invent a result."
    ),
    "product_matching": (
        "Product Matching Reviewer. Explain the deterministic match results and unmet hard specifications "
        "from the input. Do not override the recorded match or invent compatibility."
    ),
    "supplier": (
        "Supplier Evidence Reviewer. Distinguish verified history from synthetic demo fields and missing data. "
        "Never infer supplier reliability without evidence in the input."
    ),
    "pricing": (
        "Pricing Reviewer. Describe only the supplied exact calculations. Do not recompute or invent prices, "
        "discounts, taxes, or shipping."
    ),
    "delivery": (
        "Delivery Reviewer. Describe only offer lead times and limits included in the input. "
        "Do not imply an actual shipment or guaranteed ETA."
    ),
    "inventory": (
        "Inventory Reviewer. Explain recorded on-hand, reserved, available, and reorder values. "
        "Do not claim stock was reserved or changed."
    ),
    "forecast": (
        "Demand Forecast Reviewer. Explain the supplied deterministic forecast and its data source. "
        "Do not invent periods or demand values."
    ),
    "optimization": (
        "Optimization Reviewer. Explain the supplied allocation and hard-constraint result. "
        "Do not change allocation quantities or amounts."
    ),
    "risk": (
        "Risk Reviewer. Explain each supplied risk, severity, reason, and evidence. "
        "Keep unknown risks unknown; do not add unsupported risk claims."
    ),
    "compliance": (
        "Compliance Reviewer. Explain the supplied policy findings and statuses. "
        "Do not waive, invent, or change a policy result."
    ),
    "validator": (
        "Validation Reviewer. Explain deterministic validation findings as given. "
        "Never replace arithmetic or validation with your own calculation."
    ),
    "approval": (
        "Approval Reviewer. Explain whether a human decision is pending and which configured role is required. "
        "Never approve, reject, create an order, or claim a decision was made."
    ),
}


def build_procurement_agent_set() -> ProcurementAgentSet:
    """Construct specialist Agents and a manager that invokes them as tools."""
    try:
        from agents import Agent
    except ImportError as exc:
        raise RuntimeError(
            "Agents SDK is not installed. Install the optional requirements-ai.txt dependencies."
        ) from exc

    options = _model_option()
    specialists = {
        key: Agent(
            name=f"Procurement {key.replace('_', ' ').title()} Agent",
            instructions=instructions,
            **options,
        )
        for key, instructions in _SPECIALIST_INSTRUCTIONS.items()
    }
    tools = [
        specialist.as_tool(
            tool_name=f"review_{key}",
            tool_description=f"Explain the already computed {key.replace('_', ' ')} evidence from the supplied plan.",
        )
        for key, specialist in specialists.items()
    ]
    manager = Agent(
        name="Procurement Manager Agent",
        instructions=(
            "Explain the validated procurement plan in the user's language. Use only data in the supplied JSON. "
            "Call only the specialist reviewers needed for the plan. Preserve all deterministic quantities, prices, "
            "risk/compliance statuses and approval decisions exactly. Clearly state when data is synthetic or unknown. "
            "The plan is a draft: never claim to create an order, reserve stock, contact a supplier, or execute payment. "
            "Return a concise user-facing summary, not new calculations."
        ),
        tools=tools,
        **options,
    )
    return ProcurementAgentSet(
        intake=build_intake_agent(),
        manager=manager,
        specialists=specialists,
    )


async def review_plan_with_agents_sdk(plan: PurchasePlan) -> str:
    """Run code-defined SDK manager/specialists as a narrative review only."""
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required when Agents SDK plan review is enabled.")
    try:
        from agents import Runner
    except ImportError as exc:
        raise RuntimeError(
            "Agents SDK is not installed. Install the optional requirements-ai.txt dependencies."
        ) from exc
    agent_set = build_procurement_agent_set()
    payload = plan.model_dump(mode="json", exclude={"request": {"source_text"}})
    result = await Runner.run(
        agent_set.manager,
        input=(
            "Review this deterministic plan and explain its outcome. "
            "Plan JSON follows:\n" + json.dumps(payload, ensure_ascii=False)
        ),
        max_turns=12,
    )
    return str(result.final_output).strip()
