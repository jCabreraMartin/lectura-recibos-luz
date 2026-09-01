import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from invoice_reader.gui import default_data_dir, load_settings, save_settings, suggested_paths


class DistributionTests(unittest.TestCase):
    def test_settings_round_trip(self):
        with TemporaryDirectory() as temp:
            data_dir = Path(temp)
            paths = {
                "facturas": data_dir / "entrada",
                "salidas": data_dir / "resultado",
                "ofertas": data_dir / "oferta.private.json",
            }
            save_settings(data_dir, paths)
            self.assertEqual(load_settings(data_dir), paths)

    def test_previous_project_is_suggested_when_it_has_invoices(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            legacy = home / "Documents" / "ChatGPT" / "OptimizadorFacturaElectrica"
            (legacy / "facturas").mkdir(parents=True)
            (legacy / "facturas" / "factura.pdf").write_bytes(b"pdf")
            with patch("pathlib.Path.home", return_value=home):
                paths = suggested_paths(home / "Documents" / "OptimizadorFacturaElectrica")
            self.assertEqual(paths["facturas"], legacy / "facturas")
            self.assertEqual(paths["salidas"], legacy / "salidas")

    def test_configured_data_directory_has_priority(self):
        with patch.dict(os.environ, {"LECTURA_RECIBOS_DATA_DIR": r"D:\DatosLuz"}):
            self.assertEqual(default_data_dir(), Path(r"D:\DatosLuz"))

    def test_installed_app_uses_user_documents(self):
        frozen_existed = hasattr(sys, "frozen")
        previous = getattr(sys, "frozen", None)
        try:
            sys.frozen = True
            with patch("pathlib.Path.home", return_value=Path(r"C:\Users\Prueba")):
                self.assertEqual(
                    default_data_dir(),
                    Path(r"C:\Users\Prueba\Documents\OptimizadorFacturaElectrica"),
                )
        finally:
            if frozen_existed:
                sys.frozen = previous
            else:
                del sys.frozen


if __name__ == "__main__":
    unittest.main()
