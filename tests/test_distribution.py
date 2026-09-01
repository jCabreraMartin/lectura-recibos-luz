import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from invoice_reader.gui import default_data_dir


class DistributionTests(unittest.TestCase):
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
