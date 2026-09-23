import json
from pathlib import Path

from backend.models.purchase import ProcurementPolicy


class PolicyService:
    """Loads the local procurement policy and exposes typed policy values."""

    def __init__(self, policy_path: str | Path | None = None) -> None:
        root = Path(__file__).resolve().parents[2]
        self.policy_path = Path(policy_path) if policy_path else root / "data" / "procurement_policy.json"
        self._policy = ProcurementPolicy()
        if self.policy_path.exists():
            self._policy = ProcurementPolicy.model_validate_json(
                self.policy_path.read_text(encoding="utf-8")
            )

    @property
    def policy(self) -> ProcurementPolicy:
        return self._policy
