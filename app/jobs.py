"""
Cotización logueada → inbox admin → tablero.

El visitante (sin cuenta) no pasa por aquí: solo PDF + WhatsApp.

    from app.jobs import payload_desde_presupuesto, crear_trabajo_inbox
    trabajo = crear_trabajo_inbox(cliente_id, payload_desde_presupuesto(data))

Publicar (solo admin) pasa de cotizacion a pendiente (visible a montadores).
No uses /api/cliente/publicar-trabajo (modelo de cobro in-app, obsoleto).
"""
from datetime import datetime

from app.extensions import db
from app.models import Trabajo


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


def publicar_trabajo(trabajo: Trabajo) -> Trabajo:
    """Pasa el borrador al tablero (pendiente, sin montador)."""
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
    trabajo.estado = est
    if est in ("cotizacion", "pendiente"):
        trabajo.montador_id = None
