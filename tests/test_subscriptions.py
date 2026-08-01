import json
import unittest
from pathlib import Path


class SubscriptionPackageTests(unittest.TestCase):
    def test_premium_week_package_exists_and_is_ordered_before_one_month(self):
        data = json.loads(Path("subscriptions.json").read_text(encoding="utf-8"))
        packages = data["premium"]["packages"]

        week_package = next((p for p in packages if p["duration"] == 7), None)
        self.assertIsNotNone(week_package)
        self.assertEqual(week_package["price"][0], 100)
        self.assertNotIn(week_package["id"], {p["id"] for p in packages if p is not week_package})

        one_month_index = next(i for i, p in enumerate(packages) if p["duration"] == 30)
        week_index = next(i for i, p in enumerate(packages) if p["duration"] == 7)
        self.assertLess(week_index, one_month_index)


if __name__ == "__main__":
    unittest.main()
