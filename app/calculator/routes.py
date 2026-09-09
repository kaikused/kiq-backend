"""Rutas HTTP de la calculadora de presupuestos."""
import os
from urllib.parse import quote

from flask import Blueprint, jsonify, redirect, request
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request
from google.cloud import vision

from ..email_service import enviar_lead_interno
from ..storage import (
    codigo_desde_carpeta,
    comprimir_imagen,
    nueva_carpeta_cotizacion,
    carpeta_valida,
    signed_url_for_blob,
    upload_bytes_to_gcs,
)
from .analyzers import alinear_con_pedido, detectar_muebles, es_pedido_fuera_de_tarifario, item_consulta
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


@calculator_bp.route("/health", methods=["GET"])
def health():
    """Ping ligero para despertar el servidor en Render."""
    return jsonify({"ok": True}), 200


def _get_vision_client():
    """Vision después de cargar credenciales (no al importar el módulo)."""
    try:
        from ..storage import get_google_credentials
        get_google_credentials()
        return vision.ImageAnnotatorClient()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"⚠️ Vision client no disponible: {exc}")
        return None


def _parse_input():
    """Extrae descripción, dirección, análisis previo e imágenes del request."""
    image_urls = []
    image_labels = None
    descripcion = ""
    direccion_cliente = None
    analisis_previo = None
    nombre = "cliente"
    carpeta = None

    if request.is_json:
        data = request.json
        descripcion = data.get("descripcion_texto_mueble", "")
        direccion_cliente = data.get("direccion_cliente")
        nombre = (data.get("client_name") or data.get("nombre") or "cliente").strip()
        carpeta = data.get("carpeta_gcs")
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
        nombre = (request.form.get("client_name") or request.form.get("nombre") or "cliente").strip()
        carpeta = request.form.get("carpeta_gcs")
        files = request.files.getlist("imagen")
        if files and files[0].filename:
            if not carpeta:
                carpeta = nueva_carpeta_cotizacion(nombre)
            for index, file in enumerate(files):
                if not file:
                    continue
                try:
                    file_content = file.read()
                    if not file_content:
                        print(f"⚠️ Imagen {index} vacía (stream consumido o archivo 0 bytes)")
                        continue

                    if index == 0:
                        vision_client = _get_vision_client()
                        if vision_client:
                            image = vision.Image(content=file_content)
                            response = vision_client.label_detection(image=image)
                            if not response.error.message:
                                image_labels = [
                                    label.description for label in response.label_annotations[:5]
                                ]

                    comprimida, ctype, fname = comprimir_imagen(
                        file_content,
                        file.filename or f"foto-{index + 1}.jpg",
                    )
                    gcs_url, _blob = upload_bytes_to_gcs(
                        comprimida,
                        f"foto-{index + 1}.jpg",
                        folder=carpeta,
                        content_type=ctype,
                        unique_name=False,
                    )
                    if gcs_url:
                        image_urls.append(gcs_url)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    print(f"❌ Error img {index}: {e}")

    if not carpeta:
        carpeta = nueva_carpeta_cotizacion(nombre)
    return descripcion, direccion_cliente, analisis_previo, image_urls, image_labels, carpeta


def _build_clarification_response(resultados, image_urls, image_labels, carpeta):
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
        "carpeta_gcs": carpeta,
    }), 200


@calculator_bp.route("/calcular_presupuesto", methods=["POST"])
def calcular_presupuesto():
    """Endpoint principal para cálculo de presupuestos."""
    descripcion, direccion, analisis_previo, image_urls, image_labels, carpeta = _parse_input()

    consulta_manual = False

    if analisis_previo:
        muebles_procesados = alinear_con_pedido(descripcion, analisis_previo)
        consulta_manual = any(item.get("tipo") == "consulta" for item in muebles_procesados)
    else:
        muebles_procesados = alinear_con_pedido(
            descripcion,
            detectar_muebles(descripcion, image_labels),
        )

        if len(muebles_procesados) == 1 and muebles_procesados[0].get("tipo") == "saludo":
            return jsonify({
                "status": "greeting",
                "ACLARACION_REQUERIDA": True,
                "MUEBLE_PROBABLE": "saludo",
                "mensaje": "Saludo detectado.",
                "conversion": build_conversion_payload(status="unknown"),
                "carpeta_gcs": carpeta,
            }), 200

        if es_pedido_fuera_de_tarifario(descripcion) or (
            not muebles_procesados and (descripcion or "").strip()
        ):
            muebles_procesados = [item_consulta(descripcion)]
            consulta_manual = True
        elif not muebles_procesados:
            conversion = build_conversion_payload(status="unknown")
            return jsonify({
                "status": "unknown",
                "ACLARACION_REQUERIDA": True,
                "MUEBLE_PROBABLE": "desconocido",
                "mensaje": "No entiendo qué mueble es.",
                "conversion": conversion,
                "image_urls": image_urls,
                "image_labels": image_labels,
                "carpeta_gcs": carpeta,
            }), 200

        if not consulta_manual and any(item.get("falta_info") for item in muebles_procesados):
            return _build_clarification_response(
                muebles_procesados, image_urls, image_labels, carpeta
            )

    consulta_manual = consulta_manual or any(
        item.get("tipo") == "consulta" for item in muebles_procesados
    )
    presupuesto = calcular_presupuesto_items(muebles_procesados)
    logistica = calcular_desplazamiento(direccion)
    totales = total_final(
        presupuesto["coste_muebles_base"],
        presupuesto["coste_extras"],
        logistica["coste_desplazamiento"],
        presupuesto["anclaje_global"],
        consulta=consulta_manual,
    )

    conversion = build_conversion_payload(
        status="consulta_manual" if consulta_manual else "success",
        items=muebles_procesados,
        total=totales["total_presupuesto"],
    )

    return jsonify({
        "status": "consulta_manual" if consulta_manual else "success",
        "consulta_manual": consulta_manual,
        "total_presupuesto": totales["total_presupuesto"],
        "analisis": {
            "necesita_anclaje_general": False if consulta_manual else presupuesto["anclaje_global"],
            "items": muebles_procesados,
        },
        "desglose": {
            "muebles_cotizados": presupuesto["muebles_cotizados"],
            "coste_muebles_base": presupuesto["coste_muebles_base"] if not consulta_manual else 0,
            "extras_calculados": presupuesto["coste_extras"] if not consulta_manual else 0,
            "coste_desplazamiento": 0 if consulta_manual else logistica["coste_desplazamiento"],
            "coste_anclaje_estimado": 0 if consulta_manual else totales["coste_anclaje"],
            "detalles_extras": [] if consulta_manual else presupuesto["detalles_factura"],
            "distancia_km": logistica["distancia_km"],
            "consulta_manual": consulta_manual,
        },
        "necesita_anclaje": False if consulta_manual else presupuesto["anclaje_global"],
        "conversion": conversion,
        "image_urls": image_urls,
        "image_labels": image_labels,
        "carpeta_gcs": carpeta,
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
        if not data.get("solo_admin")
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
    consulta = bool(data.get("consulta_manual") or (data.get("desglose") or {}).get("consulta_manual"))
    precio = data.get("precio_calculado")

    pdf_bytes = generar_pdf_presupuesto(data)
    pdf_url = None
    pdf_corto = None
    gcs_error = None
    carpeta = data.get("carpeta_gcs") or nueva_carpeta_cotizacion(nombre)
    try:
        pdf_url, blob_path = upload_bytes_to_gcs(
            pdf_bytes,
            "presupuesto-kiq.pdf",
            folder=carpeta,
            content_type="application/pdf",
            unique_name=False,
        )
        pdf_corto = _enlace_pdf_corto(carpeta)
        print(f"PDF corto={pdf_corto} blob={blob_path}")
    except Exception as err:  # pylint: disable=broad-exception-caught
        gcs_error = str(err)
        print(f"❌ No se pudo subir el PDF a Google Storage: {gcs_error}")

    leads_email = os.getenv("LEADS_EMAIL", "fqvdo7@gmail.com")
    whatsapp_kiq = os.getenv("WHATSAPP_KIQ", "34664497889")

    extra = (
        f"<p>Email cliente: {email or '—'}</p>"
        f"<p>Teléfono: {telefono or '—'}</p>"
        f"<p>Zona: {data.get('direccion') or '—'}</p>"
        f"<p>Descripción: {data.get('descripcion') or '—'}</p>"
        f"<p>Tipo: {'Consulta manual' if consulta else 'Presupuesto'}</p>"
        f"<p>PDF: {pdf_corto or pdf_url or 'adjunto'}</p>"
    )

    enviado_ok = enviar_lead_interno(
        leads_email,
        nombre,
        "a confirmar" if consulta else precio,
        pdf_bytes,
        extra,
    )
    print(f"📧 Lead interno a {leads_email}: {enviado_ok} | pdf_url={pdf_url}")

    mensaje_wa = (
        f"Hola, soy {nombre}. He pedido un presupuesto de montaje en Kiq.\n"
        f"Zona: {data.get('direccion') or 'pendiente'}\n"
        f"Qué montar: {data.get('descripcion') or 'muebles'}\n"
        "Os escribo para que me confirméis el presupuesto por aquí.\n"
    )
    link_pdf = pdf_corto or pdf_url
    whatsapp_url = f"https://wa.me/{whatsapp_kiq}?text={quote(mensaje_wa)}"

    trabajo_id = None
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        claims = get_jwt() if identity else {}
        cliente_id = int(identity) if identity and claims.get("rol") == "cliente" else None
        from app.jobs import crear_trabajo_desde_presupuesto
        trabajo = crear_trabajo_desde_presupuesto(data, cliente_id=cliente_id)
        trabajo_id = trabajo.id
        print(
            f"Inbox admin trabajo #{trabajo_id} "
            f"({'cliente ' + str(identity) if cliente_id else 'visitante'})"
        )
    except Exception as err:  # pylint: disable=broad-exception-caught
        print(f"No se creó ficha de inbox: {err}")

    return jsonify({
        "status": "success",
        "enviado_interno": enviado_ok,
        "pdf_url": link_pdf,
        "pdf_url_firmada": pdf_url,
        "gcs_error": gcs_error,
        "whatsapp_url": whatsapp_url,
        "trabajo_id": trabajo_id,
    })


def _enlace_pdf_corto(carpeta: str) -> str:
    code = codigo_desde_carpeta(carpeta)
    base = (
        os.getenv("PUBLIC_API_URL")
        or os.getenv("PUBLIC_BASE_URL")
        or "https://kiq-calculadora.onrender.com"
    ).rstrip("/")
    return f"{base}/p/{code}"


@calculator_bp.route("/p/<code>", methods=["GET"])
def abrir_pdf_corto(code):
    """Redirige un enlace corto a una URL firmada de GCS."""
    if not carpeta_valida(code):
        return "Presupuesto no encontrado", 404
    try:
        url = signed_url_for_blob(f"cotizaciones/{code}/presupuesto-kiq.pdf")
        resp = redirect(url)
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"❌ No se pudo abrir PDF corto {code}: {exc}")
        return "No se pudo abrir el PDF", 500
