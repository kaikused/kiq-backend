"""
Rutas públicas para la aplicación (Reseñas, etc).
"""
import os
import requests
from requests.utils import quote
from flask import Blueprint, jsonify

public_bp = Blueprint('public', __name__)

@public_bp.route('/get-reviews', methods=['GET'])
def get_reviews():
    """
    Obtiene las reseñas reales desde Google Places API.
    Fuerza HTTPS en las imágenes para evitar bloqueos de contenido mixto.
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