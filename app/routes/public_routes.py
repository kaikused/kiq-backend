"""
Rutas públicas para la aplicación (Reseñas, etc).
"""
import os
import requests
from requests.utils import quote
from flask import Blueprint, jsonify
from cachetools import cached, TTLCache

public_bp = Blueprint('public', __name__)

# Caché de 24 horas para las reseñas
reviews_cache = TTLCache(maxsize=1, ttl=86400)


@cached(reviews_cache)
def fetch_google_reviews_data():
    """
    Consulta la API de Google Places y procesa los datos de las reseñas.
    """
    api_key = os.getenv('GOOGLE_PLACES_API_KEY')
    place_id = os.getenv('PLACE_ID')

    if not api_key or not place_id:
        print("❌ Error: Faltan credenciales de Google para Places")
        return {"error": "Faltan credenciales", "result": {"reviews": []}}, 500

    base_url = "https://maps.googleapis.com/maps/api/place/details/json"
    fields = "reviews,rating,user_ratings_total"
    # Acortamos la línea para cumplir con el límite de caracteres de Pylint
    url = f"{base_url}?place_id={place_id}&fields={fields}&key={api_key}&language=es"

    try:
        response = requests.get(url, timeout=5)
        data = response.json()

        if data.get('status') != 'OK':
            print(f"⚠️ Error Google API: {data.get('status')}")
            return {"result": {"reviews": []}}, 200

        reviews_raw = data.get('result', {}).get('reviews', [])
        reviews_limpias = []

        for r in reviews_raw:
            rating = r.get("rating", 5)
            if rating < 4:
                continue

            author_name = r.get("author_name", "Cliente Kiq")
            raw_photo = r.get("profile_photo_url")

            if raw_photo:
                photo_url = raw_photo.replace("http://", "https://")
            else:
                safe_name = quote(author_name)
                photo_url = (
                    f"https://ui-avatars.com/api/?name={safe_name}"
                    "&background=random&color=fff"
                )

            reviews_limpias.append({
                "author_name": author_name,
                "profile_photo_url": photo_url,
                "rating": rating,
                "text": r.get("text", ""),
                "relative_time_description": r.get("relative_time_description", "")
            })

        return {
            "result": {
                "reviews": reviews_limpias,
                "rating_global": data.get('result', {}).get('rating'),
                "total_ratings": data.get('result', {}).get('user_ratings_total')
            }
        }, 200

    except requests.exceptions.RequestException as e:
        # Capturamos una excepción específica de requests en lugar de Exception global
        print(f"❌ Error de conexión con Google: {e}")
        return {"result": {"reviews": []}}, 200


@public_bp.route('/get-reviews', methods=['GET'])
def get_reviews():
    """
    Endpoint de Flask que sirve las reseñas cacheadas.
    """
    data, status_code = fetch_google_reviews_data()
    return jsonify(data), status_code
