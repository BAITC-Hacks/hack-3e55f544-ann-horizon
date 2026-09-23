from backend.models.contractor import ContractorSearchRequest, ContractorSearchResult
from backend.tools.contractors import ContractorTools


class ContractorMatchingAgent:
    """Returns at most three deterministic, evidence-backed contractor cards."""

    def __init__(self, tools: ContractorTools) -> None:
        self._tools = tools

    def recommend(self, request: ContractorSearchRequest) -> ContractorSearchResult:
        return self._tools.find_recommendations(request)
