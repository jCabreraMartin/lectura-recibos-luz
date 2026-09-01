import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from invoice_reader.batch import build_history, process_folder, render_html


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

    @patch("invoice_reader.batch.read_invoice")
    def test_incremental_processing_and_duplicate_detection(self, reader):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            first = folder / "primera.pdf"
            first.write_bytes(b"factura uno")
            reader.return_value = invoice(
                "2026-04-01", "2026-05-01", 30, 100, 20, 30, 50, 40
            )
            reader.return_value["source"]["filename"] = first.name

            initial = process_folder(folder)
            self.assertEqual(initial["processing"]["new_count"], 1)
            self.assertEqual(reader.call_count, 1)

            duplicate = folder / "copia-con-otro-nombre.pdf"
            duplicate.write_bytes(first.read_bytes())
            repeated = process_folder(folder, existing_history=initial)
            self.assertEqual(repeated["invoice_count"], 1)
            self.assertEqual(repeated["processing"]["skipped_count"], 2)
            self.assertEqual(repeated["processing"]["duplicate_count"], 2)
            self.assertEqual(reader.call_count, 1)

    @patch("invoice_reader.batch.read_invoice")
    def test_changed_file_replaces_previous_invoice(self, reader):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            path = folder / "factura.pdf"
            path.write_bytes(b"version uno")
            original = invoice(
                "2026-04-01", "2026-05-01", 30, 100, 20, 30, 50, 40
            )
            original["source"]["filename"] = path.name
            reader.return_value = original
            initial = process_folder(folder)

            path.write_bytes(b"version dos")
            changed = invoice(
                "2026-04-01", "2026-05-01", 30, 120, 20, 30, 70, 45
            )
            changed["source"]["filename"] = path.name
            reader.return_value = changed
            updated = process_folder(folder, existing_history=initial)

            self.assertEqual(updated["invoice_count"], 1)
            self.assertEqual(updated["totals"]["consumption_kwh"], 120)
            self.assertEqual(updated["processing"]["updated_count"], 1)

    @patch("invoice_reader.batch.read_invoice", side_effect=ValueError("PDF no valido"))
    def test_processing_error_is_reported_without_stopping_folder(self, reader):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "incorrecta.pdf").write_bytes(b"no es un pdf")

            history = process_folder(folder)

            self.assertEqual(history["invoice_count"], 0)
            self.assertEqual(history["processing"]["error_count"], 1)
            self.assertEqual(
                history["processing"]["errors"][0]["filename"], "incorrecta.pdf"
            )


if __name__ == "__main__":
    unittest.main()

