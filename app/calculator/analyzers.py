"""Motores de análisis de texto: Gemini, spaCy y keywords."""
import json
import os
import re

import google.generativeai as genai

from ..nlp_engine import get_nlp_model
from .measures import campos_faltantes_armario, campos_faltantes_medida
from .tarifario import TARIFARIO
from .vision import detect_from_vision_labels

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception:  # pylint: disable=broad-exception-caught
        GEMINI_API_KEY = None


def _base_item(tipo: str, fuente: str, confianza: float = 0.7) -> dict:
    return {
        "tipo": tipo,
        "cantidad": 1,
        "atributos": {},
        "falta_info": [],
        "confianza": confianza,
        "fuente": fuente,
    }


def _enrich_item(item: dict, texto_lower: str) -> dict:
    """Completa atributos y falta_info según el tipo de mueble."""
    tipo = item["tipo"]
    attrs = item.setdefault("atributos", {})
    faltantes = item.setdefault("falta_info", [])

    if tipo == "armario":
        faltantes.extend(campos_faltantes_armario(texto_lower, attrs))
    elif tipo in ("canape", "cama"):
        faltantes.extend(campos_faltantes_medida(texto_lower, attrs))

    item["falta_info"] = list(dict.fromkeys(faltantes))
    return item


def _extract_cantidad(texto_lower: str, tipo: str) -> int:
    """Detecta cantidad explícita para un tipo de mueble."""
    keywords = TARIFARIO.get(tipo, {}).get("keywords", [tipo])
    for kw in keywords:
        match = re.search(rf"\b(\d+|dos|tres|cuatro)\s+{re.escape(kw)}s?\b", texto_lower)
        if match:
            val = match.group(1)
            if val.isdigit():
                return int(val)
            return {"dos": 2, "tres": 3, "cuatro": 4}.get(val, 1)
    return 1


def find_furniture_keywords(texto: str) -> list[str]:
    """Busca tipos de mueble por keywords (multi-palabra primero, con límite de palabra)."""
    texto_lower = texto.lower()
    encontrados = []
    usado = set()

    entries = []
    for key, data in TARIFARIO.items():
        for kw in data["keywords"]:
            entries.append((len(kw), key, kw))
    entries.sort(reverse=True)

    for _, key, kw in entries:
        if key in usado:
            continue
        if re.search(rf"\b{re.escape(kw)}\b", texto_lower):
            encontrados.append(key)
            usado.add(key)

    return encontrados


def analizar_con_gemini_estricto(texto_usuario: str) -> list[dict] | None:
    """Usa Gemini para extraer muebles. Es estricto: si falta info, la pide."""
    if not GEMINI_API_KEY or not texto_usuario.strip():
        return None

    try:
        keys_muebles = list(TARIFARIO.keys())
        prompt = f"""
Especialista: Eres un experto cotizador. Analiza el texto.
CATÁLOGO: {keys_muebles}

OBJETIVOS:
1. Si el usuario SOLO saluda y NO pide muebles -> {{ "tipo": "saludo", "cantidad": 0 }}

2. Si menciona muebles, extrae SOLO los que el cliente pide en el texto.
   No inventes muebles extra. Ignora cualquier cosa que no esté escrita.
   Extrae datos (MODO ESTRICTO):
   - ARMARIOS:
     * ¿Tipo puerta? (corredera/batiente). SI FALTA -> "falta_info": ["tipo_puerta"].
     * ¿Cantidad puertas? SI FALTA -> "falta_info": ["num_puertas"].

   - CANAPÉS / CAMAS:
     * ¿Medida explícita? (90, 105, 135, 150, 180, pequeño, grande...).
     * SI NO DICE LA MEDIDA -> Debes añadir "falta_info": ["medida"].
     * NO asumas medidas estándar. El cliente DEBE especificar.

ESTRUCTURA JSON:
[
    {{
        "tipo": "canape",
        "cantidad": 1,
        "atributos": {{ "medida": null }},
        "falta_info": ["medida"]
    }}
]

TEXTO CLIENTE: "{texto_usuario}"
Responde SOLO con JSON.
"""
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        texto_limpio = response.text.replace("```json", "").replace("```", "").strip()
        datos = json.loads(texto_limpio)

        if isinstance(datos, dict):
            datos = [datos]

        for item in datos:
            item.setdefault("confianza", 0.85)
            item.setdefault("fuente", "gemini")
            item.setdefault("atributos", {})
            item.setdefault("falta_info", [])

        return datos

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"⚠️ Error Gemini Estricto: {e}")
        return None


def analizar_con_keywords(descripcion: str) -> list[dict]:
    """Detección por keywords multi-palabra (más fiable que token a token)."""
    texto_lower = descripcion.lower()
    tipos = find_furniture_keywords(descripcion)
    detectados = []

    for tipo in tipos:
        item = _base_item(tipo, "keywords", 0.65)
        item["cantidad"] = _extract_cantidad(texto_lower, tipo)
        detectados.append(_enrich_item(item, texto_lower))

    return detectados


def analizar_con_spacy_basico(descripcion: str) -> list[dict]:
    """Respaldo spaCy + keywords. Si Regex no encuentra el dato, lo marca como faltante."""
    keyword_results = analizar_con_keywords(descripcion)
    if keyword_results:
        return keyword_results

    nlp = get_nlp_model()
    if not nlp:
        return []

    doc = nlp(descripcion.lower())
    detectados = []
    texto_lower = descripcion.lower()

    for token in doc:
        if token.i > 0 and token.lemma_ == doc[token.i - 1].lemma_:
            continue

        for key, data in TARIFARIO.items():
            if token.lemma_ in data["keywords"] or token.text in data["keywords"]:
                item = _base_item(key, "spacy", 0.6)
                item["cantidad"] = _extract_cantidad(texto_lower, key)
                detectados.append(_enrich_item(item, texto_lower))
                break

    return detectados


def merge_detections(text_results: list[dict], vision_results: list[dict]) -> list[dict]:
    """
    El texto del cliente manda. Vision solo confirma lo ya pedido.
    No añade muebles extra que salgan en la foto de fondo.
    """
    text_items = [
        item for item in (text_results or [])
        if item.get("tipo") and item.get("tipo") != "saludo"
    ]
    if text_items:
        by_tipo = {}
        merged = []
        for item in text_items:
            by_tipo[item["tipo"]] = item
            merged.append(item)
        for v_item in vision_results or []:
            tipo = v_item.get("tipo")
            if tipo in by_tipo:
                existing = by_tipo[tipo]
                existing["confianza"] = min(1.0, existing.get("confianza", 0.7) + 0.1)
                existing["fuente"] = f"{existing.get('fuente', 'texto')}+vision"
        return merged

    return vision_results or []


def alinear_con_pedido(descripcion: str, items: list[dict]) -> list[dict]:
    """Quita muebles que no están en el texto si el cliente ya dijo qué quiere."""
    pedidos = set(find_furniture_keywords(descripcion or ""))
    if not pedidos:
        return items or []
    filtrados = [
        item for item in (items or [])
        if item.get("tipo") in pedidos
    ]
    if filtrados:
        return filtrados
    return analizar_con_keywords(descripcion)


TIPO_ALIASES = {
    "mesa": "mesa_comedor",
    "mesas": "mesa_comedor",
    "table": "mesa_comedor",
    "comedor": "mesa_comedor",
    "ropero": "armario",
    "placard": "armario",
    "somier": "cama",
    "sillon": "sofa",
    "sillón": "sofa",
}


def _normalize_tipo(tipo: str) -> str:
    if tipo in TARIFARIO or tipo == "saludo":
        return tipo
    return TIPO_ALIASES.get((tipo or "").lower(), tipo)


def detectar_muebles(
    descripcion: str,
    image_labels: list[str] | None = None,
) -> list[dict]:
    """
    Pipeline unificado de detección:
    Gemini → keywords/spaCy → Vision labels.
    """
    resultados = analizar_con_gemini_estricto(descripcion)
    if not resultados:
        resultados = analizar_con_spacy_basico(descripcion)
    else:
        texto_lower = descripcion.lower()
        for item in resultados:
            item["tipo"] = _normalize_tipo(item.get("tipo", ""))
            if item.get("tipo") == "saludo":
                continue
            if item["tipo"] not in TARIFARIO:
                continue
            item.setdefault("atributos", {})
            item["falta_info"] = []
            _enrich_item(item, texto_lower)
        resultados = [
            i for i in resultados
            if i.get("tipo") in TARIFARIO or i.get("tipo") == "saludo"
        ]
        if not resultados:
            resultados = analizar_con_spacy_basico(descripcion)

    vision_results = detect_from_vision_labels(image_labels)
    return merge_detections(resultados or [], vision_results)
