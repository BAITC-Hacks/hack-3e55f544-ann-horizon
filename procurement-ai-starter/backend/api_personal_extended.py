"""Add with app.include_router(create_personal_router(get_repository))."""

from collections.abc import Callable
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.integrations.catalog import SQLiteCatalogAdapter
from backend.models.personal_extended import (
    BundleRequest, BundleResult, CompatibilityRequest, CompatibilityResult,
    PersonalPreferences, PersonalPreferencesInput, PersonalPurchase, PersonalPurchaseInput,
    PersonalReorderRecommendation, ReturnDraft, ReturnDraftInput,
)
from backend.repositories.personal_extended import PersonalExtendedRepository
from backend.repositories.procurement import SQLiteProcurementRepository
from backend.services.catalog import CatalogService
from backend.services.personal_extended import PersonalExtendedService
from backend.tools.personal_extended import PersonalExtendedTools


def create_personal_router(get_repository: Callable[[], SQLiteProcurementRepository]) -> APIRouter:
    router = APIRouter(prefix="/api/personal", tags=["Personal shopping"])

    @lru_cache(maxsize=4)
    def build_tools(repository: SQLiteProcurementRepository) -> PersonalExtendedTools:
        return PersonalExtendedTools(PersonalExtendedService(
            PersonalExtendedRepository(repository.db_path), CatalogService(SQLiteCatalogAdapter(repository)),
        ))

    def get_tools() -> PersonalExtendedTools:
        return build_tools(get_repository())

    def invoke(action, *args):
        try:
            return action(*args)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/preferences", response_model=PersonalPreferences)
    def preferences(user_id: str = Query(default="demo-user", min_length=1, max_length=100),
                    tools: PersonalExtendedTools = Depends(get_tools)):
        return invoke(tools.preferences, user_id)

    @router.put("/preferences", response_model=PersonalPreferences)
    def save_preferences(request: PersonalPreferencesInput,
                         user_id: str = Query(default="demo-user", min_length=1, max_length=100),
                         tools: PersonalExtendedTools = Depends(get_tools)):
        return invoke(tools.save_preferences, user_id, request)

    @router.post("/purchases", response_model=PersonalPurchase, status_code=201)
    def add_purchase(request: PersonalPurchaseInput, tools: PersonalExtendedTools = Depends(get_tools)):
        return invoke(tools.add_purchase, request)

    @router.get("/purchases", response_model=list[PersonalPurchase])
    def purchases(user_id: str = Query(default="demo-user", min_length=1, max_length=100),
                  tools: PersonalExtendedTools = Depends(get_tools)):
        return invoke(tools.purchases, user_id)

    @router.get("/reorder-recommendations", response_model=list[PersonalReorderRecommendation])
    def reorders(user_id: str = Query(default="demo-user", min_length=1, max_length=100),
                 due_only: bool = False, tools: PersonalExtendedTools = Depends(get_tools)):
        return invoke(tools.reorders, user_id, due_only)

    @router.post("/compatibility", response_model=CompatibilityResult)
    def compatibility(request: CompatibilityRequest, tools: PersonalExtendedTools = Depends(get_tools)):
        return invoke(tools.compatibility, request)

    @router.post("/bundles", response_model=BundleResult)
    def bundle(request: BundleRequest, tools: PersonalExtendedTools = Depends(get_tools)):
        return invoke(tools.bundle, request)

    @router.post("/returns", response_model=ReturnDraft, status_code=201)
    def create_return(request: ReturnDraftInput, tools: PersonalExtendedTools = Depends(get_tools)):
        return invoke(tools.create_return, request)

    @router.get("/returns", response_model=list[ReturnDraft])
    def returns(user_id: str = Query(default="demo-user", min_length=1, max_length=100),
                tools: PersonalExtendedTools = Depends(get_tools)):
        return invoke(tools.returns, user_id)

    @router.post("/returns/{return_id}/cancel", response_model=ReturnDraft)
    def cancel_return(return_id: str,
                      user_id: str = Query(default="demo-user", min_length=1, max_length=100),
                      tools: PersonalExtendedTools = Depends(get_tools)):
        return invoke(tools.cancel_return, return_id, user_id)

    return router
