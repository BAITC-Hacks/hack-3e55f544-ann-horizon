from backend.models.purchase import PurchasePlan, PurchaseRequest, ValidationFinding
from backend.tools.procurement import ProcurementTools


class ValidatorAgent:
    def __init__(self, tools: ProcurementTools) -> None:
        self._tools = tools

    def validate(self, request: PurchaseRequest, plan: PurchasePlan) -> list[ValidationFinding]:
        return self._tools.validate(request, plan)
