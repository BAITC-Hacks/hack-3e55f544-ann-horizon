import unittest

from backend.agents.intake import IntakeAgent
from backend.agents.manager import ManagerAgent
from backend.models.purchase import UserContext
from backend.integrations.catalog import SampleCatalogAdapter
from backend.services.catalog import CatalogService


class CatalogSearchTests(unittest.TestCase):
    def setUp(self):
        self.catalog = CatalogService(SampleCatalogAdapter())

    def test_full_product_name_and_sku_win_over_shared_tokens(self):
        products = self.catalog.search_products("Нужно купить 1 шт. Беспроводная клавиатура KeyWorks")
        self.assertEqual([(product.id, product.category) for product in products], [(8, "keyboard")])
        by_sku = self.catalog.search_products("KEY-8-KW")
        self.assertEqual([product.id for product in by_sku], [8])

    def test_category_search_does_not_mix_similarly_named_accessories(self):
        products = self.catalog.search_products("Нужна клавиатура для офиса")
        self.assertTrue(products)
        self.assertEqual({product.category for product in products}, {"keyboard"})
        request = IntakeAgent().parse("Нужно закупить 6 клавиатур для офиса")
        self.assertEqual(request.quantity, 6)

    def test_structured_repeat_purchase_keeps_the_requested_sku(self):
        product = self.catalog.list_products()[7]
        request = IntakeAgent().parse(
            f"Нужно купить 1 шт. {product.name}",
            user_context=UserContext(user_type="personal", organization_id=None),
        )
        request = request.model_copy(update={"required_specs": {"sku": product.sku}})
        plan = ManagerAgent().plan(request)
        self.assertTrue(plan.lines)
        self.assertEqual({line.product_id for line in plan.lines}, {product.id})


if __name__ == "__main__":
    unittest.main()
