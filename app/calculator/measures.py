"""Utilidades para clasificación de medidas de camas y canapés."""
import re

SMALL_MEASURES = {90, 105}
MEDIUM_MEASURES = {135, 150}
LARGE_MEASURES = {160, 180, 200}

MEDIDA_KEYWORDS = {
    "pequeno": ["individual", "pequeño", "pequeno", "single", "90", "105"],
    "mediano": ["mediano", "mediana", "135", "150"],
    "grande": ["king", "grande", "matrimonio", "160", "180", "200"],
}

MEDIDA_REGEX = re.compile(
    r"\b(90|105|135|150|160|180|190|200)(?:\s*cm)?\b|"
    r"\b(individual|pequeñ[oa]|mediano|mediana|king|grande|matrimonio)\b",
    re.IGNORECASE,
)


def extract_medida_from_text(texto: str) -> str | None:
    """Extrae la primera medida reconocible del texto (prioriza cm numéricos)."""
    if not texto:
        return None
    text = texto.lower()
    numeric = re.search(r"\b(90|105|135|150|160|180|190|200)(?:\s*cm)?\b", text)
    if numeric:
        return numeric.group(1)
    match = MEDIDA_REGEX.search(text)
    if not match:
        return None
    return next((g for g in match.groups() if g), match.group(0))


def classify_medida(medida: str | None) -> str | None:
    """
    Clasifica una medida en 'pequeno', 'mediano' o 'grande'.
    Usa límites de palabra para evitar falsos positivos (p.ej. '90' dentro de '190').
    """
    if not medida:
        return None

    text = medida.lower().strip()

    for size, keywords in MEDIDA_KEYWORDS.items():
        for kw in keywords:
            if kw.isdigit():
                if re.search(rf"\b{kw}(?:\s*cm)?\b", text):
                    return size
            elif kw in text:
                return size

    numbers = re.findall(r"\b(\d{2,3})(?:\s*cm)?\b", text)
    for num_str in numbers:
        num = int(num_str)
        if num in SMALL_MEASURES:
            return "pequeno"
        if num in MEDIUM_MEASURES:
            return "mediano"
        if num in LARGE_MEASURES:
            return "grande"

    return None


def campos_faltantes_armario(texto: str, attrs: dict) -> list[str]:
    """Determina qué datos faltan para cotizar un armario."""
    faltantes = []
    if not attrs.get("tipo_puerta"):
        if re.search(r"corredera|deslizante|sliding", texto):
            attrs["tipo_puerta"] = "corredera"
        elif re.search(r"batiente|bisagra|abrir|hinged", texto):
            attrs["tipo_puerta"] = "batiente"
        else:
            faltantes.append("tipo_puerta")

    if not attrs.get("num_puertas"):
        nums = re.findall(r"\b(\d+)\s*(?:puertas?|doors?)\b", texto)
        if nums:
            attrs["num_puertas"] = int(nums[0])
        elif "dos" in texto or "2 puertas" in texto:
            attrs["num_puertas"] = 2
        elif "tres" in texto or "3 puertas" in texto:
            attrs["num_puertas"] = 3
        elif "cuatro" in texto or "4 puertas" in texto:
            attrs["num_puertas"] = 4
        else:
            faltantes.append("num_puertas")

    return faltantes


def campos_faltantes_medida(texto: str, attrs: dict) -> list[str]:
    """Determina si falta la medida de cama/canapé."""
    if attrs.get("medida"):
        return []
    medida = extract_medida_from_text(texto)
    if medida:
        attrs["medida"] = medida
        return []
    return ["medida"]
