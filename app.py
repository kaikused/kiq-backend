from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import requests
import os
import re
import urllib.parse
import spacy
from spacy.matcher import Matcher
# --- MODIFICACIÓN: Importaciones añadidas ---
import uuid
from google.cloud import vision

# --- CONFIGURACIÓN INICIAL ---
load_dotenv()
app = Flask(__name__)
CORS(app)

# --- MODIFICACIÓN: Configuración de credenciales de Google Cloud ---
# Asegúrate de que el archivo 'google-credentials.json' esté en la misma carpeta que app.py
try:
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'google-credentials.json'
except Exception as e:
    print(f"Advertencia: No se pudo establecer la variable de entorno para las credenciales de Google. Error: {e}")


try:
    nlp = spacy.load("es_core_news_sm")
except OSError:
    print("Modelo de spaCy no encontrado. Ejecuta: python -m spacy download es_core_news_sm")
    nlp = None

# --- BASE DE DATOS DE CONOCIMIENTO (TARIFARIO) BILINGÜE Y COMPLETO ---
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

# --- DICCIONARIO BILINGÜE DE NÚMEROS ---
NUMEROS_TEXTO = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
}

# --- FUNCIÓN DE ANÁLISIS MEJORADA (CON SPACY MATCHER) ---
# (Esta función no se modifica)
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

# --- RUTA DE CÁLCULO MEJORADA (CON DESGLOSE BILINGÜE Y DISTANCIA REAL) ---
# (Esta función no se modifica)
@app.route('/calcular_presupuesto', methods=['POST'])
def calcular_presupuesto():
    data = request.json
    descripcion = data.get('descripcion_texto_mueble', '')
    direccion_cliente = data.get('direccion_cliente', '')
    lang = data.get('language', 'es')

    analisis = analizar_descripcion_con_spacy(descripcion)
    precio_base = analisis["coste_total_base"] + analisis["coste_total_extras"]
    
    desglose_precio = []
    for item in analisis["muebles_encontrados"]:
        mueble_data = TARIFARIO.get(item["tipo"], {"precio": 40, "display_name": {"es": "Otro", "en": "Other"}})
        coste_mueble = mueble_data.get("precio", 40) * item["cantidad"]
        nombre_item = mueble_data.get("display_name", {}).get(lang, item["tipo"].replace("_", " ").title())
        desglose_precio.append({"item": nombre_item, "cantidad": item["cantidad"], "precio": coste_mueble})

    coste_desplazamiento = 0
    zona_info = "No se proporcionó dirección" if lang == 'es' else "No address provided"
    if direccion_cliente:
        try:
            api_key = os.getenv('GOOGLE_API_KEY')
            origin_address = os.getenv('ORIGIN_ADDRESS')
            origen_formateado = urllib.parse.quote_plus(origin_address)
            destino_formateado = urllib.parse.quote_plus(direccion_cliente)
            url = f"https://maps.googleapis.com/maps/api/distancematrix/json?origins={origen_formateado}&destinations={destino_formateado}&key={api_key}&language={lang}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            distancia_data = response.json()
            if distancia_data['status'] == 'OK' and distancia_data['rows'][0]['elements'][0]['status'] == 'OK':
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

    if coste_desplazamiento > 0:
        nombre_desplazamiento = "Desplazamiento" if lang == 'es' else "Travel Cost"
        desglose_precio.append({"item": nombre_desplazamiento, "cantidad": 1, "precio": coste_desplazamiento})

    precio_final_estimado = max(precio_base + coste_desplazamiento, 30)

    response = {
        "precio_estimado": precio_final_estimado,
        "desglose": desglose_precio,
        "zona_desplazamiento_info": zona_info,
        "necesita_anclaje": analisis.get("necesita_anclaje_general", False),
    }
    return jsonify(response)

# --- MODIFICACIÓN: Nueva ruta para analizar imágenes ---
@app.route('/analizar_imagen', methods=['POST'])
def analizar_imagen():
    if 'imagen' not in request.files:
        return jsonify({"error": "No se encontró el archivo de imagen"}), 400

    file = request.files['imagen']
    
    # Guardar la imagen en el servidor
    filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
    filepath = os.path.join('static', 'uploads', filename)
    file.save(filepath)

    # Crear la URL pública de la imagen
    base_url = os.getenv('BASE_URL', 'http://127.0.0.1:5000')
    image_url = f"{base_url}/{filepath.replace(os.path.sep, '/')}"

    file.seek(0)
    content = file.read()

    # Analizar con Google Vision
    try:
        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=content)
        
        # --- LÓGICA MEJORADA: Usamos OBJECT LOCALIZATION ---
        # Esto es más preciso que las etiquetas generales, ya que detecta objetos específicos.
        objects = client.object_localization(image=image).localized_object_annotations

        if not objects:
            # Si no detecta objetos, usamos las etiquetas como plan B
            print("No se detectaron objetos, usando etiquetas generales como fallback.")
            response = client.label_detection(image=image)
            labels = response.label_annotations
            if response.error.message:
                raise Exception(response.error.message)
            # Convertimos las etiquetas a un formato similar al de los objetos para procesarlas igual
            objects = [{'name': label.description, 'score': label.score} for label in labels]

    except Exception as e:
        print(f"Error en la API de Vision: {e}")
        return jsonify({"error": f"Error en la API de Vision: {e}"}), 500

    # --- LÓGICA MEJORADA: Encontrar la mejor coincidencia basada en la puntuación ---
    
    posibles_muebles = {}
    
    # Recorremos los objetos/etiquetas detectados por Google
    for obj in objects:
        # Normalizamos el nombre del objeto detectado (ej: "Bed frame" -> "bed frame")
        detected_name = obj.name.lower()
        score = obj.score

        # Comparamos con nuestro tarifario
        for mueble_key, data in TARIFARIO.items():
            if detected_name in data["keywords"]:
                # Si encontramos una coincidencia, guardamos su puntuación.
                # Si ya habíamos encontrado este tipo de mueble, nos quedamos con la puntuación más alta.
                if mueble_key not in posibles_muebles or score > posibles_muebles[mueble_key]:
                    posibles_muebles[mueble_key] = score
    
    # --- DECISIÓN INTELIGENTE v2 ---
    muebles_encontrados = []
    if posibles_muebles:
        # Ordenamos los muebles encontrados por su puntuación, de mayor a menor
        muebles_ordenados = sorted(posibles_muebles.items(), key=lambda item: item[1], reverse=True)
        
        # Nos quedamos con todos los resultados que superen un umbral de confianza.
        CONFIDENCE_THRESHOLD = 0.75  # Umbral de confianza del 75%

        for mueble, puntuacion in muebles_ordenados:
            if puntuacion >= CONFIDENCE_THRESHOLD:
                print(f"Coincidencia VÁLIDA encontrada: {mueble} con una confianza de {puntuacion:.2%}")
                # Evitar duplicados si varias keywords apuntan al mismo mueble
                if not any(m['tipo'] == mueble for m in muebles_encontrados):
                    muebles_encontrados.append({"tipo": mueble, "cantidad": 1})
            else:
                # Como la lista está ordenada, si uno no cumple, los siguientes tampoco.
                print(f"Coincidencia descartada por baja confianza: {mueble} ({puntuacion:.2%})")
                break

    # Si después de filtrar por confianza no encontramos nada, usamos 'otro'.
    if not muebles_encontrados:
        print("No se encontraron coincidencias claras por encima del umbral. Usando 'otro'.")
        muebles_encontrados.append({"tipo": "otro", "cantidad": 1})


    # El resto del cálculo del presupuesto es igual
    coste_total_base = 0
    necesita_anclaje_general = False
    for item in muebles_encontrados:
        mueble_data = TARIFARIO.get(item["tipo"], {"precio": 40, "necesita_anclaje": True})
        coste_total_base += item["cantidad"] * mueble_data.get("precio", 40)
        if mueble_data.get("necesita_anclaje"):
            necesita_anclaje_general = True
    
    desglose_precio = []
    lang = request.form.get('language', 'es')
    for item in muebles_encontrados:
        mueble_data = TARIFARIO.get(item["tipo"], {"precio": 40, "display_name": {"es": "Otro", "en": "Other"}})
        coste_mueble = mueble_data.get("precio", 40) * item["cantidad"]
        nombre_item = mueble_data.get("display_name", {}).get(lang, "Otro")
        desglose_precio.append({"item": nombre_item, "cantidad": item["cantidad"], "precio": coste_mueble})

    response_data = {
        "precio_estimado": coste_total_base,
        "desglose": desglose_precio,
        "necesita_anclaje": necesita_anclaje_general,
        "zona_desplazamiento_info": "Dirección no proporcionada",
        "image_url": image_url
    }
    
    return jsonify(response_data)


# --- RUTA PARA LAS RESEÑAS DE GOOGLE ---
# (Esta función no se modifica)
@app.route('/get-reviews')
def get_google_reviews():
    try:
        api_key = os.getenv('GOOGLE_API_KEY')
        place_id = 'ChIJqw-jW3f3cg0RqMnZfeTvCJU'
        lang = request.args.get('language', 'es')
        url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields=reviews&key={api_key}&language={lang}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error al cargar reseñas: {e}")
        return jsonify({"error": "Error interno al cargar reseñas"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
