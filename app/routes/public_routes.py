"""
Rutas públicas para la aplicación (Reseñas API V1).
"""
import os
import requests
from flask import Blueprint, jsonify
from cachetools import cached, TTLCache

public_bp = Blueprint('public', __name__)
reviews_cache = TTLCache(maxsize=1, ttl=86400)

@cached(reviews_cache)
def fetch_google_reviews_v1():
    """Consulta la API V1 de Google Places con el mapeo correcto."""
    api_key = os.getenv('GOOGLE_PLACES_API_KEY')
    place_id = os.getenv('PLACE_ID')

    if not api_key or not place_id:
        return {"error": "Faltan credenciales"}, 500

    url = f"https://places.googleapis.com/v1/places/{place_id}"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "reviews,rating,displayName"
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            params={"languageCode": "es"},
            timeout=10
        )
        data = response.json()

        if response.status_code != 200:
            return {"error": "Google API Error", "details": data}, response.status_code

        reviews_raw = data.get("reviews", [])
        reviews_limpias = []

        for r in reviews_raw:
            # Extraemos los datos según la estructura V1 que recibimos
            author_info = r.get("authorAttribution", {})
            text_info = r.get("text", {})

            reviews_limpias.append({
                "author_name": author_info.get("displayName", "Cliente Kiq"),
                "profile_photo_url": author_info.get("photoUri", ""),
                "rating": r.get("rating", 5),
                "text": text_info.get("text", ""),
                "relative_time_description": r.get("relativePublishTimeDescription", "")
            })

        return {
            "result": {
                "reviews": reviews_limpias,
                "rating_global": data.get("rating", 5.0),
                "business_name": data.get("displayName", {}).get("text", "Kiq montajes")
            }
        }, 200

    except requests.exceptions.RequestException as e:
        # Arreglado W0718: Ahora capturamos el error específico de conexión
        return {"error": str(e)}, 500

@public_bp.route('/get-reviews', methods=['GET'])
def get_reviews():
    """Servicio de reseñas."""
    data, status_code = fetch_google_reviews_v1()
    return jsonify(data), status_code
