"""
Rutas públicas para la aplicación (Reseñas, etc).
"""
import os
import requests
from flask import Blueprint, jsonify

public_bp = Blueprint('public', __name__)

@public_bp.route('/get-reviews', methods=['GET'])
def get_reviews():
    """
    Obtiene las reseñas reales desde Google Places API.
    Devuelve la estructura exacta que espera el Frontend.
    """
    api_key = os.getenv('GOOGLE_API_KEY')
    place_id = os.getenv('GOOGLE_PLACE_ID')

    # 1. Validación de credenciales
    if not api_key or not place_id:
        print("❌ Error: Faltan credenciales de Google")
        return jsonify({
            "error": "Faltan credenciales de Google",
            "result": {"reviews": []}
        }), 500

    # 2. URL de Google Places (Details)
    # Dividimos la URL para cumplir con la longitud de línea (C0301)
    base_url = "https://maps.googleapis.com/maps/api/place/details/json"
    fields = "reviews,rating,user_ratings_total"
    url = f"{base_url}?place_id={place_id}&fields={fields}&key={api_key}&language=es"

    try:
        response = requests.get(url, timeout=5)
        data = response.json()

        if data.get('status') != 'OK':
            print(f"⚠️ Error Google API: {data.get('status')} - {data.get('error_message')}")
            return jsonify({"result": {"reviews": []}}), 200

        # 3. Extraer reseñas
        reviews_raw = data.get('result', {}).get('reviews', [])
        reviews_limpias = []

        for r in reviews_raw:
            reviews_limpias.append({
                "author_name": r.get("author_name", "Cliente Kiq"),
                # Dividimos esta línea larga para evitar C0301
                "profile_photo_url": r.get(
                    "profile_photo_url",
                    "https://ui-avatars.com/api/?name=Kiq+Client"
                ),
                "rating": r.get("rating", 5),
                "text": r.get("text", ""),
                "relative_time_description": r.get("relative_time_description", "")
            })

        return jsonify({
            "result": {
                "reviews": reviews_limpias
            }
        }), 200

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"❌ Excepción fetching reviews: {e}")
        return jsonify({"result": {"reviews": []}}), 200
