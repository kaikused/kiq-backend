"""
Módulo de calculadora de presupuestos para Kiq Montajes.
Versión PRO: Anti-Ambigüedad (Anti-Vagos).
Integra lógica de precios dinámica, IA Estricta (Gemini/spaCy) y Google Maps.
"""
import os
import re
import json
from io import BytesIO
from flask import Blueprint, request, jsonify
from google.cloud import vision
import google.generativeai as genai
# pylint: disable=no-name-in-module
from google.auth.exceptions import DefaultCredentialsError as AuthCredentialsError
import requests
from requests.exceptions import RequestException, Timeout
from dotenv import load_dotenv

from .storage import upload_image_to_gcs
from .nlp_engine import get_nlp_model

load_dotenv()

# --- CONSTANTES GLOBALES ---
PRECIO_MINIMO = 30.0

# --- CONFIGURACIÓN GLOBAL ---
VISION_CLIENT = None
try:
    VISION_CLIENT = vision.ImageAnnotatorClient()
except AuthCredentialsError as e:
    print(f"⚠️ Error Credenciales Vision: {e}")
except Exception as e: # pylint: disable=broad-exception-caught
    print(f"⚠️ Error desconocido Vision Client: {e}")

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"⚠️ Error Gemini Config: {e}")
        GEMINI_API_KEY = None

calculator_bp = Blueprint('calculator', __name__)

# --- TARIFARIO INTELIGENTE ---
TARIFARIO = {
    "armario": {
        "keywords": ["armario", "ropero", "placard", "clóset", "pax", "wardrobe"],
        "precio_base": 90,
        "necesita_anclaje": True,
        "display_name": {"es": "Armario"},
        "reglas_precio": {
            "puerta_extra": 30,
            "suplemento_corredera": 20
        }
    },
    "canape": {
        "keywords": ["canape", "canapé", "arcón", "cama abatible"],
        "precio_base": 60,
        "necesita_anclaje": False,
        "display_name": {"es": "Canapé Abatible"},
        "reglas_precio": {
            "individual": -10,
            "king": 30
        }
    },
    "cama": {
        "precio_base": 50,
        "necesita_anclaje": False,
        "keywords": ["cama", "somier"],
        "display_name": {"es": "Cama"}
    },
    "comoda": {
        "precio_base": 50,
        "necesita_anclaje": True,
        "keywords": ["cómoda", "cajonera"],
        "display_name": {"es": "Cómoda"}
    },
    "mesita_noche": {
        "precio_base": 30,
        "necesita_anclaje": False,
        "keywords": ["mesita", "mesilla"],
        "display_name": {"es": "Mesita de Noche"}
    },
    "sofa": {
        "precio_base": 65,
        "necesita_anclaje": False,
        "keywords": ["sofa", "sofá", "sillon"],
        "display_name": {"es": "Sofá"}
    },
    "mueble_tv": {
        "precio_base": 50,
        "necesita_anclaje": True,
        "keywords": ["mueble tv", "mesa tv"],
        "display_name": {"es": "Mueble TV"}
    },
    "escritorio": {
        "precio_base": 45,
        "necesita_anclaje": False,
        "keywords": ["escritorio", "mesa estudio"],
        "display_name": {"es": "Escritorio"}
    },
    "silla": {
        "precio_base": 15,
        "necesita_anclaje": False,
        "keywords": ["silla", "taburete"],
        "display_name": {"es": "Silla"}
    },
    "vitrina": {
        "precio_base": 99,
        "necesita_anclaje": True,
        "keywords": ["vitrina", "aparador"],
        "display_name": {"es": "Vitrina"}
    },
    "mesa_comedor": {
        "precio_base": 49,
        "necesita_anclaje": False,
        "keywords": ["mesa comedor"],
        "display_name": {"es": "Mesa Comedor"}
    },
}

NUMEROS_TEXTO = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10
}

# --- CEREBRO IA ESTRICTO ---
def analizar_con_gemini_estricto(texto_usuario):
    """
    Usa Gemini para extraer datos estructurados.
    Si falta información crítica, marca 'falta_info'.
    """
    try:
        if not GEMINI_API_KEY:
            return None

        keys_muebles = list(TARIFARIO.keys())

        prompt = f"""
Especialista: Eres un experto cotizador de muebles. Analiza el texto del cliente.
CATÁLOGO: {keys_muebles}

TUS REGLAS DE ORO (Validación Estricta):
1. ARMARIOS:
   - ¿Dice el tipo de puerta? (Busca: "corredera", "deslizante", "batiente", "bisagra").
   - ¿Dice la cantidad? (Busca números o "2 puertas", "3 puertas").
   - Si falta algo, añádelo a la lista 'falta_info': ["tipo_puerta"] o ["num_puertas"].
   - Si no dice nada, asume NADA. No inventes.

2. CANAPÉS / CAMAS:
   - ¿Dice la medida? (90, 105, 135, 150, 160, 180, "matrimonio", "individual", "king").
   - Si falta, añade a 'falta_info': ["medida"].

ESTRUCTURA DE RESPUESTA JSON (Lista de objetos):
[
    {{
        "tipo": "armario",
        "cantidad": 1,
        "atributos": {{
            "tipo_puerta": "corredera",
            "num_puertas": 3,
            "medida": null
        }},
        "falta_info": []
    }}
]

TEXTO CLIENTE: "{texto_usuario}"
Responde SOLO con el JSON válido.
"""
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)

        texto_limpio = response.text.replace('```json', '').replace('```', '').strip()
        datos = json.loads(texto_limpio)

        if isinstance(datos, dict):
            datos = [datos]
        return datos

    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"⚠️ Error Gemini Estricto: {e}")
        return None

# --- FALLBACK: SPACY + REGEX ---
def analizar_con_spacy_basico(descripcion):
    """
    Respaldo híbrido. Usa spaCy para detectar el mueble y RegEx para validar atributos.
    """
    nlp = get_nlp_model()
    if not nlp:
        return []

    doc = nlp(descripcion.lower())
    detectados = []
    texto_lower = descripcion.lower()

    for token in doc:
        # Evitamos duplicados básicos
        if token.i > 0 and token.lemma_ == doc[token.i-1].lemma_:
            continue

        for key, data in TARIFARIO.items():
            if token.lemma_ in data["keywords"] or token.text in data["keywords"]:

                item = {
                    "tipo": key,
                    "cantidad": 1,
                    "atributos": {},
                    "falta_info": []
                }

                # VALIDACIÓN DE REGLAS (REGEX)
                if key == "armario":
                    if re.search(r'corredera|deslizante', texto_lower):
                        item["atributos"]["tipo_puerta"] = "corredera"
                    elif re.search(r'batiente|bisagra|abrir', texto_lower):
                        item["atributos"]["tipo_puerta"] = "batiente"
                    else:
                        item["falta_info"].append("tipo_puerta")

                    match_num = re.search(
                        r'(\d+|dos|tres|cuatro|cinco)\s*(puertas|cuerpos)',
                        texto_lower
                    )
                    if match_num:
                        num_map = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}
                        val = match_num.group(1)
                        if val.isdigit():
                            item["atributos"]["num_puertas"] = int(val)
                        else:
                            item["atributos"]["num_puertas"] = num_map.get(val, 2)
                    else:
                        item["falta_info"].append("num_puertas")

                elif key == "canape" or key == "cama":
                    match_medida = re.search(
                        r'90|105|135|150|160|180|200|king|matrimonio|individual',
                        texto_lower
                    )
                    if match_medida:
                        item["atributos"]["medida"] = match_medida.group(0)
                    else:
                        item["falta_info"].append("medida")

                detectados.append(item)
                break

    return detectados

# --- RUTA PRINCIPAL ---
@calculator_bp.route('/calcular_presupuesto', methods=['POST'])
def calcular_presupuesto():
    """
    Endpoint principal para cálculo de presupuestos.
    Maneja texto, imágenes y validación interactiva con el usuario.
    """
    # 1. Variables y Entrada
    image_urls = []
    image_labels = None
    descripcion = ""
    direccion_cliente = None

    if request.is_json:
        data = request.json
        descripcion = data.get('descripcion_texto_mueble', '')
        direccion_cliente = data.get('direccion_cliente')
        analisis_previo = data.get('analisis_confirmado')
    else:
        descripcion = request.form.get('descripcion_texto_mueble', '')
        direccion_cliente = request.form.get('direccion_cliente')
        analisis_previo = None

        # Procesamiento Básico de Imágenes
        files = request.files.getlist('imagen')
        if files and files[0].filename != '':
            for index, file in enumerate(files):
                if file:
                    try:
                        file_content = file.read()
                        file_stream = BytesIO(file_content)
                        file.stream = file_stream
                        file.stream.seek(0)
                        gcs_url = upload_image_to_gcs(file, folder="cotizaciones")
                        if gcs_url:
                            image_urls.append(gcs_url)
                        if index == 0 and VISION_CLIENT:
                            file_stream.seek(0)
                            image = vision.Image(content=file_stream.getvalue())
                            # pylint: disable=no-member
                            response = VISION_CLIENT.label_detection(image=image)
                            if not response.error.message:
                                labels = response.label_annotations
                                image_labels = [f"{l.description}" for l in labels[:3]]
                    except Exception as e: # pylint: disable=broad-exception-caught
                        print(f"Error img {index}: {e}")

    # 2. PROCESAMIENTO INTELIGENTE
    muebles_procesados = []

    if analisis_previo:
        muebles_procesados = analisis_previo
    else:
        # Si es la primera vez, preguntamos a Gemini Estricto
        resultados = analizar_con_gemini_estricto(descripcion)

        if not resultados:
            # Fallback Inteligente si Gemini muere
            resultados = analizar_con_spacy_basico(descripcion)

        # --- FILTRO ANTI-VAGOS ---
        preguntas_necesarias = []
        for item in resultados:
            if item.get("falta_info"):
                preguntas_necesarias.append({
                    "tipo_mueble": item["tipo"],
                    "dato_faltante": item["falta_info"]
                })

        if preguntas_necesarias:
            return jsonify({
                "status": "ask_user",
                "mensaje": "Para darte un precio exacto, necesitamos un detalle más.",
                "preguntas": preguntas_necesarias,
                "analisis_temporal": resultados
            })

        muebles_procesados = resultados

    # 3. CÁLCULO DE PRECIO
    coste_muebles_base = 0 # Variable unificada
    coste_extras = 0
    detalles_factura = []
    anclaje_global = False
    muebles_cotizados = []

    for item in muebles_procesados:
        tipo = item.get("tipo", "otro")
        cantidad = item.get("cantidad", 1)
        attrs = item.get("atributos", {})

        tarifas = TARIFARIO.get(tipo, {"precio_base": 40, "necesita_anclaje": False})
        precio_unitario = tarifas.get("precio_base", 40)

        # --- LÓGICA DE VARIANTES Y EXTRAS ---
        if tipo == "armario":
            reglas = tarifas.get("reglas_precio", {})
            tipo_puerta = attrs.get("tipo_puerta", "batiente")
            if "corredera" in str(tipo_puerta).lower():
                suplemento = reglas.get("suplemento_corredera", 20)
                precio_unitario += suplemento
                detalles_factura.append(f"Suplemento Puertas Correderas: +{suplemento}€")

            num_puertas = attrs.get("num_puertas", 2)
            if isinstance(num_puertas, (int, float)) and num_puertas > 2:
                extra_puertas = (num_puertas - 2) * reglas.get("puerta_extra", 30)
                coste_extras += extra_puertas
                detalles_factura.append(
                    f"Extra tamaño ({num_puertas} puertas): +{extra_puertas}€"
                )

        elif tipo == "canape":
            reglas = tarifas.get("reglas_precio", {})
            medida = str(attrs.get("medida", "135"))

            if any(m in medida for m in ["90", "105", "individual"]):
                precio_unitario += reglas.get("individual", -10)
            elif any(m in medida for m in ["160", "180", "king"]):
                precio_unitario += reglas.get("king", 30)
                detalles_factura.append("Suplemento King Size: +30€")

        subtotal = precio_unitario * cantidad
        coste_muebles_base += subtotal

        if tarifas.get("necesita_anclaje"):
            anclaje_global = True

        muebles_cotizados.append({
            "item": tarifas.get("display_name", {}).get("es", tipo),
            "cantidad": cantidad,
            "precio_unitario": precio_unitario,
            "subtotal": subtotal
        })

    # 4. LOGÍSTICA
    coste_desplazamiento = 15
    distancia_txt = "Zona Estándar"

    if direccion_cliente:
        try:
            api_key = os.getenv('GOOGLE_API_KEY')
            origin = os.getenv('ORIGIN_ADDRESS')
            if api_key and origin:
                url = "https://maps.googleapis.com/maps/api/distancematrix/json"
                params = {
                    "origins": origin,
                    "destinations": direccion_cliente,
                    "key": api_key
                }
                resp = requests.get(url, params=params, timeout=3)
                data_maps = resp.json()

                if (data_maps['status'] == 'OK' and
                        data_maps['rows'][0]['elements'][0]['status'] == 'OK'):
                    km = data_maps['rows'][0]['elements'][0]['distance']['value'] / 1000
                    distancia_txt = f"{km:.1f} km"
                    if km > 40:
                        coste_desplazamiento = 35
                    elif km > 20:
                        coste_desplazamiento = 25
                    else:
                        coste_desplazamiento = 15
        except (RequestException, Timeout, KeyError, IndexError):
            pass

    # 5. TOTAL Y SUELO
    coste_anclaje = 15 if anclaje_global else 0
    total = coste_muebles_base + coste_extras + coste_desplazamiento + coste_anclaje
    precio_final = max(total, PRECIO_MINIMO)

    return jsonify({
        "status": "success",
        "total_presupuesto": precio_final,
        "desglose": {
            "muebles_cotizados": muebles_cotizados,
            "coste_muebles_base": coste_muebles_base,
            "extras_calculados": coste_extras,
            "coste_desplazamiento": coste_desplazamiento,
            "coste_anclaje_estimado": coste_anclaje,
            "detalles_extras": detalles_factura,
            "distancia_km": distancia_txt
        },
        "necesita_anclaje": anclaje_global,
        "image_urls": image_urls,
        "image_labels": image_labels
    })