"""Cálculo de costes de desplazamiento."""
import os

import requests
from requests.exceptions import RequestException, Timeout


def calcular_desplazamiento(direccion_cliente: str | None) -> dict:
    """Calcula coste y distancia según Google Distance Matrix."""
    coste = 15
    distancia_txt = "Zona Estándar"

    if not direccion_cliente:
        return {"coste_desplazamiento": coste, "distancia_km": distancia_txt}

    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        origin = os.getenv("ORIGIN_ADDRESS")
        if not (api_key and origin):
            return {"coste_desplazamiento": coste, "distancia_km": distancia_txt}

        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": origin,
            "destinations": direccion_cliente,
            "key": api_key,
        }
        resp = requests.get(url, params=params, timeout=3)
        data_maps = resp.json()

        if (
            data_maps.get("status") == "OK"
            and data_maps["rows"][0]["elements"][0]["status"] == "OK"
        ):
            km = data_maps["rows"][0]["elements"][0]["distance"]["value"] / 1000
            distancia_txt = f"{km:.1f} km"
            if km > 40:
                coste = 35
            elif km > 20:
                coste = 25
            else:
                coste = 15
    except (RequestException, Timeout, KeyError, IndexError):
        pass

    return {"coste_desplazamiento": coste, "distancia_km": distancia_txt}
