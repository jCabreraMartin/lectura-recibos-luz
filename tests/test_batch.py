import unittest

from invoice_reader.batch import build_history, render_html


def invoice(start, end, days, total_kwh, p1, p2, p3, amount):
    return {
        "source": {"filename": "factura-privada.pdf", "pages": 2},
        "supplier": "Compania ficticia",
        "billing_period": {"start": start, "end": end, "days": days},
        "consumption": {
            "total_kwh": total_kwh,
            "punta_kwh": p1,
            "llano_kwh": p2,
            "valle_kwh": p3,
        },
        "contracted_power": {"punta_kw": 3.3, "valle_kw": 3.3},
        "amounts": {
            "invoice_total_eur": amount,
            "services_total_eur": 5.0,
        },
        "services": [{"name": "Servicio ficticio", "amount_eur": 4.0}],
        "warnings": [],
    }


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.history = build_history(
            [
                invoice("2026-02-01", "2026-03-01", 28, 200, 40, 60, 100, 50),
                invoice("2026-03-01", "2026-04-01", 31, 300, 60, 90, 150, 70),
            ]
        )

    def test_aggregate_totals(self):
        self.assertEqual(self.history["invoice_count"], 2)
        self.assertEqual(self.history["coverage"]["days"], 59)
        self.assertEqual(self.history["totals"]["consumption_kwh"], 500)
        self.assertEqual(self.history["totals"]["invoice_eur"], 120)
        self.assertEqual(self.history["totals"]["valle_kwh"], 250)

    def test_contiguous_periods_have_no_warning(self):
        self.assertEqual(self.history["warnings"], [])

    def test_html_does_not_expose_source_filename(self):
        report = render_html(self.history)
        self.assertIn("Informe historico de electricidad", report)
        self.assertNotIn("factura-privada.pdf", report)


if __name__ == "__main__":
    unittest.main()

