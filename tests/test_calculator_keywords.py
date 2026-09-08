"""Tests de detección por keywords multi-palabra."""
import unittest

import tests.bootstrap  # noqa: F401

from app.calculator.analyzers import alinear_con_pedido, analizar_con_keywords, find_furniture_keywords


class TestKeywordDetection(unittest.TestCase):
    def test_una_mesa_simple(self):
        tipos = find_furniture_keywords("una mesa")
        self.assertIn("mesa_comedor", tipos)

    def test_mesita_no_es_mesa_comedor(self):
        tipos = find_furniture_keywords("una mesita de noche")
        self.assertIn("mesita_noche", tipos)
        self.assertNotIn("mesa_comedor", tipos)

    def test_mesa_comedor_multi_palabra(self):
        tipos = find_furniture_keywords("necesito montar una mesa comedor")
        self.assertIn("mesa_comedor", tipos)

    def test_mueble_tv_multi_palabra(self):
        tipos = find_furniture_keywords("mueble tv blanco ikea")
        self.assertIn("mueble_tv", tipos)

    def test_foto_no_anade_mueble_que_no_pidio(self):
        items = [
            {"tipo": "armario", "cantidad": 1},
            {"tipo": "mueble_tv", "cantidad": 1},
        ]
        filtrados = alinear_con_pedido(
            "armario de puertas batientes de 2 puertas",
            items,
        )
        self.assertEqual([i["tipo"] for i in filtrados], ["armario"])

    def test_una_balda_colgada(self):
        tipos = find_furniture_keywords("una balda colgada")
        self.assertIn("balda", tipos)
        items = analizar_con_keywords("una balda")
        self.assertEqual(items[0]["tipo"], "balda")

    def test_dos_armarios_cantidad(self):
        items = analizar_con_keywords("2 armarios pax corredera 3 puertas")
        armarios = [i for i in items if i["tipo"] == "armario"]
        self.assertEqual(len(armarios), 1)
        self.assertEqual(armarios[0]["cantidad"], 2)


if __name__ == "__main__":
    unittest.main()
