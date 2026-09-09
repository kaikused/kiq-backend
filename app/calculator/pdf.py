"""Generación de PDF de presupuestos Kiq."""
from datetime import datetime
from io import BytesIO

import requests
from fpdf import FPDF

from ..storage import comprimir_imagen

MARCA = (109, 40, 217)


def _email_para_pdf(email) -> str:
    e = (email or "").strip()
    if not e or e.endswith("@leads.kiq.local") or e.startswith("invitado."):
        return ""
    return e


def _fecha_visita_txt(valor) -> str:
    if not valor:
        return ""
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    texto = str(valor).strip()
    try:
        if texto.endswith("Z"):
            texto = texto[:-1]
        return datetime.fromisoformat(texto).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return _txt(texto)


def _pago_txt(valor) -> str:
    v = (valor or "").strip().lower()
    if v == "bizum":
        return "Bizum"
    if v in ("efectivo", "efectivo_gemas", "cash"):
        return "Efectivo"
    return ""


def _txt(value) -> str:
    if value is None:
        return ""
    texto = str(value).replace("€", "EUR").replace("—", "-")
    return texto.encode("latin-1", "replace").decode("latin-1")


class PresupuestoPDF(FPDF):
    def header(self):
        self.set_fill_color(*MARCA)
        self.rect(0, 0, 210, 22, "F")
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 14, "Kiq Montajes", ln=True, align="C")
        self.ln(10)
        self.set_text_color(30, 30, 30)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 10, _txt("Presupuesto orientativo · Málaga · kiq.es"), align="C")


def generar_pdf_presupuesto(payload: dict) -> bytes:
    """Crea un PDF A4 con desglose, datos del cliente y fotos."""
    pdf = PresupuestoPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    nombre = _txt(payload.get("nombre") or "Cliente")
    direccion = _txt(payload.get("direccion") or "Pendiente")
    descripcion = _txt(payload.get("descripcion") or "Montaje de muebles")
    precio = payload.get("precio_calculado") or 0
    telefono = _txt(payload.get("telefono") or "")
    email = _txt(_email_para_pdf(payload.get("email")))
    fecha_visita = _fecha_visita_txt(payload.get("fecha_visita"))
    metodo_pago = _pago_txt(payload.get("metodo_pago"))
    cobrado = bool(payload.get("cobrado"))
    desglose = payload.get("desglose") or {}
    consulta = bool(payload.get("consulta_manual") or desglose.get("consulta_manual"))
    titulo = "Consulta de montaje" if consulta else "Presupuesto de montaje"
    items = desglose.get("muebles_cotizados") or []
    blanco = "---"

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, titulo, ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC"), ln=True)
    pdf.set_text_color(30, 30, 30)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Datos del cliente", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Nombre: {nombre}", ln=True)
    pdf.cell(0, 6, f"Zona: {direccion}", ln=True)
    if email:
        pdf.cell(0, 6, f"Email: {email}", ln=True)
    if telefono:
        pdf.cell(0, 6, f"Telefono: {telefono}", ln=True)
    if fecha_visita:
        pdf.cell(0, 6, f"Fecha y hora del montaje: {fecha_visita}", ln=True)
    if metodo_pago:
        pdf.cell(0, 6, f"Metodo de pago: {metodo_pago}", ln=True)
    if cobrado:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*MARCA)
        extra_pago = f" ({metodo_pago})" if metodo_pago else ""
        pdf.cell(0, 6, f"PAGADO POR ANTICIPADO{extra_pago}", ln=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 30, 30)
    else:
        pdf.cell(0, 6, "Estado de cobro: Pendiente", ln=True)
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Que hay que montar", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, descripcion)
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Desglose", ln=True)
    pdf.set_fill_color(243, 244, 246)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(90, 7, "Item", border=1, fill=True)
    pdf.cell(25, 7, "Cant.", border=1, fill=True, align="C")
    pdf.cell(35, 7, "Precio", border=1, fill=True, align="R")
    pdf.cell(35, 7, "Subtotal", border=1, fill=True, align="R", ln=True)
    pdf.set_font("Helvetica", "", 9)

    for item in items:
        pdf.cell(90, 7, _txt(item.get("item", "")), border=1)
        pdf.cell(25, 7, str(item.get("cantidad", 1)), border=1, align="C")
        if consulta:
            pdf.cell(35, 7, blanco, border=1, align="R")
            pdf.cell(35, 7, blanco, border=1, align="R", ln=True)
        else:
            pdf.cell(35, 7, f"{item.get('precio_unitario', 0):.0f} EUR", border=1, align="R")
            pdf.cell(35, 7, f"{item.get('subtotal', 0):.0f} EUR", border=1, align="R", ln=True)

    pdf.ln(2)
    pdf.set_font("Helvetica", "", 10)
    extras = desglose.get("detalles_extras") or []
    for extra in extras:
        pdf.cell(0, 5, f"- {_txt(extra)}", ln=True)

    zona = _txt(desglose.get("distancia_km", ""))
    if consulta:
        pdf.cell(0, 6, f"Desplazamiento: {blanco}  ({zona})", ln=True)
        pdf.cell(0, 6, f"Anclaje: {blanco}", ln=True)
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(*MARCA)
        pdf.cell(0, 10, "Total estimado: ________ EUR", ln=True)
        pdf.set_text_color(80, 80, 80)
        pdf.set_font("Helvetica", "", 8)
        pdf.multi_cell(
            0,
            5,
            _txt("Consulta para cotizar a mano. Kiq confirmara el precio antes del servicio."),
        )
    else:
        pdf.cell(0, 6, f"Desplazamiento: {desglose.get('coste_desplazamiento', 0)} EUR  ({zona})", ln=True)
        pdf.cell(0, 6, f"Anclaje: {desglose.get('coste_anclaje_estimado', 0)} EUR", ln=True)
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(*MARCA)
        pdf.cell(0, 10, f"Total estimado: {float(precio or 0):.0f} EUR", ln=True)
        if cobrado:
            pdf.set_font("Helvetica", "B", 11)
            extra_pago = f" por {metodo_pago}" if metodo_pago else ""
            pdf.cell(0, 8, f"PAGADO POR ANTICIPADO{extra_pago}", ln=True)
        pdf.set_text_color(80, 80, 80)
        pdf.set_font("Helvetica", "", 8)
        pdf.multi_cell(
            0,
            5,
            _txt("Precio orientativo. Incluye montaje profesional y desplazamiento en zona estandar. "
                 "Un montador confirmara el detalle antes del servicio."),
        )

    _add_fotos(pdf, payload.get("imagenes") or [])
    return bytes(pdf.output())


def _add_fotos(pdf: PresupuestoPDF, image_urls: list):
    urls = [u for u in image_urls if u][:4]
    if not urls:
        return

    pdf.ln(6)
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Fotos de referencia", ln=True)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(
        0,
        4,
        _txt("La foto es solo apoyo visual. El pedido cotizado es el de la descripcion, no otros muebles que aparezcan en la imagen."),
    )
    pdf.set_text_color(30, 30, 30)
    pdf.ln(2)

    x_start = pdf.get_x()
    y = pdf.get_y()
    slot_w = 85
    for idx, url in enumerate(urls):
        try:
            resp = requests.get(url, timeout=6)
            if resp.status_code != 200 or not resp.content:
                continue
            comprimida, _ctype, _name = comprimir_imagen(resp.content, "foto.jpg")
            img = BytesIO(comprimida)
            col = idx % 2
            row = idx // 2
            x = x_start + col * (slot_w + 8)
            yy = y + row * 62
            if yy + 55 > 270:
                pdf.add_page()
                y = pdf.get_y()
                yy = y
            pdf.image(img, x=x, y=yy, w=80, h=55)
        except Exception:  # pylint: disable=broad-exception-caught
            continue
