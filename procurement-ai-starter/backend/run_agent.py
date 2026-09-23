import argparse
import asyncio
import json
import sys
from dotenv import load_dotenv

from backend.agents.manager import build_manager_agent
from backend.models.purchase import UserContext


DEMO_REQUEST = (
    "Нужно закупить 300 SSD минимум 1 TB по цене до 25 000 ₸ за штуку, "
    "доставка максимум 7 дней."
)


def main() -> None:
    load_dotenv()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run the local Procurement AI demo workflow.")
    parser.add_argument("request", nargs="?", default=DEMO_REQUEST, help="Request in Russian or English")
    parser.add_argument("--user-type", choices=("personal", "business"), default="business")
    parser.add_argument("--llm-intake", action="store_true", help="Opt in to an OpenAI model for request extraction")
    parser.add_argument("--agent-review", action="store_true", help="Opt in to the code-defined Agents SDK reviewers")
    args = parser.parse_args()

    context = UserContext(user_type=args.user_type)
    manager = build_manager_agent()
    manager.use_llm_intake = args.llm_intake
    manager.use_agents_sdk_review = args.agent_review
    plan = asyncio.run(manager.plan_text_async(args.request, context))
    print(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
