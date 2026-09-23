from backend.integrations.contractors import ContractorCatalogAdapter
from backend.models.contractor import ContractorSearchRequest, ContractorSearchResult
from backend.services.contractors import ContractorMatchingService


class ContractorTools:
    """Application tools for contractor search; catalog access stays behind an adapter."""

    def __init__(self, catalog: ContractorCatalogAdapter) -> None:
        self._matching = ContractorMatchingService(catalog)

    def find_recommendations(self, request: ContractorSearchRequest) -> ContractorSearchResult:
        return self._matching.search(request)
