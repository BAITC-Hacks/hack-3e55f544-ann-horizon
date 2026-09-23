from decimal import Decimal
from uuid import uuid4

from backend.models.purchase import ApprovalRequirement, ProcurementPolicy
from backend.services.compliance import approval_role_for_amount


class ApprovalAgent:
    """Calculates whether the policy requires a human approver; it never places orders."""

    def __init__(self, policy: ProcurementPolicy) -> None:
        self._policy = policy

    def evaluate(
        self,
        *,
        user_type: str,
        amount: Decimal,
        plan_ready: bool,
        compliance_passed: bool,
    ) -> ApprovalRequirement:
        if not plan_ready or not compliance_passed:
            return ApprovalRequirement(status="BLOCKED")
        if user_type != "business":
            return ApprovalRequirement(status="NOT_REQUIRED")
        role = approval_role_for_amount(
            amount,
            self._policy.business.approval_thresholds,
        )
        if role is None:
            return ApprovalRequirement(status="NOT_REQUIRED")
        return ApprovalRequirement(
            status="PENDING",
            required=True,
            role=role,
            approval_id=str(uuid4()),
        )
