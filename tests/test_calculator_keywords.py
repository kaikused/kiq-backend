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

    def test_nuevas_categorias(self):
        self.assertIn("espejo", find_furniture_keywords("un espejo de pared"))
        self.assertIn("cabecero", find_furniture_keywords("cabecero de 160"))
        self.assertIn("soporte_tv", find_furniture_keywords("soporte tv para la salon"))
        self.assertIn("kallax", find_furniture_keywords("un kallax de ikea"))
        self.assertIn("cama_abatible", find_furniture_keywords("cama abatible de pared"))
        self.assertNotIn("canape", find_furniture_keywords("cama abatible de pared"))
        self.assertIn("zapatero", find_furniture_keywords("zapatero estrecho"))
        self.assertIn("mesa_centro", find_furniture_keywords("mesa de centro"))
        self.assertNotIn("mesa_comedor", find_furniture_keywords("mesa de centro"))
        self.assertIn("litera", find_furniture_keywords("una litera"))
        self.assertIn("cuna", find_furniture_keywords("cuna de bebe"))
        self.assertIn("mueble_bano", find_furniture_keywords("mueble de baño"))
        self.assertIn("cortinas", find_furniture_keywords("montar cortinas"))
        self.assertIn("tendedero", find_furniture_keywords("tendedero de pared"))

    def test_consulta_fuera_de_tarifario(self):
        from app.calculator.analyzers import es_pedido_fuera_de_tarifario
        self.assertTrue(es_pedido_fuera_de_tarifario("montame un toldo electrico"))
        self.assertFalse(es_pedido_fuera_de_tarifario("un kallax blanco"))
        self.assertNotIn("cama", find_furniture_keywords("cama abatible de pared"))

    def test_dos_armarios_cantidad(self):
        items = analizar_con_keywords("2 armarios pax corredera 3 puertas")
        armarios = [i for i in items if i["tipo"] == "armario"]
        self.assertEqual(len(armarios), 1)
        self.assertEqual(armarios[0]["cantidad"], 2)


if __name__ == "__main__":
    unittest.main()
