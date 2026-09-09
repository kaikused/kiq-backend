"""Payloads orientados a conversión para el frontend."""
from .tarifario import TARIFARIO

CAMPO_LABELS = {
    "medida": "la medida",
    "tipo_puerta": "el tipo de puerta",
    "num_puertas": "el número de puertas",
}

SOCIAL_PROOF = "4.8★ en Google · Montadores verificados en Málaga"


def _nombre_mueble(tipo: str) -> str:
    return TARIFARIO.get(tipo, {}).get("display_name", {}).get("es", tipo)


def build_conversion_payload(
    status: str,
    items: list[dict] | None = None,
    total: float | None = None,
    preguntas: list[dict] | None = None,
    presupuesto_parcial: dict | None = None,
) -> dict:
    """
    Genera copy y CTAs para que el frontend convierta visitas en clientes.
    El frontend puede renderizar esto directamente sin hardcodear textos.
    """
    conversion = {
        "social_proof": SOCIAL_PROOF,
        "beneficios": [
            "Presupuesto instantáneo sin compromiso",
            "Montadores verificados en tu zona",
            "Pago seguro · Satisfacción garantizada",
        ],
    }

    if status == "clarification_needed" and preguntas:
        primera = preguntas[0]
        tipo = primera.get("tipo_mueble", "mueble")
        campos = primera.get("dato_faltante", [])
        campo_txt = CAMPO_LABELS.get(campos[0], campos[0]) if campos else "algunos detalles"

        conversion.update({
            "headline": f"Tu {_nombre_mueble(tipo)} está casi listo",
            "subheadline": f"Confirma {campo_txt} para ver el precio exacto",
            "cta_primary": "Ver precio exacto",
            "cta_secondary": "Guardar y continuar después",
            "urgency": "Respuesta en menos de 2 minutos",
            "microcopy_registro": "Solo necesitamos tu email para guardar el presupuesto",
        })

        if presupuesto_parcial and presupuesto_parcial.get("precio_minimo_estimado"):
            pmin = presupuesto_parcial["precio_minimo_estimado"]
            conversion["precio_gancho"] = f"Desde {pmin:.0f}€"

    elif status == "success" and total is not None:
        conversion.update({
            "headline": f"Tu montaje por {total:.0f}€",
            "subheadline": "Precio cerrado · Incluye desplazamiento y montaje profesional",
            "cta_primary": "Cotizar por WhatsApp",
            "cta_secondary": "Pedir otro precio",
            "urgency": "Montadores en Málaga y Costa del Sol",
            "microcopy_registro": "Sin cuenta: te llega el presupuesto por WhatsApp",
            "precio_gancho": f"{total:.0f}€",
        })

    elif status == "consulta_manual":
        conversion.update({
            "headline": "Lo cotizamos a mano",
            "subheadline": "No está en el tarifario automático. Kiq te confirma el precio.",
            "cta_primary": "Enviar consulta por WhatsApp",
            "cta_secondary": "Añadir otra foto",
        })

    elif status == "unknown":
        conversion.update({
            "headline": "¿Qué mueble necesitas montar?",
            "subheadline": "Escríbenos o sube una foto — te damos precio al instante",
            "cta_primary": "Subir foto del mueble",
            "cta_secondary": "Ver precios orientativos",
            "sugerencias": [
                {"tipo": k, "nombre": v["display_name"]["es"], "desde": v["precio_base"]}
                for k, v in list(TARIFARIO.items())[:6]
            ],
        })

    if items:
        conversion["confianza_media"] = round(
            sum(i.get("confianza", 0.7) for i in items) / len(items), 2
        )

    return conversion
