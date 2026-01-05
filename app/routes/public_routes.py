from flask import Blueprint, jsonify, request

# Creamos el Blueprint 'public'
public_bp = Blueprint('public', __name__)

# --- RUTA 1: RESEÑAS (Para quitar el error 404) ---
@public_bp.route('/get-reviews', methods=['GET'])
def get_reviews():
    return jsonify([
        {"id": 1, "author": "María G.", "text": "Excelente servicio, muy rápido.", "rating": 5},
        {"id": 2, "author": "Juan P.", "text": "El montador fue muy amable.", "rating": 4},
        {"id": 3, "author": "Carlos R.", "text": "Todo perfecto, repetiré.", "rating": 5}
    ]), 200