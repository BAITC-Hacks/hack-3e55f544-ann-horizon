import os
from decimal import Decimal
from typing import Literal

from pydantic import Field

from backend.models.purchase import StrictModel, PurchaseRequest, UserContext


class IntakeExtraction(StrictModel):
    """Structured user-stated fields; never contains catalog or pricing claims."""

    product_query: str = Field(min_length=1, max_length=200)
    quantity: int = Field(gt=0, le=1_000_000)
    budget_total: float | None
    budget_per_unit: float | None
    currency: str
    max_delivery_days: int | None
    required_specs: dict[str, str | int | float]
    preferred_brand: str | None
    priority: Literal["price", "balanced", "speed", "quality"]


class OpenAIIntakeAgent:
    """Opt-in structured natural-language extraction through OpenAI Agents SDK."""

    async def parse(self, text: str, user_context: UserContext) -> PurchaseRequest:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required when LLM intake is enabled.")
        try:
            from agents import Runner
            from backend.integrations.agents_sdk import build_intake_agent
        except ImportError as exc:
            raise RuntimeError(
                "LLM intake package is missing. Install requirements-ai.txt to enable it."
            ) from exc

        agent = build_intake_agent()
        result = await Runner.run(
            agent,
            input=(
                f"User context: user_type={user_context.user_type}; "
                f"currency={user_context.currency}; department={user_context.department or 'unspecified'}.\n"
                f"Request: {text}"
            ),
        )
        extracted = result.final_output
        if not isinstance(extracted, IntakeExtraction):
            extracted = IntakeExtraction.model_validate(extracted)
        return PurchaseRequest(
            product_query=extracted.product_query,
            quantity=extracted.quantity,
            budget_total=Decimal(str(extracted.budget_total)) if extracted.budget_total is not None else None,
            budget_per_unit=Decimal(str(extracted.budget_per_unit)) if extracted.budget_per_unit is not None else None,
            currency=extracted.currency.upper(),
            max_delivery_days=extracted.max_delivery_days,
            required_specs=extracted.required_specs,
            preferred_brand=extracted.preferred_brand,
            priority=extracted.priority,
            user_context=user_context,
            source_text=text,
        )
