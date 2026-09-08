"""Tests de detección por Vision labels."""
import unittest

import tests.bootstrap  # noqa: F401

from app.calculator.analyzers import merge_detections
from app.calculator.vision import detect_from_vision_labels


class TestVisionDetection(unittest.TestCase):
    def test_detect_wardrobe_from_labels(self):
        items = detect_from_vision_labels(["Wardrobe", "Furniture", "Wood"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["tipo"], "armario")
        self.assertEqual(items[0]["fuente"], "vision")

    def test_detect_shelf_as_balda(self):
        items = detect_from_vision_labels(["Shelving", "Shelf", "Wall"])
        self.assertEqual(items[0]["tipo"], "balda")

    def test_detect_sofa(self):
        items = detect_from_vision_labels(["Couch", "Living room"])
        self.assertEqual(items[0]["tipo"], "sofa")

    def test_merge_text_and_vision(self):
        text = [{"tipo": "cama", "cantidad": 1, "atributos": {"medida": "150"}, "falta_info": [], "confianza": 0.8, "fuente": "gemini"}]
        vision = detect_from_vision_labels(["Bed frame", "Bedroom"])
        merged = merge_detections(text, vision)
        self.assertEqual(len(merged), 1)
        self.assertIn("vision", merged[0]["fuente"])

    def test_vision_does_not_add_extra_furniture(self):
        text = [{"tipo": "cama", "cantidad": 1, "atributos": {"medida": "150"}, "falta_info": [], "confianza": 0.8, "fuente": "gemini"}]
        vision = detect_from_vision_labels(["Nightstand", "Bed", "Television"])
        merged = merge_detections(text, vision)
        tipos = {i["tipo"] for i in merged}
        self.assertEqual(tipos, {"cama"})

    def test_vision_only_when_no_text(self):
        vision = detect_from_vision_labels(["Nightstand", "Bed"])
        merged = merge_detections([], vision)
        tipos = {i["tipo"] for i in merged}
        self.assertIn("cama", tipos)
        self.assertIn("mesita_noche", tipos)


if __name__ == "__main__":
    unittest.main()
