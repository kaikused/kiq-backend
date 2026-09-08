"""Rutas HTTP de la calculadora de presupuestos."""
import os
from io import BytesIO
from urllib.parse import quote

from flask import Blueprint, jsonify, request
from google.cloud import vision

from ..email_service import enviar_lead_interno
from ..storage import upload_bytes_to_gcs, upload_image_to_gcs
from .analyzers import detectar_muebles
from .conversion import build_conversion_payload
from .logistics import calcular_desplazamiento
from .pdf import generar_pdf_presupuesto
from .pricing import (
    calcular_presupuesto_items,
    calcular_presupuesto_parcial,
    total_final,
)
from .tarifario import TARIFARIO

calculator_bp = Blueprint("calculator", __name__)

VISION_CLIENT = None
try:
    VISION_CLIENT = vision.ImageAnnotatorClient()
except Exception:  # pylint: disable=broad-exception-caught
    VISION_CLIENT = None


def _parse_input():
    """Extrae descripción, dirección, análisis previo e imágenes del request."""
    image_urls = []
    image_labels = None
    descripcion = ""
    direccion_cliente = None
    analisis_previo = None

    if request.is_json:
        data = request.json
        descripcion = data.get("descripcion_texto_mueble", "")
        direccion_cliente = data.get("direccion_cliente")
        analisis_raw = data.get("analisis")
        if analisis_raw and isinstance(analisis_raw, dict) and "items" in analisis_raw:
            analisis_previo = analisis_raw["items"]
        elif analisis_raw:
            analisis_previo = analisis_raw
        if data.get("image_urls"):
            image_urls = data.get("image_urls")
        if data.get("image_labels"):
            image_labels = data.get("image_labels")
    else:
        descripcion = request.form.get("descripcion_texto_mueble", "")
        direccion_cliente = request.form.get("direccion_cliente")
        files = request.files.getlist("imagen")
        if files and files[0].filename:
            for index, file in enumerate(files):
                if not file:
                    continue
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
                        response = VISION_CLIENT.label_detection(image=image)
                        if not response.error.message:
                            labels = response.label_annotations
                            image_labels = [label.description for label in labels[:5]]
                except Exception as e:  # pylint: disable=broad-exception-caught
                    print(f"Error img {index}: {e}")

    return descripcion, direccion_cliente, analisis_previo, image_urls, image_labels


def _build_clarification_response(resultados, image_urls, image_labels):
    """Respuesta cuando faltan datos — incluye TODAS las preguntas pendientes."""
    preguntas = [
        {"tipo_mueble": item["tipo"], "dato_faltante": item["falta_info"]}
        for item in resultados
        if item.get("falta_info")
    ]
    parcial = calcular_presupuesto_parcial(resultados)
    conversion = build_conversion_payload(
        status="clarification_needed",
        items=resultados,
        preguntas=preguntas,
        presupuesto_parcial=parcial,
    )

    return jsonify({
        "status": "clarification_needed",
        "ACLARACION_REQUERIDA": True,
        "MUEBLE_PROBABLE": preguntas[0]["tipo_mueble"] if preguntas else "desconocido",
        "CAMPOS_FALTANTES": preguntas[0]["dato_faltante"] if preguntas else [],
        "preguntas_pendientes": preguntas,
        "presupuesto_parcial": parcial,
        "analisis": {"items": resultados},
        "conversion": conversion,
        "mensaje": "Se requiere especificar el tamaño o detalles.",
        "image_urls": image_urls,
        "image_labels": image_labels,
    }), 200


@calculator_bp.route("/calcular_presupuesto", methods=["POST"])
def calcular_presupuesto():
    """Endpoint principal para cálculo de presupuestos."""
    descripcion, direccion, analisis_previo, image_urls, image_labels = _parse_input()

    if analisis_previo:
        muebles_procesados = analisis_previo
    else:
        muebles_procesados = detectar_muebles(descripcion, image_labels)

        if not muebles_procesados:
            conversion = build_conversion_payload(status="unknown")
            return jsonify({
                "status": "unknown",
                "ACLARACION_REQUERIDA": True,
                "MUEBLE_PROBABLE": "desconocido",
                "mensaje": "No entiendo qué mueble es.",
                "conversion": conversion,
                "image_urls": image_urls,
                "image_labels": image_labels,
            }), 200

        if len(muebles_procesados) == 1 and muebles_procesados[0].get("tipo") == "saludo":
            return jsonify({
                "status": "greeting",
                "ACLARACION_REQUERIDA": True,
                "MUEBLE_PROBABLE": "saludo",
                "mensaje": "Saludo detectado.",
                "conversion": build_conversion_payload(status="unknown"),
            }), 200

        if any(item.get("falta_info") for item in muebles_procesados):
            return _build_clarification_response(muebles_procesados, image_urls, image_labels)

    presupuesto = calcular_presupuesto_items(muebles_procesados)
    logistica = calcular_desplazamiento(direccion)
    totales = total_final(
        presupuesto["coste_muebles_base"],
        presupuesto["coste_extras"],
        logistica["coste_desplazamiento"],
        presupuesto["anclaje_global"],
    )

    conversion = build_conversion_payload(
        status="success",
        items=muebles_procesados,
        total=totales["total_presupuesto"],
    )

    return jsonify({
        "status": "success",
        "total_presupuesto": totales["total_presupuesto"],
        "analisis": {
            "necesita_anclaje_general": presupuesto["anclaje_global"],
            "items": muebles_procesados,
        },
        "desglose": {
            "muebles_cotizados": presupuesto["muebles_cotizados"],
            "coste_muebles_base": presupuesto["coste_muebles_base"],
            "extras_calculados": presupuesto["coste_extras"],
            "coste_desplazamiento": logistica["coste_desplazamiento"],
            "coste_anclaje_estimado": totales["coste_anclaje"],
            "detalles_extras": presupuesto["detalles_factura"],
            "distancia_km": logistica["distancia_km"],
        },
        "necesita_anclaje": presupuesto["anclaje_global"],
        "conversion": conversion,
        "image_urls": image_urls,
        "image_labels": image_labels,
    })


@calculator_bp.route("/calcular_presupuesto/tarifario", methods=["GET"])
def get_tarifario_publico():
    """
    Tarifario público para el frontend.
    Permite mostrar precios 'desde X€' sin llamar a la calculadora completa.
    """
    items = [
        {
            "tipo": key,
            "nombre": data["display_name"]["es"],
            "precio_desde": data["precio_base"],
            "necesita_anclaje": data.get("necesita_anclaje", False),
        }
        for key, data in TARIFARIO.items()
    ]
    return jsonify({
        "status": "success",
        "items": sorted(items, key=lambda x: x["precio_desde"]),
        "conversion": build_conversion_payload(status="unknown"),
    })


@calculator_bp.route("/enviar_presupuesto", methods=["POST"])
def enviar_presupuesto():
    """Genera PDF, lo envía a fqvdo7@gmail.com y abre WhatsApp con el resumen."""
    data = request.get_json(silent=True) or {}
    nombre = (data.get("nombre") or "Cliente").strip()
    email = (data.get("email") or "").strip()
    telefono = (data.get("telefono") or "").strip()
    precio = data.get("precio_calculado") or 0

    pdf_bytes = generar_pdf_presupuesto(data)
    pdf_url = None
    try:
        pdf_url = upload_bytes_to_gcs(
            pdf_bytes,
            "presupuesto-kiq.pdf",
            folder="cotizaciones",
        )
    except Exception as gcs_error:  # pylint: disable=broad-exception-caught
        print(f"❌ No se pudo subir el PDF a Google Storage: {gcs_error}")

    leads_email = os.getenv("LEADS_EMAIL", "fqvdo7@gmail.com")
    whatsapp_kiq = os.getenv("WHATSAPP_KIQ", "34664497889")

    extra = (
        f"<p>Email cliente: {email or '—'}</p>"
        f"<p>Teléfono: {telefono or '—'}</p>"
        f"<p>Zona: {data.get('direccion') or '—'}</p>"
        f"<p>Descripción: {data.get('descripcion') or '—'}</p>"
        f"<p>PDF: {pdf_url or 'adjunto'}</p>"
    )

    enviado_ok = enviar_lead_interno(leads_email, nombre, precio, pdf_bytes, extra)
    print(f"📧 Lead interno a {leads_email}: {enviado_ok} | pdf_url={pdf_url}")

    mensaje_wa = (
        f"Hola, soy {nombre}. He pedido un presupuesto de montaje en Kiq.\n"
        f"Total estimado: {precio}€\n"
        f"Zona: {data.get('direccion') or 'pendiente'}\n"
        f"Qué montar: {data.get('descripcion') or 'muebles'}\n"
    )
    if pdf_url:
        mensaje_wa += f"PDF: {pdf_url}\n"
    else:
        mensaje_wa += "El PDF te lo enviamos por correo a Kiq.\n"
    whatsapp_url = f"https://wa.me/{whatsapp_kiq}?text={quote(mensaje_wa)}"

    return jsonify({
        "status": "success",
        "enviado_interno": enviado_ok,
        "pdf_url": pdf_url,
        "whatsapp_url": whatsapp_url,
    })
