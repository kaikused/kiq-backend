"""Tests del clasificador de medidas."""
import unittest

import tests.bootstrap  # noqa: F401

from app.calculator.measures import classify_medida, extract_medida_from_text


class TestClassifyMedida(unittest.TestCase):
    def test_medida_pequena_90(self):
        self.assertEqual(classify_medida("90"), "pequeno")
        self.assertEqual(classify_medida("90cm"), "pequeno")

    def test_no_confunde_190_con_90(self):
        self.assertNotEqual(classify_medida("190"), "pequeno")
        self.assertIsNone(classify_medida("190"))

    def test_medida_grande_180(self):
        self.assertEqual(classify_medida("180"), "grande")
        self.assertEqual(classify_medida("king size"), "grande")

    def test_medida_mediana_135(self):
        self.assertEqual(classify_medida("135"), "mediano")
        self.assertEqual(classify_medida("mediano"), "mediano")

    def test_extract_medida_from_text(self):
        self.assertEqual(extract_medida_from_text("canapé 150cm"), "150")
        self.assertEqual(extract_medida_from_text("cama matrimonio 180"), "180")
        self.assertIsNone(extract_medida_from_text("armario blanco"))

    def test_extract_pequeno_sin_acento(self):
        self.assertEqual(extract_medida_from_text("canape medida pequeno"), "pequeno")
        self.assertEqual(classify_medida("pequeno"), "pequeno")


if __name__ == "__main__":
    unittest.main()
