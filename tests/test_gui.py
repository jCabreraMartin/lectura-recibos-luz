import unittest

from invoice_reader.gui import _number, form_to_offer, offer_to_form


class GuiDataTests(unittest.TestCase):
    def test_spanish_number_and_percentage(self):
        self.assertEqual(_number("0,12", "Precio"), 0.12)
        self.assertEqual(_number("21", "IVA", percentage=True), 0.21)
        self.assertIsNone(_number("", "Opcional"))

    def test_fixed_offer_round_trip(self):
        values = {
            "name": "Oferta de prueba",
            "supplier": "Compania ficticia",
            "energy_type": "fixed",
            "fixed_price": "0,12",
            "power_punta": "0,10",
            "power_valle": "0,01",
            "services": "0",
            "other": "0",
            "meter": "0,026",
            "electricity_tax": "5,11269632",
            "vat": "21",
        }
        offer = form_to_offer(values)
        self.assertEqual(offer["energy"]["price_eur_kwh"], 0.12)
        self.assertEqual(offer["vat_rate"], 0.21)
        restored = offer_to_form(offer)
        self.assertEqual(restored["fixed_price"], "0,12")
        self.assertEqual(restored["vat"], "21")

    def test_negative_cost_is_rejected(self):
        with self.assertRaises(ValueError):
            _number("-1", "Servicios")


if __name__ == "__main__":
    unittest.main()

