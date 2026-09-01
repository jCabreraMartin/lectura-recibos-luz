import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from invoice_reader.reader import (
    _billing_period,
    _decimal,
    _detect_supplier,
    _find_invoice_total,
    _find_amount,
    _find_number,
    _find_period_consumption,
    _find_power,
    _find_services,
    extract_pages,
)


class ReaderRulesTests(unittest.TestCase):
    def test_spanish_decimal(self) -> None:
        self.assertEqual(_decimal("1.234,56"), Decimal("1234.56"))

    def test_period_before_value(self) -> None:
        value = _find_number("Consumo valle 339,94 kWh", (r"valle",), r"kWh")
        self.assertEqual(value, Decimal("339.94"))

    def test_value_before_period(self) -> None:
        value = _find_number("339,94 kWh periodo valle", (r"valle",), r"kWh")
        self.assertEqual(value, Decimal("339.94"))

    def test_consumption_is_preferred_over_meter_reading(self) -> None:
        text = (
            "lecturas punta: 24.865,78 kWh; valle 9.459,91 kWh\n"
            "Sus consumos desagregados han sido punta: 141,27 kWh; "
            "llano: 169,97 kWh; valle 339,94 kWh."
        )
        self.assertEqual(
            _find_period_consumption(text, r"punta", r"P1"), Decimal("141.27")
        )

    def test_consumption_summary_can_span_multiple_lines(self) -> None:
        text = (
            "Sus consumos desagregados han sido punta: 100,00 kWh;\n"
            "llano: 100,00 kWh; valle 200,00 kWh."
        )
        self.assertEqual(
            _find_period_consumption(text, r"llano", r"P2"), Decimal("100.00")
        )
        self.assertEqual(
            _find_period_consumption(text, r"valle", r"P3"), Decimal("200.00")
        )

    def test_specific_invoice_total_wins(self) -> None:
        text = "TOTAL ENERGIA 102,99 EUR\nTOTAL IMPORTE FACTURA 137,17 EUR"
        self.assertEqual(_find_invoice_total(text), Decimal("137.17"))

    def test_billing_period(self) -> None:
        period = _billing_period("17/06/2026 - 19/07/2026")
        self.assertEqual(
            period,
            {"start": "2026-06-17", "end": "2026-07-19", "days": 32},
        )

    def test_endesa_official_example_labels(self) -> None:
        text = (
            "ENDESA ENERGIA\n"
            "De 03/08/2021 a 04/09/2021 (32 dias)\n"
            "Consumo total 384,294 kWh\n"
            "Potencias contratadas: punta 3,450 kW; valle 3,450 kW\n"
            "Energia 18,12 EUR\n"
            "Impuesto electricidad (30,19 x 5,112696 %) 1,54 EUR\n"
            "Importe Servicios Endesa X 4,07 EUR\n"
            "Total importe a pagar 39,91 EUR"
        )
        self.assertEqual(
            _billing_period(text),
            {"start": "2021-08-03", "end": "2021-09-04", "days": 32},
        )
        self.assertEqual(_find_power(text, "punta"), Decimal("3.450"))
        self.assertEqual(_find_power(text, "valle"), Decimal("3.450"))
        self.assertEqual(_find_invoice_total(text), Decimal("39.91"))
        self.assertEqual(
            _find_amount(text, (r"(?:total\s+)?energ.?a",)), Decimal("18.12")
        )
        self.assertEqual(
            _find_amount(text, (r"impuesto\s+(?:sobre\s+)?electricidad",)),
            Decimal("1.54"),
        )
        self.assertEqual(
            _find_services(text),
            [{"name": "Importe Servicios Endesa X", "amount_eur": 4.07}],
        )

    def test_supplier(self) -> None:
        self.assertEqual(_detect_supplier("Factura de ENDESA ENERGIA"), "Endesa")

    def test_last_amount_on_detail_line(self) -> None:
        text = "Impuesto sobre electricidad 5,11269632 % s/97,92 EUR 5,01 EUR"
        self.assertEqual(
            _find_amount(text, (r"impuesto\s+sobre\s+electricidad",)),
            Decimal("5.01"),
        )

    @patch("invoice_reader.reader.ocr_pdf", return_value=["texto reconocido"])
    @patch("invoice_reader.reader._extract_pdf_text", return_value=[""])
    def test_ocr_is_used_only_when_pdf_has_no_text(self, extract, ocr) -> None:
        pages, used = extract_pages(Path("factura.pdf"))
        self.assertEqual(pages, ["texto reconocido"])
        self.assertTrue(used)
        ocr.assert_called_once()

    @patch("invoice_reader.reader.ocr_pdf")
    @patch("invoice_reader.reader._extract_pdf_text", return_value=["texto digital"])
    def test_ocr_is_skipped_for_digital_pdf(self, extract, ocr) -> None:
        pages, used = extract_pages(Path("factura.pdf"))
        self.assertEqual(pages, ["texto digital"])
        self.assertFalse(used)
        ocr.assert_not_called()


if __name__ == "__main__":
    unittest.main()

