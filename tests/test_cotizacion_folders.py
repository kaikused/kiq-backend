"""Tests de carpetas de cotización y slugs."""
import unittest

import tests.bootstrap  # noqa: F401

from app.storage import carpeta_valida, codigo_desde_carpeta, nueva_carpeta_cotizacion, slug_cliente


class TestCarpetasCotizacion(unittest.TestCase):
    def test_slug_cliente(self):
        self.assertEqual(slug_cliente("Luis"), "luis")
        self.assertEqual(slug_cliente("María José"), "maria-jose")

    def test_carpeta_incluye_nombre_y_fecha(self):
        carpeta = nueva_carpeta_cotizacion("luis")
        self.assertTrue(carpeta.startswith("cotizaciones/luis-"))
        self.assertTrue(carpeta_valida(codigo_desde_carpeta(carpeta)))

    def test_codigo_rechaza_path_traversal(self):
        self.assertFalse(carpeta_valida("../secret"))
        self.assertFalse(carpeta_valida(""))


if __name__ == "__main__":
    unittest.main()
