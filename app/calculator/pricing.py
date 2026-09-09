"""Motor de cálculo de precios."""
from .measures import classify_medida
from .tarifario import COSTE_ANCLAJE, PRECIO_MINIMO, TARIFARIO


def _precio_rango_tipo(tipo: str) -> tuple[float, float]:
    """Devuelve (min, max) estimado para un tipo cuando faltan datos."""
    tarifas = TARIFARIO.get(tipo, {"precio_base": 40})
    base = tarifas.get("precio_base", 40)
    reglas = tarifas.get("reglas_precio", {})
    minimo = base + reglas.get("pequeno", 0)
    maximo = base + reglas.get("grande", 0) + reglas.get("suplemento_corredera", 0)
    if tipo == "armario":
        maximo += reglas.get("puerta_extra", 30) * 2
    return (min(minimo, maximo), max(minimo, maximo))


def calcular_precio_item(tipo: str, cantidad: int, attrs: dict) -> dict:
    """Calcula precio unitario y extras para un ítem."""
    if tipo == "consulta":
        texto = (attrs.get("texto") or "Consulta")[:80]
        return {
            "precio_unitario": 0,
            "subtotal": 0,
            "coste_extras": 0,
            "extras": [],
            "necesita_anclaje": False,
            "display_name": texto,
            "consulta": True,
        }

    if tipo == "otros":
        try:
            precio_unitario = float(attrs.get("precio_unitario") or attrs.get("precio") or 0)
        except (TypeError, ValueError):
            precio_unitario = 0.0
        nombre = (attrs.get("concepto") or attrs.get("texto") or "Otros").strip() or "Otros"
        return {
            "precio_unitario": precio_unitario,
            "subtotal": precio_unitario * cantidad,
            "coste_extras": 0,
            "extras": [],
            "necesita_anclaje": False,
            "display_name": nombre[:80],
        }

    tarifas = TARIFARIO.get(tipo, {"precio_base": 40, "necesita_anclaje": False})
    precio_unitario = tarifas.get("precio_base", 40)
    reglas = tarifas.get("reglas_precio", {})
    extras = []
    coste_extras = 0.0

    if tipo == "armario":
        tipo_puerta = str(attrs.get("tipo_puerta", "batiente")).lower()
        if "corredera" in tipo_puerta:
            suplemento = reglas.get("suplemento_corredera", 20)
            precio_unitario += suplemento
            extras.append(f"Suplemento Puertas Correderas: +{suplemento}€")

        num_puertas = attrs.get("num_puertas", 2)
        if isinstance(num_puertas, (int, float)) and num_puertas > 2:
            extra_puertas = (num_puertas - 2) * reglas.get("puerta_extra", 30)
            coste_extras += extra_puertas
            extras.append(f"Extra tamaño ({int(num_puertas)} puertas): +{extra_puertas}€")

    elif tipo in ("canape", "cama"):
        medida = attrs.get("medida")
        size = classify_medida(str(medida) if medida else None)
        if size == "pequeno":
            descuento = reglas.get("pequeno", -10)
            precio_unitario += descuento
            extras.append("Medida pequeña (90/105): -10€")
        elif size == "grande":
            suplemento = reglas.get("grande", 20)
            precio_unitario += suplemento
            extras.append("Medida grande/King: +20€")

    subtotal = precio_unitario * cantidad
    return {
        "precio_unitario": precio_unitario,
        "subtotal": subtotal,
        "coste_extras": coste_extras,
        "extras": extras,
        "necesita_anclaje": tarifas.get("necesita_anclaje", False),
        "display_name": tarifas.get("display_name", {}).get("es", tipo),
    }


def calcular_presupuesto_items(items: list[dict]) -> dict:
    """Calcula el presupuesto completo a partir de ítems detectados."""
    coste_muebles_base = 0.0
    coste_extras = 0.0
    detalles_factura = []
    anclaje_global = False
    muebles_cotizados = []

    for item in items:
        tipo = item.get("tipo", "otro")
        cantidad = int(item.get("cantidad", 1))
        attrs = item.get("atributos", {})

        resultado = calcular_precio_item(tipo, cantidad, attrs)
        coste_muebles_base += resultado["subtotal"]
        coste_extras += resultado["coste_extras"]
        detalles_factura.extend(resultado["extras"])

        if resultado["necesita_anclaje"]:
            anclaje_global = True

        muebles_cotizados.append({
            "item": resultado["display_name"],
            "cantidad": cantidad,
            "precio_unitario": resultado["precio_unitario"],
            "subtotal": resultado["subtotal"],
        })

    return {
        "coste_muebles_base": coste_muebles_base,
        "coste_extras": coste_extras,
        "detalles_factura": detalles_factura,
        "anclaje_global": anclaje_global,
        "muebles_cotizados": muebles_cotizados,
    }


def calcular_presupuesto_parcial(items: list[dict]) -> dict:
    """
    Estima rango de precio cuando hay ítems con datos incompletos.
    Útil para mostrar 'desde X€' en el frontend antes de convertir.
    """
    min_total = 0.0
    max_total = 0.0
    completos = []
    pendientes = []

    for item in items:
        tipo = item.get("tipo", "otro")
        cantidad = int(item.get("cantidad", 1))
        faltantes = item.get("falta_info", [])

        if faltantes:
            pmin, pmax = _precio_rango_tipo(tipo)
            min_total += pmin * cantidad
            max_total += pmax * cantidad
            pendientes.append({
                "tipo": tipo,
                "display_name": TARIFARIO.get(tipo, {}).get("display_name", {}).get("es", tipo),
                "campos_faltantes": faltantes,
                "precio_desde": pmin * cantidad,
                "precio_hasta": pmax * cantidad,
            })
        else:
            resultado = calcular_precio_item(tipo, cantidad, item.get("atributos", {}))
            min_total += resultado["subtotal"] + resultado["coste_extras"]
            max_total += resultado["subtotal"] + resultado["coste_extras"]
            completos.append(tipo)

    return {
        "precio_minimo_estimado": min_total,
        "precio_maximo_estimado": max_total,
        "items_completos": completos,
        "items_pendientes": pendientes,
    }


def total_final(
    coste_muebles_base: float,
    coste_extras: float,
    coste_desplazamiento: float,
    anclaje_global: bool,
    consulta: bool = False,
) -> dict:
    """Calcula total final con mínimo garantizado."""
    if consulta:
        return {
            "coste_anclaje": 0.0,
            "total_presupuesto": None,
        }
    coste_anclaje = COSTE_ANCLAJE if anclaje_global else 0.0
    total = coste_muebles_base + coste_extras + coste_desplazamiento + coste_anclaje
    precio_final = max(total, PRECIO_MINIMO)
    return {
        "coste_anclaje": coste_anclaje,
        "total_presupuesto": precio_final,
    }
