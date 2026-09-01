import unittest

from invoice_reader.batch import build_history
from invoice_reader.tariffs import compare_offer, compare_offers, render_comparison_html
from tests.test_batch import invoice


class TariffTests(unittest.TestCase):
    def setUp(self):
        self.history = build_history(
            [invoice("2026-01-01", "2026-02-01", 31, 100, 20, 30, 50, 50)]
        )

    def test_complete_fixed_offer(self):
        offer = {
            "name": "Tarifa completa ficticia",
            "supplier": "Compania ficticia",
            "energy": {"type": "fixed", "price_eur_kwh": 0.10},
            "power": {"punta_eur_kw_day": 0.1, "valle_eur_kw_day": 0.01},
            "services_monthly_eur": 0,
            "other_monthly_eur": 0,
            "meter_rental_eur_day": 0,
            "electricity_tax_rate": 0,
            "vat_rate": 0,
        }
        result = compare_offer(self.history, offer)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["breakdown"]["energy_eur"], 10)
        self.assertEqual(result["estimated_total_eur"], 21.25)
        self.assertEqual(result["historical_savings_eur"], 28.75)

    def test_incomplete_offer_never_claims_final_savings(self):
        offer = {
            "name": "Oferta verbal",
            "supplier": "Endesa",
            "energy": {"type": "fixed", "price_eur_kwh": 0.12},
        }
        result = compare_offer(self.history, offer)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["known_partial_total_eur"], 12)
        self.assertIsNone(result["estimated_total_eur"])
        self.assertIsNone(result["historical_savings_eur"])

    def test_period_prices_and_html(self):
        offer = {
            "name": "Tres periodos",
            "energy": {
                "type": "periods",
                "punta_eur_kwh": 0.2,
                "llano_eur_kwh": 0.1,
                "valle_eur_kwh": 0.05,
            },
        }
        comparison = compare_offers(self.history, [offer])
        self.assertEqual(comparison["offers"][0]["breakdown"]["energy_eur"], 9.5)
        rendered = render_comparison_html(comparison)
        self.assertIn("Tres periodos", rendered)
        self.assertIn("Incompleta", rendered)


if __name__ == "__main__":
    unittest.main()

