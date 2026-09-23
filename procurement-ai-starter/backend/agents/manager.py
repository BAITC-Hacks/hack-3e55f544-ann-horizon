from decimal import Decimal, ROUND_HALF_UP

from backend.agents.forecast import DemandForecastAgent
from backend.agents.intake import IntakeAgent
from backend.agents.inventory import InventoryAgent
from backend.agents.approval import ApprovalAgent
from backend.agents.compliance import ComplianceAgent
from backend.agents.optimization import OptimizationAgent
from backend.agents.pricing import PricingAgent
from backend.agents.product_matching import ProductMatchingAgent
from backend.agents.reorder import AutomaticReorderAgent
from backend.agents.risk import RiskAgent
from backend.agents.search import SearchAgent
from backend.agents.supplier import SupplierAgent
from backend.agents.validator import ValidatorAgent
from backend.models.purchase import (
    PurchasePlan,
    PurchaseRequest,
    ReorderRecommendation,
    ReorderWorkflow,
    UserContext,
)
from backend.tools.procurement import ProcurementTools
from backend.services.compliance import ComplianceService
from backend.services.policy import PolicyService
from backend.services.risk import RiskService


class ManagerAgent:
    """Coordinates only the agents needed for one local procurement request."""

    def __init__(
        self,
        tools: ProcurementTools | None = None,
        use_llm_intake: bool = False,
        use_agents_sdk_review: bool = False,
    ) -> None:
        self.tools = tools or ProcurementTools()
        self.use_llm_intake = use_llm_intake
        self.use_agents_sdk_review = use_agents_sdk_review
        self.intake = IntakeAgent()
        self.search = SearchAgent(self.tools)
        self.matching = ProductMatchingAgent(self.tools)
        self.suppliers = SupplierAgent(self.tools)
        self.pricing = PricingAgent(self.tools)
        self.optimization = OptimizationAgent(self.tools)
        self.validator = ValidatorAgent(self.tools)
        self.inventory = InventoryAgent(self.tools)
        self.forecast = DemandForecastAgent(self.tools)
        self.reorder = AutomaticReorderAgent(self.tools)
        self.policy = PolicyService()
        self.risks = RiskAgent(RiskService())
        self.compliance = ComplianceAgent(ComplianceService(self.tools.catalog, self.policy))
        self.approval = ApprovalAgent(self.policy.policy)

    def plan_text(self, text: str, user_context: UserContext | None = None) -> PurchasePlan:
        request = self.intake.parse(text, user_context)
        return self.plan(request)

    async def plan_text_async(self, text: str, user_context: UserContext | None = None) -> PurchasePlan:
        context = user_context or UserContext()
        if self.use_llm_intake:
            from backend.integrations.llm_intake import OpenAIIntakeAgent

            request = await OpenAIIntakeAgent().parse(text, context)
        else:
            request = self.intake.parse(text, context)
        plan = self.plan(request)
        if self.use_agents_sdk_review:
            from backend.integrations.agents_sdk import review_plan_with_agents_sdk

            summary = await review_plan_with_agents_sdk(plan)
            plan = plan.model_copy(
                update={
                    "ai_summary": summary,
                    "agents_used": [*plan.agents_used, "OpenAI Agents SDK Manager Agent"],
                }
            )
        return plan

    def reorder_recommendations(self) -> list[ReorderRecommendation]:
        recommendations: list[ReorderRecommendation] = []
        for item in self.inventory.scan():
            if item.available > item.reorder_point:
                continue
            forecast = self.forecast.forecast(item)
            recommendation = self.reorder.recommend(item, forecast)
            if recommendation.recommended_quantity > 0:
                recommendations.append(recommendation)
        return recommendations

    def reorder_workflows(self) -> list[ReorderWorkflow]:
        workflows: list[ReorderWorkflow] = []
        for recommendation in self.reorder_recommendations():
            product = self.tools.catalog.product_by_id(recommendation.product_id)
            if product is None:
                continue
            requirements: dict[str, int | str] = {}
            if product.ram_gb is not None:
                requirements["ram_gb"] = product.ram_gb
            if product.ssd_gb is not None:
                requirements["ssd_gb"] = product.ssd_gb
            if product.capacity_gb is not None:
                requirements["ssd_gb"] = product.capacity_gb
            if product.interface is not None:
                requirements["interface"] = product.interface
            request = PurchaseRequest(
                product_query=product.category,
                quantity=recommendation.recommended_quantity,
                currency="KZT",
                required_specs=requirements,
                preferred_brand=product.brand,
                priority="balanced",
                user_context=UserContext(
                    user_type="business",
                    organization_id="demo-organization",
                    permissions={"recommend_purchase"},
                    currency="KZT",
                ),
                source_text=f"Automatic reorder recommendation for product {product.id}",
            )
            workflows.append(
                ReorderWorkflow(
                    recommendation=recommendation,
                    purchase_plan=self.plan(request),
                )
            )
        return workflows

    def plan(
        self,
        request: PurchaseRequest,
        excluded_supplier_ids: set[int] | None = None,
    ) -> PurchasePlan:
        products = self.search.search(request)
        agents_used = ["ManagerAgent", "SearchAgent"]
        matches = []
        if products:
            matches = self.matching.match(request, products)
            if excluded_supplier_ids:
                matches = [match for match in matches if match.supplier.id not in excluded_supplier_ids]
            agents_used.append("ProductMatchingAgent")

        supplier_assessments = self.suppliers.assess(matches) if matches else []
        price_summary = self.pricing.analyze(request, matches)
        allocation = self.optimization.optimize(request, matches)
        if matches:
            agents_used.extend(["SupplierAgent", "PricingAgent", "OptimizationAgent"])

        effective_unit = None
        if allocation.quantity_planned:
            effective_unit = (allocation.merchandise_subtotal / allocation.quantity_planned).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        explanation = ["Каталог товаров и предложений содержит синтетические DEMO DATA."]
        if excluded_supplier_ids:
            explanation.append(
                "Перепланирование исключило поставщиков с задержанной или отменённой поставкой: "
                + ", ".join(str(item) for item in sorted(excluded_supplier_ids)) + "."
            )
        if not products:
            explanation.append("В локальном каталоге не найден товар по запросу.")
        elif not matches:
            explanation.append("Для найденных товаров нет доступных предложений.")
        elif not allocation.lines:
            explanation.append("Ни одно предложение не проходит заданные характеристики, валюту, бюджет или срок доставки.")
        elif allocation.quantity_planned < request.quantity:
            explanation.append(
                f"Можно распределить {allocation.quantity_planned} из {request.quantity} единиц; остатка у поставщиков недостаточно."
            )
        else:
            explanation.append(f"Подобран план на все {request.quantity} единиц.")
        if len({line.supplier_id for line in allocation.lines}) > 1:
            explanation.append("Количество распределено между несколькими поставщиками из-за остатков и выбранного рейтинга вариантов.")
        if supplier_assessments and any(item.data_status == "insufficient_data" for item in supplier_assessments):
            explanation.append("Истории исполнения поставок нет; показатели надёжности/рейтинга в каталоге помечены как DEMO.")
        explanation.append("Сумма плана — стоимость товаров; неизвестные доставка и налоги в неё не включены.")
        explanation.append("Заказ не создан, платежи и внешние действия не выполнялись.")

        plan = PurchasePlan(
            request=request,
            status="BLOCKED",
            selected_offer_ids=[line.offer_id for line in allocation.lines],
            lines=allocation.lines,
            quantity_requested=request.quantity,
            quantity_planned=allocation.quantity_planned,
            merchandise_subtotal=allocation.merchandise_subtotal,
            total_cost=allocation.merchandise_subtotal,
            currency=request.currency,
            average_effective_unit_cost=effective_unit,
            price_summary=price_summary,
            supplier_assessments=supplier_assessments,
            explanation=explanation,
            agents_used=agents_used,
            requires_human_review=True,
            external_order_created=False,
        )
        findings = self.validator.validate(request, plan)
        agents_used.append("ValidatorAgent")
        risks = self.risks.assess(request, plan)
        compliance_findings = self.compliance.evaluate(request, plan)
        agents_used.extend(["RiskAgent", "ComplianceAgent"])
        has_compliance_error = any(item.severity == "error" for item in compliance_findings)
        is_blocked = any(item.severity == "error" for item in findings) or has_compliance_error
        approval = self.approval.evaluate(
            user_type=request.user_context.user_type,
            amount=plan.total_cost,
            plan_ready=not is_blocked,
            compliance_passed=not has_compliance_error,
        )
        agents_used.append("ApprovalAgent")
        return plan.model_copy(
            update={
                "status": "BLOCKED" if is_blocked else "READY_FOR_REVIEW",
                "findings": findings,
                "risks": risks,
                "compliance_findings": compliance_findings,
                "compliance_status": "BLOCKED" if has_compliance_error else "COMPLIANT",
                "approval_status": approval.status,
                "approval_required": approval.required,
                "approval_role": approval.role,
                "approval_id": approval.approval_id,
                "agents_used": agents_used,
            }
        )


def build_manager_agent() -> ManagerAgent:
    """Keep the starter's builder entry point for scripts and callers."""
    return ManagerAgent()
