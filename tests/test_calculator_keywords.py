"""Tests de detección por keywords multi-palabra."""
import unittest

import tests.bootstrap  # noqa: F401

from app.calculator.analyzers import analizar_con_keywords, find_furniture_keywords


class TestKeywordDetection(unittest.TestCase):
    def test_mesa_comedor_multi_palabra(self):
        tipos = find_furniture_keywords("necesito montar una mesa comedor")
        self.assertIn("mesa_comedor", tipos)

    def test_mueble_tv_multi_palabra(self):
        tipos = find_furniture_keywords("mueble tv blanco ikea")
        self.assertIn("mueble_tv", tipos)

    def test_dos_armarios_cantidad(self):
        items = analizar_con_keywords("2 armarios pax corredera 3 puertas")
        armarios = [i for i in items if i["tipo"] == "armario"]
        self.assertEqual(len(armarios), 1)
        self.assertEqual(armarios[0]["cantidad"], 2)


if __name__ == "__main__":
    unittest.main()
