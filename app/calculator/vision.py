"""Detección de muebles a partir de labels de Google Vision."""
from .tarifario import TARIFARIO

# Mapeo de labels de Vision (inglés) → clave del tarifario
VISION_LABEL_MAP = {
    "wardrobe": "armario",
    "closet": "armario",
    "cupboard": "armario",
    "armoire": "armario",
    "furniture": None,
    "bed": "cama",
    "bed frame": "cama",
    "bunk bed": "cama",
    "sofa": "sofa",
    "couch": "sofa",
    "loveseat": "sofa",
    "desk": "escritorio",
    "office desk": "escritorio",
    "chair": "silla",
    "office chair": "silla",
    "dresser": "comoda",
    "chest of drawers": "comoda",
    "nightstand": "mesita_noche",
    "bedside table": "mesita_noche",
    "television": "mueble_tv",
    "entertainment center": "mueble_tv",
    "tv stand": "mueble_tv",
    "coffee table": "mesa_comedor",
    "kitchen table": "mesa_comedor",
    "mesa": "mesa_comedor",
    "display cabinet": "vitrina",
    "cabinet": "vitrina",
    "bookcase": "vitrina",
    "shelf": "balda",
    "shelving": "balda",
    "floating shelf": "balda",
}


def _match_tarifario_from_label(label: str) -> str | None:
    """Intenta mapear un label de Vision a una clave del tarifario."""
    label_lower = label.lower().strip()

    if label_lower in VISION_LABEL_MAP:
        return VISION_LABEL_MAP[label_lower]

    for key, data in TARIFARIO.items():
        for kw in data["keywords"]:
            if kw in label_lower or label_lower in kw:
                return key

    return None


def detect_from_vision_labels(labels: list[str] | None) -> list[dict]:
    """
    Convierte labels de Vision en ítems detectados.
    Cada ítem incluye confianza relativa según posición en la lista.
    """
    if not labels:
        return []

    detectados = []
    seen = set()

    for idx, label in enumerate(labels):
        tipo = _match_tarifario_from_label(label)
        if not tipo or tipo in seen:
            continue

        confianza = max(0.5, 0.85 - (idx * 0.1))
        item = {
            "tipo": tipo,
            "cantidad": 1,
            "atributos": {},
            "falta_info": [],
            "confianza": round(confianza, 2),
            "fuente": "vision",
        }

        if tipo == "armario":
            item["falta_info"] = ["tipo_puerta", "num_puertas"]
        elif tipo in ("canape", "cama"):
            item["falta_info"] = ["medida"]

        detectados.append(item)
        seen.add(tipo)

    return detectados
