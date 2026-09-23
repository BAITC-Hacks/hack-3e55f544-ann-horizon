"""Typed boundary for local personal shopping workflows."""

from backend.models.personal_extended import (
    BundleRequest, BundleResult, CompatibilityRequest, CompatibilityResult,
    PersonalPreferences, PersonalPreferencesInput, PersonalPurchase, PersonalPurchaseInput,
    PersonalReorderRecommendation, ReturnDraft, ReturnDraftInput,
)
from backend.services.personal_extended import PersonalExtendedService


class PersonalExtendedTools:
    def __init__(self, service: PersonalExtendedService):
        self._service = service

    def preferences(self, user_id: str) -> PersonalPreferences:
        return self._service.preferences(user_id)

    def save_preferences(self, user_id: str, request: PersonalPreferencesInput) -> PersonalPreferences:
        return self._service.save_preferences(user_id, request)

    def add_purchase(self, request: PersonalPurchaseInput) -> PersonalPurchase:
        return self._service.add_purchase(request)

    def purchases(self, user_id: str) -> list[PersonalPurchase]:
        return self._service.purchases(user_id)

    def reorders(self, user_id: str, due_only: bool = False) -> list[PersonalReorderRecommendation]:
        return self._service.reorders(user_id, due_only)

    def compatibility(self, request: CompatibilityRequest) -> CompatibilityResult:
        return self._service.compatibility(request)

    def bundle(self, request: BundleRequest) -> BundleResult:
        return self._service.bundle(request)

    def create_return(self, request: ReturnDraftInput) -> ReturnDraft:
        return self._service.create_return(request)

    def returns(self, user_id: str) -> list[ReturnDraft]:
        return self._service.returns(user_id)

    def cancel_return(self, return_id: str, user_id: str) -> ReturnDraft:
        return self._service.cancel_return(return_id, user_id)
