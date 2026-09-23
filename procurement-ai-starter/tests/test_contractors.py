import unittest
from collections import Counter
from datetime import date
from decimal import Decimal

from backend.integrations.contractors import FileContractorCatalogAdapter
from backend.models.contractor import ContractorSearchRequest
from backend.services.contractors import ContractorMatchingService
from backend.api import contractor_demo_scenarios


class ContractorMatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profiles = FileContractorCatalogAdapter().list_profiles()
        cls.service = ContractorMatchingService(FileContractorCatalogAdapter())

    @staticmethod
    def dense_request(event_date: date) -> ContractorSearchRequest:
        return ContractorSearchRequest(
            city="Алматы",
            event_date=event_date,
            event_type="корпоратив",
            category="Ведущий",
            budget_kzt=Decimal("1200000"),
            duration_hours=Decimal("4"),
            language="русский",
        )

    def test_source_dataset_counts_and_demo_flags_are_preserved(self) -> None:
        self.assertEqual(len(self.profiles), 66)
        counts = Counter(category for profile in self.profiles for category in profile.categories)
        self.assertEqual(counts["Ведущий"], 15)
        self.assertEqual(counts["Фотограф"], 12)
        self.assertEqual(counts["Банкетный зал"], 8)
        for category in (
            "Флорист", "Декоратор", "Подарки и сувениры", "Ведущий церемонии",
            "Фото и видеобудки", "Отель", "Инструменталист",
        ):
            self.assertEqual(counts[category], 3)
        self.assertEqual(sum(profile.synthetic for profile in self.profiles), 13)

    def test_dense_category_returns_three_distinct_deterministic_explanations(self) -> None:
        request = self.dense_request(date(2026, 10, 17))
        first = self.service.search(request)
        second = self.service.search(request)

        self.assertEqual(first.outcome, "MATCHES")
        self.assertEqual(len(first.cards), 3)
        self.assertEqual(first, second)
        self.assertEqual(len({card.contractor_id for card in first.cards}), 3)
        self.assertEqual(len({card.explanation for card in first.cards}), 3)
        self.assertTrue(all("ниже лимита" in card.explanation for card in first.cards))
        self.assertTrue(all(card.explanation.count(".") == 1 for card in first.cards))

    def test_date_availability_changes_results_and_explains_bookings(self) -> None:
        october_17 = self.service.search(self.dense_request(date(2026, 10, 17)))
        october_18 = self.service.search(self.dense_request(date(2026, 10, 18)))

        self.assertNotEqual(
            [card.contractor_id for card in october_17.cards],
            [card.contractor_id for card in october_18.cards],
        )
        self.assertIn("заняты на эту дату", october_17.message)
        self.assertGreater(october_17.rejection_reasons.get("booked_on_date", 0), 0)

    def test_sparse_category_and_no_result_are_explained(self) -> None:
        sparse = self.service.search(
            ContractorSearchRequest(
                city="Алматы", event_date=date(2026, 11, 14), event_type="свадьба",
                category="Флорист", budget_kzt=Decimal("500000"), language="русский",
            )
        )
        self.assertEqual(sparse.outcome, "MATCHES")
        self.assertLessEqual(len(sparse.cards), 3)
        self.assertLess(sparse.matched_count, 3)
        self.assertIn("заняты на эту дату", sparse.message)

        absent_category = self.service.search(
            ContractorSearchRequest(
                city="Астана", event_date=date(2026, 10, 17), event_type="свадьба",
                category="Неизвестная категория", budget_kzt=Decimal("500000"),
            )
        )
        self.assertEqual(absent_category.outcome, "CATEGORY_NOT_FOUND")
        self.assertIn("нет подрядчиков категории", absent_category.message)

        no_match = self.service.search(
            ContractorSearchRequest(
                city="Алматы", event_date=date(2026, 12, 20), event_type="корпоратив",
                category="Ведущий", budget_kzt=Decimal("1"),
            )
        )
        self.assertEqual(no_match.outcome, "NO_MATCHES")
        self.assertGreater(no_match.candidate_count, 0)
        self.assertIn("выше бюджета", no_match.message)

    def test_calendar_window_is_not_extrapolated(self) -> None:
        with self.assertRaisesRegex(ValueError, "calendar covers"):
            self.service.search(
                ContractorSearchRequest(
                    city="Алматы", event_date=date(2027, 1, 1), event_type="корпоратив",
                    category="Ведущий", budget_kzt=Decimal("1000000"),
                )
            )

    def test_demo_scenarios_include_dense_rare_empty_and_date_comparison(self) -> None:
        scenarios = contractor_demo_scenarios()
        outcomes = {scenario.scenario_id: scenario.result.outcome for scenario in scenarios}
        self.assertEqual(
            set(outcomes),
            {"dense-autumn", "rare-category", "no-result", "calendar-date-comparison"},
        )
        self.assertEqual(outcomes["dense-autumn"], "MATCHES")
        self.assertEqual(outcomes["rare-category"], "MATCHES")
        self.assertEqual(outcomes["no-result"], "NO_MATCHES")
        dense = next(s for s in scenarios if s.scenario_id == "dense-autumn")
        comparison = next(s for s in scenarios if s.scenario_id == "calendar-date-comparison")
        self.assertNotEqual(
            [card.contractor_id for card in dense.result.cards],
            [card.contractor_id for card in comparison.result.cards],
        )


if __name__ == "__main__":
    unittest.main()
