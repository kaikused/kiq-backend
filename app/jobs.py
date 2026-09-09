"""
Puente cotización → trabajo de tablero.

El funnel vivo (PDF + WhatsApp) no llama a esto todavía.
Cuando toque el marketplace, el único cable es:

    from app.jobs import payload_desde_presupuesto, crear_trabajo_pendiente
    trabajo = crear_trabajo_pendiente(cliente_id, payload_desde_presupuesto(data))

No uses /api/cliente/publicar-trabajo (deja el job en 'cotizacion' para cobrar
en la app). Ese modelo está obsoleto.
"""
from app.extensions import db
from app.models import Trabajo


def payload_desde_presupuesto(data: dict) -> dict:
    """Normaliza el JSON de la calculadora / enviar_presupuesto."""
    return {
        "descripcion": (data.get("descripcion") or data.get("descripcion_texto_mueble") or "").strip(),
        "direccion": (data.get("direccion") or data.get("direccion_cliente") or "").strip(),
        "precio_calculado": float(data.get("precio_calculado") or data.get("total_presupuesto") or 0),
        "imagenes_urls": data.get("imagenes") or data.get("imagenes_urls") or [],
        "desglose": data.get("desglose"),
        "etiquetas": data.get("etiquetas") or {},
    }


def crear_trabajo_pendiente(cliente_id: int, payload: dict) -> Trabajo:
    """Crea un trabajo que el montador ve en Disponibles. Sin cobro in-app."""
    descripcion = payload.get("descripcion") or ""
    direccion = payload.get("direccion") or ""
    if not descripcion or not direccion:
        raise ValueError("Faltan descripcion o direccion")

    trabajo = Trabajo(
        descripcion=descripcion,
        direccion=direccion,
        precio_calculado=float(payload.get("precio_calculado") or 0),
        cliente_id=int(cliente_id),
        estado="pendiente",
        imagenes_urls=payload.get("imagenes_urls") or [],
        etiquetas=payload.get("etiquetas") or {},
        desglose=payload.get("desglose"),
        metodo_pago="efectivo_gemas",
    )
    db.session.add(trabajo)
    db.session.commit()
    return trabajo
