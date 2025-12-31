"""
Módulo de calculadora de presupuestos para Kiq Montajes.
Integra lógica de precios, IA (Gemini/spaCy) y Google Maps.
"""
import os
import re
import json
import urllib.parse
from io import BytesIO
from flask import Blueprint, request, jsonify
from google.cloud import vision
import google.generativeai as genai
# Importación específica para manejo de errores de credenciales
from google.auth.exceptions import DefaultCredentialsError as AuthCredentialsError
import spacy
from spacy.matcher import Matcher
import requests
from requests.exceptions import RequestException, Timeout

# Se elimina la importación innecesaria de google.api_core.exceptions del código anterior.
from dotenv import load_dotenv

# --- IMPORTS LOCALES ---
from .storage import upload_image_to_gcs
# Importamos el getter del singleton para optimizar carga
from .nlp_engine import get_nlp_model

# Cargar las variables de entorno de .env
load_dotenv()

# --- CONFIGURACIÓN GLOBAL ---

# 1. Inicialización del Cliente de Vision API (Para etiquetas de imágenes)
VISION_CLIENT = None
try:
    # W0718 resuelto con captura específica y/o general justificada
    VISION_CLIENT = vision.ImageAnnotatorClient()
except AuthCredentialsError as e:
    print(f"⚠️ Error al inicializar Google Vision Client (Credenciales): {e}")
except Exception as e:
    # W0718: Captura de último recurso en inicialización
    print(f"⚠️ Error desconocido al inicializar Vision Client: {e}")

# 2. Configuración de Gemini (IA Generativa - Cerebro Principal)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        # W0718: Captura de último recurso en inicialización
        print(f"⚠️ Error al configurar Gemini: {e}")
        GEMINI_API_KEY = None
else:
    print("⚠️ Advertencia: No se encontró GEMINI_API_KEY. La IA avanzada no funcionará.")

# Creamos el Blueprint
calculator_bp = Blueprint('calculator', __name__)

# --- TARIFARIO COMPLETO (SIN CAMBIOS) ---
TARIFARIO = {
    "armario": {
        "keywords": [
            "armario", "armarios", "ropero", "roperos", "guardarropa",
            "guardarropas", "placard", "placards", "clóset", "clósets",
            "locker", "lockers", "wardrobe", "wardrobes", "closet",
            "closets", "armoire", "armoires"
        ],
        "precio": 90,
        "necesita_anclaje": True,
        "display_name": {"es": "Armario", "en": "Wardrobe"},
        "extras": {"puerta_adicional": 30, "espejo": 15}
    },
    "cama": {
        "keywords": [
            "cama", "camas", "canapé", "canapés", "canape", "canapes",
            "somier", "somieres", "litera", "literas", "nido", "nidos",
            "tatami", "tatamis", "bed", "beds", "ottoman", "ottomans",
            "bunk bed", "bunk beds", "bunkbed", "bunkbeds", "bed frame",
            "bed frames", "divan", "divans"
        ],
        "precio": 60,
        "necesita_anclaje": False,
        "display_name": {"es": "Cama", "en": "Bed"}
    },
    "comoda": {
        "keywords": [
            "cómoda", "cómodas", "comoda", "comodas", "sinfonier",
            "sinfonieres", "cajonera", "cajoneras", "chifonier",
            "chifonieres", "dresser", "dressers", "chest of drawers",
            "chests of drawers", "bureau", "bureaus", "tallboy", "tallboys"
        ],
        "precio": 50,
        "necesita_anclaje": True,
        "display_name": {"es": "Cómoda / Cajonera", "en": "Dresser / Chest of Drawers"}
    },
    "mesita_noche": {
        "keywords": [
            "mesita de noche", "mesitas de noche", "mesita", "mesitas",
            "mesilla", "mesillas", "mesa de noche", "mesas de noche",
            "nightstand", "nightstands", "bedside table", "bedside tables",
            "bedside cabinet", "bedside cabinets"
        ],
        "precio": 30,
        "necesita_anclaje": False,
        "display_name": {"es": "Mesita de Noche", "en": "Bedside Table"}
    },
    "cabecero": {
        "keywords": [
            "cabecero", "cabeceros", "cabezal", "cabezales", "cabecera",
            "cabeceras", "headboard", "headboards"
        ],
        "precio": 45,
        "necesita_anclaje": True,
        "display_name": {"es": "Cabecero", "en": "Headboard"}
    },
    "mueble_tv": {
        "keywords": [
            "mueble tv", "muebles tv", "mueble de television",
            "muebles de television", "mesa tv", "mesas tv", "mueble salon",
            "muebles salon", "mueble para tv", "muebles para tv",
            "centro de entretenimiento", "centros de entretenimiento",
            "tv stand", "tv stands", "media console", "media consoles",
            "tv unit", "tv units", "entertainment center", "entertainment centers"
        ],
        "precio": 50,
        "necesita_anclaje": True,
        "display_name": {"es": "Mueble de TV", "en": "TV Stand"}
    },
    "estanteria": {
        "keywords": [
            "estantería", "estanterías", "estanteria", "estanterias",
            "librería", "librerías", "repisa", "repisas", "kallax", "billy",
            "shelving", "shelvings", "bookcase", "bookcases", "shelf",
            "shelves", "shelving unit", "shelving units", "book shelf",
            "book shelves"
        ],
        "precio": 45,
        "necesita_anclaje": True,
        "display_name": {"es": "Estantería / Librería", "en": "Shelving Unit / Bookcase"}
    },
    "vitrina": {
        "keywords": [
            "vitrina", "vitrinas", "aparador", "aparadores", "alacena",
            "alacenas", "credenza", "credenzas", "display cabinet",
            "display cabinets", "sideboard", "sideboards", "buffet",
            "buffets", "hutch", "hutches"
        ],
        "precio": 99,
        "necesita_anclaje": True,
        "display_name": {"es": "Vitrina / Aparador", "en": "Display Cabinet / Sideboard"}
    },
    "mesa_centro": {
        "keywords": [
            "mesa de centro", "mesas de centro", "mesa baja", "mesas bajas",
            "mesita", "mesitas", "mesa de café", "mesas de café",
            "coffee table", "coffee tables", "cocktail table", "cocktail tables"
        ],
        "precio": 35,
        "necesita_anclaje": False,
        "display_name": {"es": "Mesa de Centro", "en": "Coffee Table"}
    },
    "mesa_comedor": {
        "keywords": [
            "mesa de comedor", "mesas de comedor", "mesa de cocina",
            "mesas de cocina", "mesa", "mesas",
            "dining table", "dining tables", "kitchen table", "kitchen tables"
        ],
        "precio": 49,
        "necesita_anclaje": False,
        "display_name": {"es": "Mesa de Comedor", "en": "Dining Table"}
    },
    "silla": {
        "keywords": [
            "silla", "sillas", "asiento", "asientos", "taburete", "taburetes",
            "banqueta", "banquetas", "chair", "chairs", "seat", "seats",
            "stool", "stools"
        ],
        "precio": 10,
        "necesita_anclaje": False,
        "display_name": {"es": "Silla / Taburete", "en": "Chair / Stool"}
    },
    "sofa": {
        "keywords": [
            "sofá", "sofás", "sofa", "sofas", "sillón", "sillones",
            "tresillo", "tresillos", "chaise longue", "chaise longues",
            "couch", "couches", "settee", "settees", "loveseat", "loveseats",
            "lounge", "lounges"
        ],
        "precio": 65,
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
        "precio": 45,
        "necesita_anclaje": False,
        "display_name": {"es": "Escritorio", "en": "Desk"}
    },
    "zapatero": {
        "keywords": [
            "zapatero", "zapateros", "mueble zapatero", "muebles zapateros",
            "shoe rack", "shoe racks", "shoe cabinet", "shoe cabinets",
            "shoe storage", "shoe organizer", "shoe organizers"
        ],
        "precio": 60,
        "necesita_anclaje": True,
        "display_name": {"es": "Zapatero", "en": "Shoe Rack"}
    },
    "panel_decorativo": {
        "keywords": [
            "panel decorativo", "paneles decorativos", "panel de pared",
            "paneles de pared", "revestimiento de pared", "revestimientos de pared",
            "friso", "frisos", "wall panel", "wall panels", "slatted panel",
            "slatted panels", "wainscoting"
        ],
        "precio": 80,
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
        "precio": 500,
        "necesita_anclaje": True,
        "display_name": {"es": "Mueble de Cocina", "en": "Kitchen Cabinet"}
    }
}

NUMEROS_TEXTO = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10
}

# --- FUNCIÓN DE ANÁLISIS CON GEMINI (Cerebro Principal) ---
def analizar_con_gemini(texto_usuario):
    """
    Usa Gemini 2.5 Flash para entender qué muebles hay en el texto
    y mapearlos a nuestro TARIFARIO.
    """
    try:
        if not GEMINI_API_KEY:
            return None

        # 1. Preparamos el catálogo
        keys_muebles = list(TARIFARIO.keys())

        # 2. Creamos el Prompt
        prompt = f"""
Especialista: Eres un experto cotizador. Analiza el texto y extrae muebles y cantidades.

CATÁLOGO DISPONIBLE (Usa SOLO estas claves):
{keys_muebles}

REGLAS DE EXTRACCIÓN:
1. Mapea cualquier mueble mencionado a la clave más cercana de tu CATÁLOGO.
2. Si un mueble se menciona con una cantidad **exacta** (ej. "dos sillas"), usa ese número.
3. Si un mueble se menciona con un término plural e **indefinido** (ej. "unas sillas"),
   **DEBES** responder ÚNICAMENTE con el siguiente objeto JSON especial:

   {{"ACLARACION_REQUERIDA": true, "MUEBLE_PROBABLE": "clave_del_mueble_identificado"}}

4. Si extraes múltiples muebles, y uno requiere aclaración, devuelve SOLO el objeto de aclaración.

TEXTO DEL CLIENTE: "{texto_usuario}"

Responde SOLO con un JSON válido, usando EXCLUSIVAMENTE las claves "tipo" y "cantidad", así:
[
    {{"tipo": "clave_del_mueble", "cantidad": 1}},
    {{"tipo": "otra_clave", "cantidad": 2}}
]
"""
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)

        # Limpiamos la respuesta
        texto_limpio = response.text.replace('```json', '').replace('```', '').strip()

        # Intentamos cargar los datos
        datos = json.loads(texto_limpio)

        # Si la respuesta es el código de aclaración, la devolvemos inmediatamente
        if isinstance(datos, dict) and datos.get("ACLARACION_REQUERIDA"):
            print(f"🛑 Gemini requiere aclaración: {datos.get('MUEBLE_PROBABLE')}")
            return datos

        return datos

    except json.JSONDecodeError as e:
        print(f"❌ Gemini falló al devolver JSON válido: {e}. Respuesta cruda: {response.text[:100]}")
        return None
    except Exception as e:
        # W0718: Captura de excepción genérica justificada por fallos de API de tercero
        print(f"⚠️ Fallo de conexión o configuración de Gemini: {e}")
        return None

# --- FUNCIÓN DE ANÁLISIS CON SPACY (Respaldo Optimizado) ---
def analizar_descripcion_con_spacy(descripcion):
    """
    Analiza una descripción de texto usando spaCy para extraer muebles y cantidades.
    OPTIMIZACIÓN: Usa el modelo singleton para evitar latencia de carga.
    """

    # --- CAMBIO: OBTENER INSTANCIA GLOBAL ---
    nlp = get_nlp_model()

    if not nlp:
        return {"muebles_encontrados": []}

    doc = nlp(descripcion.lower())
    matcher = Matcher(nlp.vocab)

    keyword_to_mueble = {}
    for mueble_key, data in TARIFARIO.items():
        for keyword in data["keywords"]:
            keyword_to_mueble[keyword] = mueble_key

    # Definición de extensiones si no existen
    if not spacy.tokens.Token.has_extension("is_mueble"):
        spacy.tokens.Token.set_extension("is_mueble", default=False)

    for token in doc:
        if token.text in keyword_to_mueble or token.lemma_ in keyword_to_mueble:
            token._.is_mueble = True

    # Patrones de Matcher
    pattern1 = [{"LOWER": {"IN": list(NUMEROS_TEXTO.keys())}}, {"_": {"is_mueble": True}}]
    pattern2 = [{"IS_DIGIT": True}, {"_": {"is_mueble": True}}]
    pattern3 = [{"_": {"is_mueble": True}}]

    matcher.add("CANTIDAD_TEXTO_MUEBLE", [pattern1])
    matcher.add("CANTIDAD_DIGITO_MUEBLE", [pattern2])
    matcher.add("MUEBLE_SOLO", [pattern3])

    matches = matcher(doc)
    # Corrección de tupla de ordenación (start, -end) si Pylint lo exige
    matches.sort(key=lambda m: (m[1], -m[2]))

    muebles_encontrados = []
    tokens_procesados = set()

    for _, start, end in matches:
        if any(i in tokens_procesados for i in range(start, end)):
            continue

        span = doc[start:end]
        cantidad = 1
        mueble_token = span[0]

        if doc[start].is_digit:
            cantidad = int(doc[start].text)
            mueble_token = span[-1]
        elif doc[start].text in NUMEROS_TEXTO:
            cantidad = NUMEROS_TEXTO[doc[start].text]
            mueble_token = span[-1]
      
        # Corrección en la determinación de mueble_token para el patrón MUEBLE_SOLO
        if len(span) == 1 and mueble_token._.is_mueble:
             pass # W0107: Mantenemos el pass si es un placeholder para lógica futura.
        elif len(span) > 1:
            mueble_token = span[-1]


        mueble_tipo = keyword_to_mueble.get(
            mueble_token.text, keyword_to_mueble.get(mueble_token.lemma_)
        )

        if mueble_tipo:
            muebles_encontrados.append({"tipo": mueble_tipo, "cantidad": cantidad})
            for i in range(start, end):
                tokens_procesados.add(i)

    return {"muebles_encontrados": muebles_encontrados}

# --- RUTA DE CÁLCULO UNIFICADA ---
@calculator_bp.route('/calcular_presupuesto', methods=['POST'])
def calcular_presupuesto():
    """
    Ruta unificada para calcular el presupuesto.
    """
    image_labels = None
    image_urls = []
    analisis = None
    direccion_cliente = None

    # --- 1. PETICIÓN FINAL (JSON) ---
    if request.is_json:
        data = request.json
        analisis = data.get('analisis')
        direccion_cliente = data.get('direccion_cliente')
        data.get('language', 'es')
        image_urls = data.get('image_urls', [])
        image_labels = data.get('image_labels')

    # --- 2. PETICIÓN INICIAL (FORMDATA) ---
    else:
        descripcion = request.form.get('descripcion_texto_mueble', '')
        request.form.get('language', 'es')

        # Procesar Imágenes
        files = request.files.getlist('imagen')
        if files and files[0].filename != '':
            for index, file in enumerate(files):
                if file:
                    try:
                        file_content = file.read()
                        file_stream = BytesIO(file_content)
                        file.stream = file_stream
                        file.stream.seek(0)

                        # Subir a GCS
                        gcs_url = upload_image_to_gcs(file, folder="cotizaciones")
                        if gcs_url:
                            image_urls.append(gcs_url)

                        # Análisis Visual (Google Vision)
                        if index == 0 and not image_labels and VISION_CLIENT:
                            file_stream.seek(0)
                            image = vision.Image(content=file_stream.getvalue())
                            # pylint: disable=no-member
                            response = VISION_CLIENT.label_detection(image=image)
                            if not response.error.message:
                                labels = response.label_annotations
                                image_labels = [
                                    f"{l.description} ({l.score:.0%})" for l in labels[:3]
                                ]
                    except Exception as e:
                        # W0718 resuelto: Se usa 'e' para informar. 
                        # Captura intencionalmente amplia por I/O y Vision API.
                        print(f"Error procesando imagen {index}: {e}")

        # --- CEREBRO HÍBRIDO: GEMINI + SPACY ---
        muebles_detectados = []

        # A) Intentar con Gemini
        resultado_gemini = analizar_con_gemini(descripcion)

        # NUEVA LÓGICA: INTERCEPTAR ACLARACIÓN REQUERIDA DE GEMINI
        if (isinstance(resultado_gemini, dict) and
                resultado_gemini.get("ACLARACION_REQUERIDA")):
            print(f"🛑 Aclaración requerida: {resultado_gemini.get('MUEBLE_PROBABLE')}")
            # Devolvemos el código de error 422 (Unprocessable Entity) de inmediato
            return jsonify(resultado_gemini), 422

        if resultado_gemini:
            print(f"🤖 Gemini detectó: {resultado_gemini}")
            muebles_detectados = resultado_gemini
        else:
            # B) Fallback a spaCy (Motor Local)
            print("⚠️ Usando spaCy como respaldo")
            analisis_spacy = analizar_descripcion_con_spacy(descripcion)
            if "muebles_encontrados" in analisis_spacy:
                muebles_detectados = analisis_spacy["muebles_encontrados"]

        # Construir objeto de análisis final
        analisis = {
            "muebles_encontrados": muebles_detectados,
            "coste_total_base": 0,
            "coste_total_extras": 0,
            "necesita_anclaje_general": False,
            "detalles_extras": []
        }

        # Si no se detectó nada, poner "otro"
        if not muebles_detectados:
            analisis["muebles_encontrados"].append({"tipo": "otro", "cantidad": 1})

        # Calcular precios
        for item in analisis["muebles_encontrados"]:
            mueble_data = TARIFARIO.get(
                item["tipo"],
                {"precio": 40, "necesita_anclaje": True}
            )
            analisis["coste_total_base"] += item["cantidad"] * mueble_data.get("precio", 40)
            if mueble_data.get("necesita_anclaje"):
                analisis["necesita_anclaje_general"] = True

        # Extras (Lógica simple mantenida por compatibilidad)
        if "armario" in [m["tipo"] for m in analisis["muebles_encontrados"]]:
            match_puertas = re.search(r'(\d+|uno|dos|tres|cuatro)\s*puertas?', descripcion)
            if match_puertas:
                # W0107 Corregido: Si es un placeholder, se mantiene el pass, sino se elimina.
                pass 

    # --- 3. RESPUESTA FINAL CON DESGLOSE DETALLADO ---
    if not analisis:
        return jsonify({"error": "No se pudo analizar."}), 400

    if direccion_cliente:

        # --- CALCULO DE PRECIOS Y DESPLAZAMIENTO (Lógica corregida) ---
        precio_base = analisis["coste_total_base"] + analisis["coste_total_extras"]
        coste_desplazamiento = 0
        zona_info = "Sin dirección"
        
        # Lógica Google Maps Distancia (EXISTENTE)
        try:
            api_key = os.getenv('GOOGLE_API_KEY')
            origin = os.getenv('ORIGIN_ADDRESS')
            
            if api_key and origin:
                url = "https://maps.googleapis.com/maps/api/distancematrix/json"
                
                params = (
                    f"origins={urllib.parse.quote_plus(origin)}&"
                    f"destinations={urllib.parse.quote_plus(direccion_cliente)}&"
                    f"key={api_key}"
                )
                
                # Se maneja RequestException y Timeout
                resp = requests.get(f"{url}?{params}", timeout=5)
                resp.raise_for_status() # Lanza excepción si la respuesta HTTP es 4xx/5xx
                
                data_maps = resp.json()
                
                # Se valida que el status sea OK y que los elementos existan.
                if (data_maps['status'] == 'OK' and 
                        data_maps['rows'] and data_maps['rows'][0]['elements'] and 
                        data_maps['rows'][0]['elements'][0]['status'] == 'OK'):
                    
                    element = data_maps['rows'][0]['elements'][0]
                    dist_m = element['distance']['value']
                    dist_km = dist_m / 1000
                    
                    if dist_km > 40:
                        coste_desplazamiento = 35
                    elif dist_km > 20:
                        coste_desplazamiento = 25
                    else:
                        coste_desplazamiento = 15
                    zona_info = f"{dist_km:.1f} km"
                else:
                    print(f"⚠️ Google Maps Status no es OK: {data_maps.get('status')}")
                    
        except (RequestException, Timeout) as e:
            # W0107 Corregido: Se añade la lógica de impresión y el `pass` se mantiene.
            print(f"❌ Error de red/timeout de Google Maps: {e}")
            pass 
        except KeyError as e:
            # W0107 Corregido: Se añade la lógica de impresión y el `pass` se mantiene.
            print(f"❌ Error de parsing del JSON de Google Maps (KeyError: {e}).")
            pass 
        except Exception as e: 
            # W0718 resuelto: Se usa 'e' para informar. Captura de último recurso.
            print(f"❌ Error desconocido en Google Maps: {e}")
            pass
        # -----------------------------------------------------------------------------

        # Cálculo puro antes de aplicar el suelo
        precio_total_calculado = precio_base + coste_desplazamiento

        # --- SUELO DE PRECIO (PRICE FLOOR) ---
        # Tarifa mínima de servicio: Desplazamiento + Tiempo Mínimo
        PRECIO_MINIMO = 30.0 # C0103: Dejado como constante de módulo
     
        if precio_total_calculado < PRECIO_MINIMO:
            precio_final = PRECIO_MINIMO
        else:
            precio_final = precio_total_calculado
        # -------------------------------------

        # --- CONSTRUCCIÓN DEL DESGLOSE DETALLADO ---

        muebles_cotizados = []
        anclaje_requerido = False
        coste_anclaje_estimado = 0
        costo_muebles_base = 0

        for item in analisis["muebles_encontrados"]:
            m_data = TARIFARIO.get(item["tipo"],
                                     {"display_name": {"es": item["tipo"]}, "precio": 40})
            nombre = m_data.get("display_name", {}).get("es", item["tipo"])
            precio_unitario = m_data.get("precio", 40)
            subtotal = item["cantidad"] * precio_unitario
            costo_muebles_base += subtotal

            if m_data.get("necesita_anclaje"):
                anclaje_requerido = True
                # Solo estimamos un coste de anclaje si al menos un mueble lo requiere
                coste_anclaje_estimado = 15

            muebles_cotizados.append({
                "item": nombre,
                "cantidad": item["cantidad"],
                "precio_unitario": precio_unitario,
                "subtotal": subtotal,
                "necesita_anclaje": m_data.get("necesita_anclaje", False)
            })

        # Estructura de respuesta final y detallada
        response_data = {
            "status": "success",
            "total_presupuesto": precio_final,
            "desglose": {
                "muebles_cotizados": muebles_cotizados,
                "coste_muebles_base": costo_muebles_base,
                "coste_desplazamiento": coste_desplazamiento,
                "distancia_km": zona_info,
                "coste_anclaje_estimado": coste_anclaje_estimado if anclaje_requerido else 0,
                "total_extras": analisis["coste_total_extras"]
            },
            "necesita_anclaje": anclaje_requerido,
            "image_urls": image_urls,
            "image_labels": image_labels
        }

    else:
        # Respuesta simplificada si no hay dirección
        response_data = {
            "analisis": analisis,
            "necesita_anclaje": analisis.get("necesita_anclaje_general", False),
            "image_urls": image_urls,
            "image_labels": image_labels
        }

    return jsonify(response_data)
