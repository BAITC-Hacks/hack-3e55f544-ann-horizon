from fastapi import APIRouter

from backend.models.analytics import ProcurementOverview


router = APIRouter(prefix="/api/procurement/analytics", tags=["Analytics"])


@router.get("/overview", response_model=ProcurementOverview)
def procurement_overview() -> ProcurementOverview:
    # Resolve the application provider at call time to avoid an import cycle.
    from backend.api import get_manager

    return get_manager().tools.procurement_overview()
