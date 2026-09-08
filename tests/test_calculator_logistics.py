"""Tests de desplazamiento y zonas."""
import unittest
from unittest.mock import patch

import tests.bootstrap  # noqa: F401

from app.calculator.logistics import calcular_desplazamiento, coste_por_km, km_local_por_zona


class TestLogistics(unittest.TestCase):
    def test_malaga_capital_tarifa_base(self):
        km = km_local_por_zona("29001")
        self.assertLessEqual(km, 20)
        self.assertEqual(coste_por_km(km), 15)

    def test_costa_cercana_sigue_barata(self):
        self.assertEqual(coste_por_km(30), 20)

    def test_marbella_suplemento(self):
        km = km_local_por_zona("marbella")
        self.assertGreater(km, 40)
        self.assertEqual(coste_por_km(km), 35)

    def test_ronda_no_es_zona_estandar(self):
        km = km_local_por_zona("ronda")
        self.assertGreater(km, 80)
        self.assertEqual(coste_por_km(km), 55)

    def test_sevilla_cubre_el_viaje(self):
        km = km_local_por_zona("sevilla")
        self.assertGreater(km, 180)
        self.assertEqual(coste_por_km(km), 110)

    def test_maps_sevilla_209_km(self):
        self.assertEqual(coste_por_km(208.7), 110)

    def test_cp_sevilla(self):
        km = km_local_por_zona("41001")
        self.assertEqual(coste_por_km(km), 110)

    @patch("app.calculator.logistics._km_desde_maps", return_value=None)
    def test_calcular_ronda_sin_maps(self, _mock_maps):
        resultado = calcular_desplazamiento("ronda")
        self.assertEqual(resultado["coste_desplazamiento"], 55)
        self.assertIn("km", resultado["distancia_km"])

    @patch("app.calculator.logistics._km_desde_maps", return_value=None)
    def test_calcular_sevilla_sin_maps(self, _mock_maps):
        resultado = calcular_desplazamiento("sevilla")
        self.assertEqual(resultado["coste_desplazamiento"], 110)
        self.assertNotIn("no reconocida", resultado["distancia_km"])


if __name__ == "__main__":
    unittest.main()
