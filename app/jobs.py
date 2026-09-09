"""
Cotización → inbox admin.

Visitante (sin cuenta): ficha de lead, PDF, WhatsApp. No sale al tablero.
Cliente con cuenta: igual, y el admin puede publicar al tablero de montadores.

    from app.jobs import crear_trabajo_desde_presupuesto
    trabajo = crear_trabajo_desde_presupuesto(data, cliente_id=...)

No uses /api/cliente/publicar-trabajo (modelo de cobro in-app, obsoleto).
"""
from datetime import datetime
import json
import secrets
import uuid

from app.extensions import db
from app.models import Cliente, Trabajo


def zona_desde_direccion(direccion):
    """Primera parte de la dirección, para filtrar montadores."""
    d = (direccion or "").strip()
    if not d:
        return None
    return d.split(",")[0].strip()[:120] or None


def parse_fecha_visita(valor):
    if not valor:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    try:
        if texto.endswith("Z"):
            texto = texto[:-1]
        return datetime.fromisoformat(texto)
    except ValueError:
        return None


def payload_desde_presupuesto(data: dict) -> dict:
    """Normaliza el JSON de la calculadora / enviar_presupuesto."""
    return {
        "descripcion": (data.get("descripcion") or data.get("descripcion_texto_mueble") or "").strip(),
        "direccion": (data.get("direccion") or data.get("direccion_cliente") or "").strip(),
        "precio_calculado": float(data.get("precio_calculado") or data.get("total_presupuesto") or 0),
        "imagenes_urls": data.get("imagenes") or data.get("imagenes_urls") or [],
        "desglose": data.get("desglose"),
        "etiquetas": data.get("etiquetas") or {},
        "carpeta_gcs": data.get("carpeta_gcs") or "",
    }


def _etiquetas_inbox(raw, origen_invitado=False):
    if isinstance(raw, dict):
        tags = dict(raw)
    elif isinstance(raw, list):
        tags = {"vision": raw}
    else:
        tags = {}
    if origen_invitado:
        tags["origen"] = "invitado"
    return tags


def ficha_es_invitado(trabajo: Trabajo) -> bool:
    tags = trabajo.etiquetas
    if isinstance(tags, dict) and tags.get("origen") == "invitado":
        return True
    cliente = Cliente.query.get(trabajo.cliente_id)
    return bool(cliente and getattr(cliente, "es_invitado", False))


def asegurar_cliente_para_presupuesto(data: dict):
    """Cliente con cuenta (si el email existe) o lead invitado (sin login)."""
    email = (data.get("email") or "").strip().lower()
    nombre = (data.get("nombre") or "Visitante").strip() or "Visitante"
    telefono = (data.get("telefono") or "").strip()[:20]
    if email:
        existente = Cliente.query.filter_by(email=email).first()
        if existente:
            if telefono and not existente.telefono:
                existente.telefono = telefono
            if nombre and existente.nombre in ("Cliente", "Visitante", "cliente"):
                existente.nombre = nombre[:100]
            return existente, bool(getattr(existente, "es_invitado", False))

    cliente = Cliente(
        nombre=nombre[:100],
        email=email or f"invitado.{uuid.uuid4().hex}@leads.kiq.local",
        telefono=telefono or None,
        es_invitado=True,
    )
    cliente.set_password(secrets.token_urlsafe(24))
    db.session.add(cliente)
    db.session.flush()
    return cliente, True


def crear_trabajo_desde_presupuesto(data: dict, cliente_id=None) -> Trabajo:
    """Inbox para cuenta o visitante. El visitante no se publica al tablero."""
    payload = payload_desde_presupuesto(data)
    invitado = False
    if cliente_id:
        cid = int(cliente_id)
    else:
        cliente, invitado = asegurar_cliente_para_presupuesto(data)
        cid = cliente.id
    payload["etiquetas"] = _etiquetas_inbox(payload.get("etiquetas"), origen_invitado=invitado)
    return crear_trabajo_inbox(cid, payload)


def crear_trabajo_inbox(cliente_id: int, payload: dict) -> Trabajo:
    """Borrador solo para el admin. No sale al tablero hasta publicar."""
    descripcion = (payload.get("descripcion") or "").strip() or "Montaje"
    direccion = (payload.get("direccion") or "a confirmar").strip()[:200]

    trabajo = Trabajo(
        descripcion=descripcion,
        direccion=direccion,
        precio_calculado=float(payload.get("precio_calculado") or 0),
        cliente_id=int(cliente_id),
        estado="cotizacion",
        imagenes_urls=payload.get("imagenes_urls") or [],
        etiquetas=payload.get("etiquetas") or {},
        desglose=payload.get("desglose"),
        metodo_pago="efectivo",
        cobrado=False,
        zona=zona_desde_direccion(direccion),
        pdf_carpeta=(payload.get("carpeta_gcs") or "").strip() or None,
    )
    db.session.add(trabajo)
    db.session.commit()
    return trabajo


def crear_trabajo_pendiente(cliente_id: int, payload: dict) -> Trabajo:
    """Crea un trabajo ya publicado. Preferible pasar por inbox + publicar."""
    trabajo = crear_trabajo_inbox(cliente_id, payload)
    return publicar_trabajo(trabajo)


def confirmar_trabajo_visitante(trabajo: Trabajo) -> Trabajo:
    """Visitante: Kiq acepta el montaje. No sale al tablero de montadores."""
    if not ficha_es_invitado(trabajo):
        raise ValueError("Solo cotizaciones de visitante")
    if trabajo.estado != "cotizacion":
        raise ValueError("Solo se puede confirmar una cotización en revisión")
    if not (trabajo.descripcion or "").strip():
        raise ValueError("Falta la descripción")
    trabajo.estado = "aceptado"
    trabajo.montador_id = None
    db.session.commit()
    return trabajo


def publicar_trabajo(trabajo: Trabajo) -> Trabajo:
    """Cuenta: al tablero. Visitante: Kiq confirma (aceptado, por WhatsApp)."""
    if ficha_es_invitado(trabajo):
        return confirmar_trabajo_visitante(trabajo)
    if trabajo.estado != "cotizacion":
        raise ValueError("Solo se puede publicar una cotización en revisión")
    direccion = (trabajo.direccion or "").strip()
    if not direccion or direccion.lower() == "a confirmar":
        raise ValueError("Falta la dirección")
    if not (trabajo.descripcion or "").strip():
        raise ValueError("Falta la descripción")
    if float(trabajo.precio_calculado or 0) <= 0:
        raise ValueError("El precio tiene que ser mayor que 0")
    trabajo.estado = "pendiente"
    trabajo.montador_id = None
    db.session.commit()
    return trabajo


def metodo_cobro_publico(valor):
    """bizum | efectivo. stripe/gemas viejos no cuentan como método MVP."""
    v = (valor or "").strip().lower()
    if v == "bizum":
        return "bizum"
    if v in ("efectivo", "efectivo_gemas", "cash"):
        return "efectivo"
    return None


def aplicar_cobro(trabajo: Trabajo, data: dict) -> None:
    """Actualiza método (Bizum/efectivo) y si está cobrado."""
    if "metodo_pago" in data and data.get("metodo_pago") is not None:
        metodo = metodo_cobro_publico(data.get("metodo_pago"))
        if metodo:
            trabajo.metodo_pago = metodo
    if "cobrado" in data:
        trabajo.cobrado = bool(data.get("cobrado"))
    if "zona" in data and data.get("zona") is not None:
        trabajo.zona = (data.get("zona") or "").strip()[:120] or None
    if "fecha_visita" in data:
        trabajo.fecha_visita = parse_fecha_visita(data.get("fecha_visita"))


ESTADOS_ADMIN = (
    "cotizacion",
    "pendiente",
    "aceptado",
    "revision_cliente",
    "completado",
    "cancelado",
    "cancelado_incidencia",
)


def aplicar_estado(trabajo: Trabajo, estado):
    """El admin puede cerrar o reabrir un trabajo."""
    est = (estado or "").strip()
    if est not in ESTADOS_ADMIN:
        raise ValueError("Estado no válido")
    if ficha_es_invitado(trabajo) and est == "pendiente":
        est = "aceptado"
    trabajo.estado = est
    if est in ("cotizacion", "pendiente"):
        trabajo.montador_id = None


def _carpeta_pdf(trabajo, nombre):
    from app.storage import nueva_carpeta_cotizacion
    raw = (getattr(trabajo, "pdf_carpeta", None) or "").strip()
    if not raw:
        return nueva_carpeta_cotizacion(nombre or "cliente")
    if raw.startswith("cotizaciones/"):
        return raw
    return f"cotizaciones/{raw}"


def regenerar_pdf_trabajo(trabajo):
    """Vuelve a generar el PDF con los datos actuales y lo pisa en GCS."""
    from app.calculator.pdf import generar_pdf_presupuesto
    from app.storage import upload_bytes_to_gcs, url_foto_almacenada

    cliente = Cliente.query.get(trabajo.cliente_id)
    desglose = trabajo.desglose or {}
    if isinstance(desglose, str):
        try:
            desglose = json.loads(desglose)
        except json.JSONDecodeError:
            desglose = {}

    nombre = (cliente.nombre if cliente else "") or "Cliente"
    zona = (getattr(trabajo, "zona", None) or "").strip()
    direccion = trabajo.direccion or ""
    if zona and zona.lower() not in direccion.lower():
        direccion = f"{direccion} ({zona})".strip()
    payload = {
        "nombre": nombre,
        "email": cliente.email if cliente else "",
        "telefono": cliente.telefono if cliente else "",
        "direccion": direccion,
        "descripcion": trabajo.descripcion,
        "precio_calculado": trabajo.precio_calculado,
        "fecha_visita": getattr(trabajo, "fecha_visita", None),
        "metodo_pago": trabajo.metodo_pago,
        "cobrado": bool(getattr(trabajo, "cobrado", False)),
        "desglose": desglose,
        "imagenes": [
            url_foto_almacenada(u) or u for u in (trabajo.imagenes_urls or [])
        ],
        "consulta_manual": False,
    }
    pdf_bytes = generar_pdf_presupuesto(payload)
    carpeta = _carpeta_pdf(trabajo, nombre)
    upload_bytes_to_gcs(
        pdf_bytes,
        "presupuesto-kiq.pdf",
        folder=carpeta,
        content_type="application/pdf",
        unique_name=False,
    )
    trabajo.pdf_carpeta = carpeta
    return carpeta


def armar_presupuesto_manual(data: dict):
    """Tarifario + desplazamiento a partir de líneas de formulario admin."""
    from app.calculator.logistics import calcular_desplazamiento
    from app.calculator.pricing import calcular_presupuesto_items, total_final
    from app.calculator.tarifario import TARIFARIO

    lineas = data.get("items") or []
    items = []
    for linea in lineas:
        tipo = (linea.get("tipo") or "").strip()
        if tipo not in TARIFARIO:
            continue
        try:
            cantidad = max(1, int(linea.get("cantidad") or 1))
        except (TypeError, ValueError):
            cantidad = 1
        if tipo == "otros":
            try:
                precio = float(linea.get("precio") or 0)
            except (TypeError, ValueError):
                precio = 0.0
            if precio <= 0:
                continue
            concepto = (linea.get("concepto") or "").strip() or "Otros"
            items.append({
                "tipo": "otros",
                "cantidad": cantidad,
                "atributos": {"precio_unitario": precio, "concepto": concepto[:80]},
            })
            continue
        attrs = {}
        if tipo == "armario":
            attrs["tipo_puerta"] = (linea.get("tipo_puerta") or "batiente").strip()
            try:
                attrs["num_puertas"] = int(linea.get("num_puertas") or 2)
            except (TypeError, ValueError):
                attrs["num_puertas"] = 2
        if tipo in ("canape", "cama"):
            medida = linea.get("medida")
            if medida:
                attrs["medida"] = str(medida)
        items.append({"tipo": tipo, "cantidad": cantidad, "atributos": attrs})

    if not items:
        raise ValueError("Añade al menos un mueble del tarifario")

    presupuesto = calcular_presupuesto_items(items)
    direccion = (data.get("direccion") or data.get("zona") or "").strip()
    logistica = calcular_desplazamiento(direccion)
    anclaje = presupuesto["anclaje_global"]
    if data.get("anclaje") is not None:
        anclaje = bool(data.get("anclaje"))
    totales = total_final(
        presupuesto["coste_muebles_base"],
        presupuesto["coste_extras"],
        logistica["coste_desplazamiento"],
        anclaje,
        consulta=False,
    )
    nombres = [
        f"{it['cantidad']}x {it['item']}" for it in presupuesto["muebles_cotizados"]
    ]
    descripcion = (data.get("descripcion") or "").strip() or ", ".join(nombres)
    desglose = {
        "muebles_cotizados": presupuesto["muebles_cotizados"],
        "coste_muebles_base": presupuesto["coste_muebles_base"],
        "extras_calculados": presupuesto["coste_extras"],
        "coste_desplazamiento": logistica["coste_desplazamiento"],
        "coste_anclaje_estimado": totales["coste_anclaje"],
        "detalles_extras": presupuesto["detalles_factura"],
        "distancia_km": logistica["distancia_km"],
        "consulta_manual": False,
        "origen": "admin_manual",
    }
    preview = {
        "total": totales["total_presupuesto"],
        "desplazamiento": logistica["coste_desplazamiento"],
        "distancia_km": logistica["distancia_km"],
        "anclaje": totales["coste_anclaje"],
        "muebles": presupuesto["coste_muebles_base"],
        "extras": presupuesto["coste_extras"],
        "lineas": presupuesto["muebles_cotizados"],
        "detalles": presupuesto["detalles_factura"],
        "descripcion": descripcion,
    }
    payload = {
        "nombre": (data.get("nombre") or "Visitante").strip() or "Visitante",
        "email": (data.get("email") or "").strip(),
        "telefono": (data.get("telefono") or "").strip(),
        "descripcion": descripcion,
        "direccion": direccion or "a confirmar",
        "precio_calculado": totales["total_presupuesto"],
        "desglose": desglose,
        "imagenes": [],
        "etiquetas": {"origen": "invitado", "canal": "telefono"},
    }
    return preview, payload
