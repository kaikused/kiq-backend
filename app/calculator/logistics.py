"""Cálculo de costes de desplazamiento desde Málaga."""
import os
import re
import unicodedata

import requests
from requests.exceptions import RequestException, Timeout

ORIGEN_POR_DEFECTO = "Málaga Centro, Málaga, España"

# Distancia aproximada desde Málaga centro si Maps no responde.
ZONAS_KM = (
    (["ronda"], 102),
    (["estepona"], 85),
    (["marbella", "san pedro"], 58),
    (["nerja"], 52),
    (["antequera"], 50),
    (["velez", "velez-malaga", "torre del mar"], 36),
    (["coin", "coín"], 33),
    (["mijas"], 32),
    (["fuengirola"], 30),
    (["alhaurin", "alhaurin de la torre", "alhaurin el grande"], 25),
    (["benalmadena", "arroyo de la miel"], 22),
    (["torremolinos"], 16),
    (["rincon de la victoria", "rincon"], 15),
    (["teatinos", "carretera de cadiz", "ciudad jardin", "malaga centro", "malaga"], 8),
)

CP_KM = (
    ("294", 102),  # Ronda
    ("29680", 85),  # Estepona
    ("29600", 58),  # Marbella
    ("29601", 58),
    ("29602", 58),
    ("29603", 58),
    ("29604", 58),
    ("29660", 58),  # San Pedro
    ("29780", 52),  # Nerja
    ("29200", 50),  # Antequera
    ("29700", 36),  # Vélez
    ("29100", 33),  # Coín
    ("29640", 30),  # Fuengirola
    ("29130", 25),  # Alhaurín
    ("29630", 22),  # Benalmádena
    ("29620", 16),  # Torremolinos
    ("29730", 15),  # Rincón
    ("290", 8),  # Málaga capital
)


def _sin_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower()


def coste_por_km(km: float) -> int:
    if km > 40:
        return 35
    if km > 20:
        return 25
    return 15


def km_local_por_zona(direccion: str) -> float | None:
    """Estima km si Maps no está disponible."""
    texto = _sin_acentos(direccion or "").strip()
    if not texto:
        return None

    cp = re.search(r"\b(\d{5})\b", texto)
    if cp:
        codigo = cp.group(1)
        for prefijo, km in CP_KM:
            if codigo.startswith(prefijo):
                return float(km)

    for nombres, km in ZONAS_KM:
        for nombre in nombres:
            if re.search(rf"\b{re.escape(_sin_acentos(nombre))}\b", texto):
                return float(km)
    return None


def _api_key() -> str | None:
    return (
        os.getenv("GOOGLE_MAPS_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GOOGLE_PLACES_API_KEY")
    )


def _destinos(direccion: str) -> list[str]:
    raw = (direccion or "").strip()
    if not raw:
        return []
    candidatos = [raw]
    bajo = _sin_acentos(raw)
    if "espana" not in bajo and "spain" not in bajo:
        candidatos.append(f"{raw}, Málaga, España")
        candidatos.append(f"{raw}, España")
    vistos = []
    for item in candidatos:
        if item not in vistos:
            vistos.append(item)
    return vistos


def _km_desde_maps(direccion_cliente: str) -> float | None:
    api_key = _api_key()
    if not api_key:
        print("⚠️ Distance Matrix: falta GOOGLE_MAPS_API_KEY / GOOGLE_API_KEY")
        return None

    origin = os.getenv("ORIGIN_ADDRESS") or ORIGEN_POR_DEFECTO
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"

    for destino in _destinos(direccion_cliente):
        try:
            resp = requests.get(
                url,
                params={
                    "origins": origin,
                    "destinations": destino,
                    "key": api_key,
                    "region": "es",
                    "language": "es",
                    "units": "metric",
                },
                timeout=8,
            )
            data = resp.json()
        except (RequestException, Timeout, ValueError) as exc:
            print(f"⚠️ Distance Matrix red: {exc}")
            continue

        status = data.get("status")
        if status != "OK":
            print(f"⚠️ Distance Matrix {status}: {data.get('error_message', '')}")
            continue

        try:
            element = data["rows"][0]["elements"][0]
        except (KeyError, IndexError):
            continue

        elem_status = element.get("status")
        if elem_status != "OK":
            print(f"⚠️ Distance Matrix destino '{destino}': {elem_status}")
            continue

        return element["distance"]["value"] / 1000

    return None


def calcular_desplazamiento(direccion_cliente: str | None) -> dict:
    """Calcula coste y distancia: Google Distance Matrix, con fallback de zonas."""
    if not direccion_cliente:
        return {"coste_desplazamiento": 15, "distancia_km": "Zona no indicada"}

    km = _km_desde_maps(direccion_cliente)
    fuente = "maps"
    if km is None:
        km = km_local_por_zona(direccion_cliente)
        fuente = "zona"

    if km is None:
        print(f"⚠️ Desplazamiento sin distancia para '{direccion_cliente}'")
        return {"coste_desplazamiento": 15, "distancia_km": "Zona no reconocida"}

    coste = coste_por_km(km)
    etiqueta = f"{km:.1f} km"
    if fuente == "zona":
        etiqueta = f"{km:.0f} km (aprox.)"
    print(f"Desplazamiento {direccion_cliente} -> {etiqueta} -> {coste} EUR ({fuente})")
    return {"coste_desplazamiento": coste, "distancia_km": etiqueta}
