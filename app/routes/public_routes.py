"""
Rutas públicas para la aplicación (Reseñas, etc).
"""
import os
import requests
from requests.utils import quote
from flask import Blueprint, jsonify
from cachetools import cached, TTLCache

public_bp = Blueprint('public', __name__)

# Creamos una caché que guarda las reseñas durante 24h (86400 segundos).
# ¡Esto hace que tu web cargue al instante y no gastes cuota de Google!
reviews_cache = TTLCache(maxsize=1, ttl=86400)

@public_bp.route('/get-reviews', methods=['GET'])
@cached(reviews_cache)
def get_reviews():
    """
    Obtiene las reseñas reales desde Google Places API.
    Fuerza HTTPS en las imágenes para evitar bloqueos de contenido mixto.
    Solo devuelve reseñas de 4 y 5 estrellas.
    """
    # Usamos las variables exactas que configuramos en el archivo .env
    api_key = os.getenv('GOOGLE_PLACES_API_KEY')
    place_id = os.getenv('PLACE_ID')

    # 1. Validación de credenciales
    if not api_key or not place_id:
        print("❌ Error: Faltan credenciales de Google para Places")
        return jsonify({
            "error": "Faltan credenciales de Google",
            "result": {"reviews": []}
        }), 500

    # 2. URL de Google Places (Details)
    base_url = "https://maps.googleapis.com/maps/api/place/details/json"
    fields = "reviews,rating,user_ratings_total"
    url = f"{base_url}?place_id={place_id}&fields={fields}&key={api_key}&language=es"

    try:
        response = requests.get(url, timeout=5)
        data = response.json()

        if data.get('status') != 'OK':
            print(f"⚠️ Error Google API: {data.get('status')} - {data.get('error_message')}")
            return jsonify({"result": {"reviews": []}}), 200

        # 3. Extraer reseñas y procesar imágenes
        reviews_raw = data.get('result', {}).get('reviews', [])
        reviews_limpias = []

        for r in reviews_raw:
            # FILTRO: Solo pasamos reseñas buenas (4 o 5 estrellas)
            rating = r.get("rating", 5)
            if rating < 4:
                continue

            author_name = r.get("author_name", "Cliente Kiq")
            raw_photo = r.get("profile_photo_url")
            
            # LÓGICA HTTPS: Si hay foto, reemplazamos http por https.
            # Si no, creamos avatar por defecto.
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

        print("✅ Reseñas de Google obtenidas y cacheadas con éxito.")
        return jsonify({
            "result": {
                "reviews": reviews_limpias,
                "rating_global": data.get('result', {}).get('rating'),
                "total_ratings": data.get('result', {}).get('user_ratings_total')
            }
        }), 200

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"❌ Excepción fetching reviews: {e}")
        return jsonify({"result": {"reviews": []}}), 200