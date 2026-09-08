"""Tests del motor de precios."""
import unittest

import tests.bootstrap  # noqa: F401

from app.calculator.pricing import calcular_precio_item, calcular_presupuesto_items, total_final


class TestPricingEngine(unittest.TestCase):
    def test_armario_batiente_2_puertas(self):
        result = calcular_precio_item("armario", 1, {"tipo_puerta": "batiente", "num_puertas": 2})
        self.assertEqual(result["precio_unitario"], 90)
        self.assertEqual(result["subtotal"], 90)

    def test_armario_corredera_suplemento(self):
        result = calcular_precio_item("armario", 1, {"tipo_puerta": "corredera", "num_puertas": 2})
        self.assertEqual(result["precio_unitario"], 110)

    def test_armario_4_puertas_extra(self):
        result = calcular_precio_item("armario", 1, {"tipo_puerta": "batiente", "num_puertas": 4})
        self.assertEqual(result["coste_extras"], 60)

    def test_canape_pequeno_descuento(self):
        result = calcular_precio_item("canape", 1, {"medida": "90"})
        self.assertEqual(result["precio_unitario"], 40)

    def test_canape_grande_suplemento(self):
        result = calcular_precio_item("canape", 1, {"medida": "180"})
        self.assertEqual(result["precio_unitario"], 70)

    def test_no_confunde_190_con_pequeno(self):
        result = calcular_precio_item("canape", 1, {"medida": "190"})
        self.assertEqual(result["precio_unitario"], 50)

    def test_presupuesto_multiple_items(self):
        items = [
            {"tipo": "mesita_noche", "cantidad": 2, "atributos": {}},
            {"tipo": "cama", "cantidad": 1, "atributos": {"medida": "135"}},
        ]
        result = calcular_presupuesto_items(items)
        self.assertEqual(result["coste_muebles_base"], 110)
        self.assertFalse(result["anclaje_global"])

    def test_precio_minimo(self):
        totales = total_final(10, 0, 5, False)
        self.assertEqual(totales["total_presupuesto"], 30)

    def test_balda_con_anclaje(self):
        result = calcular_precio_item("balda", 1, {})
        self.assertEqual(result["precio_unitario"], 30)
        self.assertTrue(result["necesita_anclaje"])
        presupuesto = calcular_presupuesto_items([{"tipo": "balda", "cantidad": 1, "atributos": {}}])
        self.assertTrue(presupuesto["anclaje_global"])


if __name__ == "__main__":
    unittest.main()
