"""
Módulo de calculadora de presupuestos para Kiq Montajes.
Versión: LÓGICA ANTI-VAGOS (Estricta para Armarios y Canapés).
Corregido para cumplir con estándares Pylint (PEP 8).
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
except Exception as e:  # pylint: disable=broad-exception-caught
    print(f"⚠️ Error desconocido Vision Client: {e}")

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:  # pylint: disable=broad-exception-caught
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
        "precio_base": 50,  # Precio para MEDIANO (135/150)
        "necesita_anclaje": False,
        "display_name": {"es": "Canapé Abatible"},
        "reglas_precio": {
            # Ajustes según tamaño
            "pequeno": -10,  # 90cm, 105cm
            "grande": 20     # 160cm, 180cm, 200cm
        }
    },
    "cama": {
        "precio_base": 50,
        "necesita_anclaje": False,
        "keywords": ["cama", "somier"],
        "display_name": {"es": "Cama"},
        "reglas_precio": {
            "pequeno": -10,
            "grande": 20
        }
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


# --- CEREBRO IA ESTRICTO (ANTI-VAGOS) ---
def analizar_con_gemini_estricto(texto_usuario):
    """
    Usa Gemini para extraer datos. Es ESTRICTO: Si falta info, la pide.
    """
    try:
        if not GEMINI_API_KEY:
            return None

        keys_muebles = list(TARIFARIO.keys())

        # PROMPT MODIFICADO PARA EXIGIR MEDIDA
        prompt = f"""
Especialista: Eres un experto cotizador. Analiza el texto.
CATÁLOGO: {keys_muebles}

OBJETIVOS:
1. Si el usuario SOLO saluda y NO pide muebles -> {{ "tipo": "saludo", "cantidad": 0 }}

2. Si menciona muebles, extrae datos (MODO ESTRICTO):
   - ARMARIOS:
     * ¿Tipo puerta? (corredera/batiente). SI FALTA -> "falta_info": ["tipo_puerta"].
     * ¿Cantidad puertas? SI FALTA -> "falta_info": ["num_puertas"].

   - CANAPÉS / CAMAS:
     * ¿Medida explícita? (90, 105, 135, 150, 180, pequeño, grande...).
     * SI NO DICE LA MEDIDA -> Debes añadir "falta_info": ["medida"].
     * NO asumas medidas estándar. El cliente DEBE especificar.

ESTRUCTURA JSON:
[
    {{
        "tipo": "canape",
        "cantidad": 1,
        "atributos": {{
            "medida": null
        }},
        "falta_info": ["medida"]
    }}
]

TEXTO CLIENTE: "{texto_usuario}"
Responde SOLO con JSON.
"""
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)

        texto_limpio = response.text.replace('```json', '').replace('```', '').strip()
        datos = json.loads(texto_limpio)

        if isinstance(datos, dict):
            datos = [datos]
        return datos

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"⚠️ Error Gemini Estricto: {e}")
        return None


# --- FALLBACK: SPACY + REGEX (ANTI-VAGOS) ---
def analizar_con_spacy_basico(descripcion):
    """
    Respaldo híbrido. Si Regex no encuentra el dato, lo marca como faltante.
    """
    nlp = get_nlp_model()
    if not nlp:
        return []

    doc = nlp(descripcion.lower())
    detectados = []
    texto_lower = descripcion.lower()

    for token in doc:
        if token.i > 0 and token.lemma_ == doc[token.i - 1].lemma_:
            continue

        for key, data in TARIFARIO.items():
            if token.lemma_ in data["keywords"] or token.text in data["keywords"]:

                item = {
                    "tipo": key,
                    "cantidad": 1,
                    "atributos": {},
                    "falta_info": []
                }

                # LOGICA ARMARIO
                if key == "armario":
                    if re.search(r'corredera|deslizante', texto_lower):
                        item["atributos"]["tipo_puerta"] = "corredera"
                    elif re.search(r'batiente|bisagra|abrir', texto_lower):
                        item["atributos"]["tipo_puerta"] = "batiente"
                    else:
                        item["falta_info"].append("tipo_puerta")

                    nums = re.findall(r'\d+', texto_lower)
                    if nums:
                        item["atributos"]["num_puertas"] = int(nums[0])
                    elif "dos" in texto_lower:
                        item["atributos"]["num_puertas"] = 2
                    elif "tres" in texto_lower:
                        item["atributos"]["num_puertas"] = 3
                    elif "cuatro" in texto_lower:
                        item["atributos"]["num_puertas"] = 4
                    else:
                        item["falta_info"].append("num_puertas")

                # LOGICA CANAPÉ / CAMA (ESTRICTA)
                elif key == "canape" or key == "cama":
                    # Buscamos medidas explícitas. Dividimos regex para cumplir longitud
                    regex_medidas = (
                        r'90|105|135|150|160|180|200|king|matrimonio|'
                        r'individual|pequeño|grande|mediano'
                    )
                    match_medida = re.search(regex_medidas, texto_lower)

                    if match_medida:
                        item["atributos"]["medida"] = match_medida.group(0)
                    else:
                        # ¡AQUÍ ESTÁ LA CLAVE! Si no hay medida, reportamos falta_info
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
    analisis_previo = None

    if request.is_json:
        data = request.json
        descripcion = data.get('descripcion_texto_mueble', '')
        direccion_cliente = data.get('direccion_cliente')
        analisis_raw = data.get('analisis')
        if analisis_raw and isinstance(analisis_raw, dict) and 'items' in analisis_raw:
            analisis_previo = analisis_raw['items']
        elif analisis_raw:
            analisis_previo = analisis_raw

        if data.get('image_urls'):
            image_urls = data.get('image_urls')
        if data.get('image_labels'):
            image_labels = data.get('image_labels')

    else:
        # FormData (subida de archivos)
        descripcion = request.form.get('descripcion_texto_mueble', '')
        direccion_cliente = request.form.get('direccion_cliente')
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
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        print(f"Error img {index}: {e}")

    # 2. PROCESAMIENTO
    muebles_procesados = []

    if analisis_previo:
        muebles_procesados = analisis_previo
    else:
        # Análisis inicial
        resultados = analizar_con_gemini_estricto(descripcion)
        if not resultados:
            resultados = analizar_con_spacy_basico(descripcion)

        if not resultados:
            return jsonify({
                "ACLARACION_REQUERIDA": True,
                "MUEBLE_PROBABLE": "desconocido",
                "mensaje": "No entiendo qué mueble es."
            }), 422

        if len(resultados) == 1 and resultados[0].get("tipo") == "saludo":
            return jsonify({
                "ACLARACION_REQUERIDA": True,
                "MUEBLE_PROBABLE": "saludo",
                "mensaje": "Saludo detectado."
            }), 422

        # --- FILTRO ANTI-VAGOS ---
        # Si falta info (como "medida"), paramos y pedimos aclaración.
        preguntas_necesarias = []
        for item in resultados:
            if item.get("falta_info"):
                preguntas_necesarias.append({
                    "tipo_mueble": item["tipo"],
                    "dato_faltante": item["falta_info"]  # Aquí irá ["medida"]
                })

        if preguntas_necesarias:
            # Retornamos 422 con los datos faltantes para que el Frontend dibuje los botones
            return jsonify({
                "ACLARACION_REQUERIDA": True,
                "MUEBLE_PROBABLE": preguntas_necesarias[0]["tipo_mueble"],
                "CAMPOS_FALTANTES": preguntas_necesarias[0]["dato_faltante"],
                "mensaje": "Se requiere especificar el tamaño o detalles."
            }), 422

        muebles_procesados = resultados

    # 3. CÁLCULO DE PRECIO
    coste_muebles_base = 0
    coste_extras = 0
    detalles_factura = []
    anclaje_global = False
    muebles_cotizados = []

    for item in muebles_procesados:
        tipo = item.get("tipo", "otro")
        cantidad = int(item.get("cantidad", 1))
        attrs = item.get("atributos", {})

        tarifas = TARIFARIO.get(tipo, {"precio_base": 40, "necesita_anclaje": False})
        precio_unitario = tarifas.get("precio_base", 40)
        reglas = tarifas.get("reglas_precio", {})

        # --- LÓGICA DE PRECIOS SEGÚN ATRIBUTOS ---

        # A) ARMARIOS
        if tipo == "armario":
            tipo_puerta = attrs.get("tipo_puerta", "batiente")
            if "corredera" in str(tipo_puerta).lower():
                suplemento = reglas.get("suplemento_corredera", 20)
                precio_unitario += suplemento
                detalles_factura.append(f"Suplemento Puertas Correderas: +{suplemento}€")

            num_puertas = attrs.get("num_puertas", 2)
            if isinstance(num_puertas, (int, float)) and num_puertas > 2:
                extra_puertas = (num_puertas - 2) * reglas.get("puerta_extra", 30)
                coste_extras += extra_puertas
                detalles_factura.append(f"Extra tamaño ({num_puertas} puertas): +{extra_puertas}€")

        # B) CANAPÉS Y CAMAS (Lógica de Medidas)
        elif tipo in ["canape", "cama"]:
            medida = str(attrs.get("medida", "mediano")).lower()

            # Clasificación de medidas en 3 grupos
            es_pequeno = any(m in medida for m in ["90", "105", "individual", "pequeño", "pequeno"])
            es_grande = any(m in medida for m in ["160", "180", "200", "king", "grande"])

            if es_pequeno:
                descuento = reglas.get("pequeno", -10)
                precio_unitario += descuento
                detalles_factura.append("Medida pequeña (90/105): -10€")
            elif es_grande:
                suplemento = reglas.get("grande", 20)
                precio_unitario += suplemento
                detalles_factura.append("Medida grande/King: +20€")
            # Si es mediano (135/150), no se toca el precio base.

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

    # 5. TOTAL
    coste_anclaje = 15 if anclaje_global else 0
    total = coste_muebles_base + coste_extras + coste_desplazamiento + coste_anclaje
    precio_final = max(total, PRECIO_MINIMO)

    return jsonify({
        "status": "success",
        "total_presupuesto": precio_final,
        "analisis": {
            "necesita_anclaje_general": anclaje_global,
            "items": muebles_procesados
        },
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