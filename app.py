from flask import Flask, request, jsonify, redirect, abort
from flask_cors import CORS
from dotenv import load_dotenv
import requests
import os
import re
import urllib.parse
import spacy
from spacy.matcher import Matcher
import uuid
from google.cloud import vision
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
import random
import string

# --- CONFIGURACIÓN INICIAL ---
load_dotenv()
app = Flask(__name__)
CORS(app)

# --- CONFIGURACIÓN DE LA BASE DE DATOS ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- MODELO DE LA BASE DE DATOS PARA LOS ENLACES ---
class Link(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_url = db.Column(db.String(512), nullable=False)
    short_code = db.Column(db.String(10), unique=True, nullable=False)

    def __repr__(self):
        return f"<Link {self.short_code}>"

# --- CONFIGURACIÓN DE CREDENCIALES DE GOOGLE CLOUD ---
try:
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'google-credentials.json'
except Exception as e:
    print(f"Advertencia: No se pudo establecer la variable de entorno para las credenciales de Google. Error: {e}")

try:
    nlp = spacy.load("es_core_news_sm")
except OSError:
    print("Modelo de spaCy no encontrado. Ejecuta: python -m spacy download es_core_news_sm")
    nlp = None

# --- TARIFARIO Y NÚMEROS (COMPLETO) ---
TARIFARIO = {
    "armario": {
        "keywords": [
            "armario", "armarios", "ropero", "roperos", "guardarropa", "guardarropas",
            "placard", "placards", "clóset", "clósets", "locker", "lockers",
            "wardrobe", "wardrobes", "closet", "closets", "armoire", "armoires"
        ],
        "precio": 90,
        "necesita_anclaje": True,
        "display_name": {"es": "Armario", "en": "Wardrobe"},
        "extras": {"puerta_adicional": 30, "espejo": 15}
    },
    "cama": {
        "keywords": [
            "cama", "camas", "canapé", "canapés", "canape", "canapes", "somier", "somieres", "litera", "literas",
            "nido", "nidos", "tatami", "tatamis",
            "bed", "beds", "ottoman", "ottomans", "bunk bed", "bunk beds", "bunkbed",
            "bunkbeds", "bed frame", "bed frames", "divan", "divans"
        ],
        "precio": 60,
        "necesita_anclaje": False,
        "display_name": {"es": "Cama", "en": "Bed"}
    },
    "comoda": {
        "keywords": [
            "cómoda", "cómodas", "comoda", "comodas", "sinfonier", "sinfonieres",
            "cajonera", "cajoneras", "chifonier", "chifonieres",
            "dresser", "dressers", "chest of drawers", "chests of drawers", "bureau",
            "bureaus", "tallboy", "tallboys"
        ],
        "precio": 50,
        "necesita_anclaje": True,
        "display_name": {"es": "Cómoda / Cajonera", "en": "Dresser / Chest of Drawers"}
    },
    "mesita_noche": {
        "keywords": [
            "mesita de noche", "mesitas de noche", "mesita", "mesitas", "mesilla", "mesillas",
            "mesa de noche", "mesas de noche",
            "nightstand", "nightstands", "bedside table", "bedside tables",
            "bedside cabinet", "bedside cabinets"
        ],
        "precio": 30,
        "necesita_anclaje": False,
        "display_name": {"es": "Mesita de Noche", "en": "Bedside Table"}
    },
    "cabecero": {
        "keywords": [
            "cabecero", "cabeceros", "cabezal", "cabezales", "cabecera", "cabeceras",
            "headboard", "headboards"
        ],
        "precio": 45,
        "necesita_anclaje": True,
        "display_name": {"es": "Cabecero", "en": "Headboard"}
    },
    "mueble_tv": {
        "keywords": [
            "mueble tv", "muebles tv", "mueble de television", "muebles de television",
            "mesa tv", "mesas tv", "mueble salon", "muebles salon", "mueble para tv", "muebles para tv",
            "centro de entretenimiento", "centros de entretenimiento",
            "tv stand", "tv stands", "media console", "media consoles", "tv unit",
            "tv units", "entertainment center", "entertainment centers"
        ],
        "precio": 50,
        "necesita_anclaje": True,
        "display_name": {"es": "Mueble de TV", "en": "TV Stand"}
    },
    "estanteria": {
        "keywords": [
            "estantería", "estanterías", "estanteria", "estanterias", "librería", "librerías",
            "repisa", "repisas", "kallax", "billy",
            "shelving", "shelvings", "bookcase", "bookcases", "shelf", "shelves",
            "shelving unit", "shelving units", "book shelf", "book shelves"
        ],
        "precio": 45,
        "necesita_anclaje": True,
        "display_name": {"es": "Estantería / Librería", "en": "Shelving Unit / Bookcase"}
    },
    "vitrina": {
        "keywords": [
            "vitrina", "vitrinas", "aparador", "aparadores", "alacena", "alacenas",
            "credenza", "credenzas",
            "display cabinet", "display cabinets", "sideboard", "sideboards",
            "buffet", "buffets", "hutch", "hutches"
        ],
        "precio": 110,
        "necesita_anclaje": True,
        "display_name": {"es": "Vitrina / Aparador", "en": "Display Cabinet / Sideboard"}
    },
    "mesa_centro": {
        "keywords": [
            "mesa de centro", "mesas de centro", "mesa baja", "mesas bajas", "mesita",
            "mesitas", "mesa de café", "mesas de café",
            "coffee table", "coffee tables", "cocktail table", "cocktail tables"
        ],
        "precio": 35,
        "necesita_anclaje": False,
        "display_name": {"es": "Mesa de Centro", "en": "Coffee Table"}
    },
    "mesa_comedor": {
        "keywords": [
            "mesa de comedor", "mesas de comedor", "mesa de cocina", "mesas de cocina", "mesa", "mesas",
            "dining table", "dining tables", "kitchen table", "kitchen tables"
        ],
        "precio": 45,
        "necesita_anclaje": False,
        "display_name": {"es": "Mesa de Comedor", "en": "Dining Table"}
    },
    "silla": {
        "keywords": [
            "silla", "sillas", "asiento", "asientos", "taburete", "taburetes",
            "banqueta", "banquetas",
            "chair", "chairs", "seat", "seats", "stool", "stools"
        ],
        "precio": 15,
        "necesita_anclaje": False,
        "display_name": {"es": "Silla / Taburete", "en": "Chair / Stool"}
    },
    "sofa": {
        "keywords": [
            "sofá", "sofás", "sofa", "sofas", "sillón", "sillones", "tresillo", "tresillos",
            "chaise longue", "chaise longues",
            "couch", "couches", "settee", "settees", "loveseat", "loveseats", "lounge", "lounges"
        ],
        "precio": 60,
        "necesita_anclaje": False,
        "display_name": {"es": "Sofá", "en": "Sofa"}
    },
    "escritorio": {
        "keywords": [
            "escritorio", "escritorios", "buró", "burós", "mesa de estudio",
            "mesas de estudio", "mesa de ordenador", "mesas de ordenador",
            "desk", "desks", "writing desk", "writing desks", "computer desk",
            "computer desks", "study table", "study tables"
        ],
        "precio": 40,
        "necesita_anclaje": False,
        "display_name": {"es": "Escritorio", "en": "Desk"}
    },
    "zapatero": {
        "keywords": [
            "zapatero", "zapateros", "mueble zapatero", "muebles zapateros",
            "shoe rack", "shoe racks", "shoe cabinet", "shoe cabinets",
            "shoe storage", "shoe organizer", "shoe organizers"
        ],
        "precio": 45,
        "necesita_anclaje": True,
        "display_name": {"es": "Zapatero", "en": "Shoe Rack"}
    },
    "panel_decorativo": {
        "keywords": [
            "panel decorativo", "paneles decorativos", "panel de pared", "paneles de pared",
            "revestimiento de pared", "revestimientos de pared", "friso", "frisos",
            "wall panel", "wall panels", "slatted panel", "slatted panels", "wainscoting"
        ],
        "precio": 60,
        "necesita_anclaje": True,
        "display_name": {"es": "Panel Decorativo", "en": "Decorative Panel"}
    },
    "cocina": {
        "keywords": [
            "cocina", "cocinas", "mueble de cocina", "muebles de cocina",
            "gabinete de cocina", "gabinetes de cocina",
            "kitchen cabinet", "kitchen cabinets", "kitchen unit", "kitchen units",
            "kitchen island", "kitchen islands"
        ],
        "precio": 250,
        "necesita_anclaje": True,
        "display_name": {"es": "Mueble de Cocina", "en": "Kitchen Cabinet"}
    }
}
NUMEROS_TEXTO = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
}

# --- FUNCIÓN DE ANÁLISIS DE TEXTO ---
def analizar_descripcion_con_spacy(descripcion):
    if not nlp:
        return {"error": "Modelo de spaCy no cargado"}

    doc = nlp(descripcion.lower())
    matcher = Matcher(nlp.vocab)

    keyword_to_mueble = {}
    for mueble_key, data in TARIFARIO.items():
        for keyword in data["keywords"]:
            keyword_to_mueble[keyword] = mueble_key

    pattern1 = [{"LOWER": {"IN": list(NUMEROS_TEXTO.keys())}}, {"_": {"is_mueble": True}}]
    pattern2 = [{"IS_DIGIT": True}, {"_": {"is_mueble": True}}]
    pattern3 = [{"_": {"is_mueble": True}}]

    if not spacy.tokens.Token.has_extension("is_mueble"):
        spacy.tokens.Token.set_extension("is_mueble", default=False)
    
    for token in doc:
        if token.text in keyword_to_mueble or token.lemma_ in keyword_to_mueble:
            token._.is_mueble = True
    
    matcher.add("CANTIDAD_TEXTO_MUEBLE", [pattern1])
    matcher.add("CANTIDAD_DIGITO_MUEBLE", [pattern2])
    matcher.add("MUEBLE_SOLO", [pattern3])

    matches = matcher(doc)
    matches.sort(key=lambda m: (m[1], -m[2])) 
    
    muebles_encontrados = []
    tokens_procesados = set()

    for match_id, start, end in matches:
        if any(i in tokens_procesados for i in range(start, end)):
            continue

        span = doc[start:end]
        
        if doc[start].is_digit or doc[start].text in NUMEROS_TEXTO:
            if doc[start].is_digit:
                cantidad = int(doc[start].text)
            else:
                cantidad = NUMEROS_TEXTO[doc[start].text]
            mueble_token = span[-1]
        else:
            cantidad = 1
            mueble_token = span[0]
        
        mueble_tipo = keyword_to_mueble.get(mueble_token.text, keyword_to_mueble.get(mueble_token.lemma_))
        
        if mueble_tipo:
            muebles_encontrados.append({"tipo": mueble_tipo, "cantidad": cantidad})
            for i in range(start, end):
                tokens_procesados.add(i)

    analisis = {
        "muebles_encontrados": muebles_encontrados,
        "coste_total_base": 0,
        "coste_total_extras": 0,
        "necesita_anclaje_general": False,
        "detalles_extras": []
    }

    if not muebles_encontrados:
        analisis["muebles_encontrados"].append({"tipo": "otro", "cantidad": 1})

    for item in analisis["muebles_encontrados"]:
        mueble_data = TARIFARIO.get(item["tipo"], {"precio": 40, "necesita_anclaje": True})
        analisis["coste_total_base"] += item["cantidad"] * mueble_data.get("precio", 40)
        if mueble_data.get("necesita_anclaje"):
            analisis["necesita_anclaje_general"] = True
            
    match_puertas = re.search(r'(\d+|uno|dos|tres|cuatro|cinco|seis)\s*puertas?', doc.text)
    if match_puertas:
        num_texto = match_puertas.group(1)
        num_puertas = int(num_texto) if num_texto.isdigit() else NUMEROS_TEXTO.get(num_texto, 0)
        if num_puertas > 2:
            analisis["coste_total_extras"] += (num_puertas - 2) * TARIFARIO["armario"]["extras"]["puerta_adicional"]
            analisis["detalles_extras"].append(f"{num_puertas} puertas")

    if "espejo" in doc.text or "mirror" in doc.text:
        analisis["coste_total_extras"] += TARIFARIO["armario"]["extras"]["espejo"]
        analisis["detalles_extras"].append("con espejo")

    return analisis

# --- RUTA DE CÁLCULO UNIFICADA Y MEJORADA ---
@app.route('/calcular_presupuesto', methods=['POST'])
def calcular_presupuesto():
    # --- PASO 1: INICIALIZAR VARIABLES ---
    image_labels = None
    image_urls = []
    analisis = None
    direccion_cliente = None
    lang = 'es'

    # --- PASO 2: DISTINGUIR ENTRE PETICIÓN INICIAL (FORMDATA) Y FINAL (JSON) ---
    if request.is_json:
        # Es la petición final con la dirección
        data = request.json
        analisis = data.get('analisis')
        direccion_cliente = data.get('direccion_cliente')
        lang = data.get('language', 'es')
        image_urls = data.get('image_urls', []) 
        image_labels = data.get('image_labels')
    
    else: # Es FormData, la petición inicial
        descripcion = request.form.get('descripcion_texto_mueble', '')
        lang = request.form.get('language', 'es')
        
        # --- LÓGICA PARA MANEJAR IMÁGENES ---
        client_name = request.form.get('client_name', 'sin_nombre').replace(' ', '_').lower()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        unique_folder_name = f"{client_name}_{timestamp}"
        
        files = request.files.getlist('imagen')

        if files and files[0].filename != '':
            client_upload_path = os.path.join('static', 'uploads', unique_folder_name)
            os.makedirs(client_upload_path, exist_ok=True)
            for file in files:
                if file:
                    try:
                        filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
                        filepath = os.path.join(client_upload_path, filename)
                        file.save(filepath)

                        base_url = os.getenv('BASE_URL', 'http://127.0.0.1:5000')
                        original_image_url = f"{base_url}/{filepath.replace(os.path.sep, '/')}"
                        
                        # Lógica del acortador
                        short_code = ''.join(random.choices(string.ascii_letters + string.digits, k=7))
                        new_link = Link(original_url=original_image_url, short_code=short_code)
                        db.session.add(new_link)
                        db.session.commit()
                        
                        short_url = f"{base_url}/r/{short_code}"
                        image_urls.append(short_url) 
                        print(f"Imagen guardada: {original_image_url} -> {short_url}")

                        # Analizar solo la primera imagen
                        if not image_labels:
                            file.seek(0)
                            content = file.read()
                            client = vision.ImageAnnotatorClient()
                            image = vision.Image(content=content)
                            response = client.label_detection(image=image)
                            labels = response.label_annotations
                            if response.error.message: raise Exception(response.error.message)
                            
                            image_labels = [f"{label.description} ({label.score:.0%})" for label in labels[:3]]
                            print(f"Metadatos de la imagen: {image_labels}")
                    except Exception as e:
                        print(f"Error al procesar la imagen: {e}")
        
        # El análisis de texto se hace en la petición inicial
        analisis = analizar_descripcion_con_spacy(descripcion)
    
    # --- PASO 3: VALIDAR QUE TENEMOS UN ANÁLISIS ---
    if not analisis:
        return jsonify({"error": "No se proporcionó descripción ni análisis previo."}), 400
        
    # --- PASO 4: CONSTRUIR Y DEVOLVER LA RESPUESTA ---
    if direccion_cliente: # Si hay dirección, es el cálculo final
        precio_base = analisis["coste_total_base"] + analisis["coste_total_extras"]
        coste_desplazamiento = 0
        zona_info = "No se proporcionó dirección" if lang == 'es' else "No address provided"
        try:
            api_key = os.getenv('GOOGLE_API_KEY')
            origin_address = os.getenv('ORIGIN_ADDRESS')
            origen_formateado = urllib.parse.quote_plus(origin_address)
            destino_formateado = urllib.parse.quote_plus(direccion_cliente)
            url = f"https://maps.googleapis.com/maps/api/distancematrix/json?origins={origen_formateado}&destinations={destino_formateado}&key={api_key}&language={lang}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            distancia_data = response.json()
            if distancia_data.get('status') == 'OK' and distancia_data['rows'][0]['elements'][0].get('status') == 'OK':
                distancia_km = distancia_data['rows'][0]['elements'][0]['distance']['value'] / 1000
                if distancia_km > 40: coste_desplazamiento = 35
                elif distancia_km > 20: coste_desplazamiento = 25
                else: coste_desplazamiento = 15
                zona_info = f"{distancia_km:.1f} km"
            else:
                zona_info = "Dirección no encontrada" if lang == 'es' else "Address not found"
        except Exception as e:
            print(f"Error al calcular la distancia: {e}")
            zona_info = "Error de cálculo" if lang == 'es' else "Calculation error"
        
        desglose_precio = []
        for item in analisis["muebles_encontrados"]:
            mueble_data = TARIFARIO.get(item["tipo"], {"precio": 40, "display_name": {"es": "Otro", "en": "Other"}})
            coste_mueble = mueble_data.get("precio", 40) * item["cantidad"]
            nombre_item = mueble_data.get("display_name", {}).get(lang, item["tipo"].replace("_", " ").title())
            desglose_precio.append({"item": nombre_item, "cantidad": item["cantidad"], "precio": coste_mueble})

        if analisis.get("coste_total_extras", 0) > 0:
            nombre_extras = "Ajustes y Extras" if lang == 'es' else "Adjustments & Extras"
            detalles = f" ({', '.join(analisis.get('detalles_extras', []))})" if analisis.get('detalles_extras') else ""
            desglose_precio.append({"item": f"{nombre_extras}{detalles}", "cantidad": 1, "precio": analisis["coste_total_extras"]})

        if coste_desplazamiento > 0:
            nombre_desplazamiento = "Desplazamiento" if lang == 'es' else "Travel Cost"
            desglose_precio.append({"item": nombre_desplazamiento, "cantidad": 1, "precio": coste_desplazamiento})
        
        precio_final_estimado = max(precio_base + coste_desplazamiento, 30)

        response_data = {
            "precio_estimado": precio_final_estimado,
            "desglose": desglose_precio,
            "zona_desplazamiento_info": zona_info,
            "necesita_anclaje": analisis.get("necesita_anclaje_general", False),
            "image_urls": image_urls,
            "image_labels": image_labels
        }
    else: # Si no hay dirección, es la respuesta del análisis inicial
        response_data = {
            "analisis": analisis,
            "necesita_anclaje": analisis.get("necesita_anclaje_general", False),
            "image_urls": image_urls,
            "image_labels": image_labels
        }
    
    return jsonify(response_data)
# --- RUTA PARA REDIRIGIR ENLACES CORTOS ---
@app.route('/r/<short_code>')
def redirect_to_url(short_code):
    link = Link.query.filter_by(short_code=short_code).first()
    if link:
        return redirect(link.original_url)
    else:
        return abort(404) # Devuelve 'Not Found' si el código no existe
    
# --- RUTA PARA LAS RESEÑAS DE GOOGLE ---
@app.route('/get-reviews')
def get_google_reviews():
    try:
        api_key = os.getenv('GOOGLE_API_KEY')
        place_id = 'ChIJ1XtcHYfyly4Re1sFUXqtre8' # Tu Place ID correcto
        lang = request.args.get('language', 'es')
        url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields=reviews&key={api_key}&language={lang}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error al cargar reseñas: {e}")
        return jsonify({"error": "Error interno al cargar reseñas"}), 500
    
with app.app_context():
        db.create_all()

if __name__ == '__main__':
    app.run(debug=True, port=5000)