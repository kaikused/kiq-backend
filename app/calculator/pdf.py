"""Generación de PDF de presupuestos Kiq."""
from datetime import datetime
from io import BytesIO

import requests
from fpdf import FPDF

from ..storage import comprimir_imagen

MARCA = (109, 40, 217)
TINTA = (24, 24, 27)
SUAVE = (82, 82, 91)
LINEA = (228, 228, 231)
FONDO = (250, 250, 250)


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


def _eur(valor) -> str:
    try:
        return f"{float(valor or 0):.0f} EUR"
    except (TypeError, ValueError):
        return "0 EUR"


class PresupuestoPDF(FPDF):
    def header(self):
        self.set_fill_color(*MARCA)
        self.rect(0, 0, 210, 16, "F")
        self.set_y(4)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 13)
        self.cell(100, 8, "Kiq Montajes", align="L")
        self.set_font("Helvetica", "", 9)
        self.cell(0, 8, "kiq.es  ·  Malaga y Costa del Sol", align="R", ln=True)
        self.set_text_color(*TINTA)
        self.ln(10)

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(*LINEA)
        self.line(18, self.get_y(), 192, self.get_y())
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*SUAVE)
        self.cell(0, 10, _txt("Presupuesto orientativo  ·  Kiq Montajes  ·  kiq.es"), align="C")

    def seccion(self, titulo: str):
        self.ln(2)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*MARCA)
        self.cell(0, 6, _txt(titulo).upper(), ln=True)
        self.set_draw_color(*LINEA)
        self.line(18, self.get_y(), 192, self.get_y())
        self.ln(3)
        self.set_text_color(*TINTA)

    def dato(self, etiqueta: str, valor: str, ancho=87):
        if not valor:
            return
        x = self.get_x()
        y = self.get_y()
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*SUAVE)
        self.cell(ancho, 4, _txt(etiqueta).upper())
        self.set_xy(x, y + 4)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*TINTA)
        self.multi_cell(ancho, 5, _txt(valor))
        self.set_y(max(self.get_y(), y + 12))


def generar_pdf_presupuesto(payload: dict) -> bytes:
    """Cotizacion A4: total y cobro primero, luego ficha, trabajo y desglose."""
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
    titulo = "Consulta de montaje" if consulta else "Presupuesto"
    items = desglose.get("muebles_cotizados") or []
    extras = desglose.get("detalles_extras") or []
    km = _txt(desglose.get("distancia_km", ""))
    blanco = "-"
    emitido = datetime.utcnow().strftime("%d/%m/%Y")

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*SUAVE)
    pdf.cell(110, 5, _txt(titulo.upper()), ln=False)
    pdf.cell(0, 5, f"Emitido {emitido}", align="R", ln=True)

    y0 = pdf.get_y()
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*TINTA)
    pdf.cell(110, 10, nombre[:42], ln=False)

    caja_x, caja_w = 128, 64
    pdf.set_fill_color(*MARCA)
    pdf.rect(caja_x, y0, caja_w, 28, "F")
    pdf.set_xy(caja_x + 4, y0 + 4)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(caja_w - 8, 5, "TOTAL", ln=True)
    pdf.set_x(caja_x + 4)
    pdf.set_font("Helvetica", "B", 18)
    if consulta:
        pdf.cell(caja_w - 8, 10, "A confirmar", ln=True)
    else:
        pdf.cell(caja_w - 8, 10, _eur(precio), ln=True)
    pdf.set_x(caja_x + 4)
    pdf.set_font("Helvetica", "B", 8)
    if cobrado:
        pago = f"PAGADO" + (f"  {metodo_pago}" if metodo_pago else "")
    else:
        pago = "Pendiente de cobro" + (f"  {metodo_pago}" if metodo_pago else "")
    pdf.cell(caja_w - 8, 5, _txt(pago), ln=True)

    pdf.set_y(max(pdf.get_y(), y0 + 32))
    pdf.set_text_color(*TINTA)

    pdf.seccion("Cliente y servicio")
    col_y = pdf.get_y()
    pdf.dato("Cliente", nombre, 85)
    y_izq = pdf.get_y()
    pdf.set_xy(107, col_y)
    pdf.dato("Zona", direccion or "Pendiente", 85)
    y_der = pdf.get_y()
    pdf.set_xy(18, y_izq)
    if telefono:
        pdf.dato("Telefono", telefono, 85)
        y_izq = pdf.get_y()
    if email:
        pdf.set_xy(18, y_izq)
        pdf.dato("Email", email, 85)
        y_izq = pdf.get_y()
    pdf.set_xy(107, y_der)
    if fecha_visita:
        pdf.dato("Fecha y hora", fecha_visita, 85)
        y_der = pdf.get_y()
    if metodo_pago and not cobrado:
        pdf.set_xy(107, y_der)
        pdf.dato("Pago", metodo_pago, 85)
        y_der = pdf.get_y()
    pdf.set_y(max(y_izq, y_der) + 2)

    pdf.seccion("Que hay que montar")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*TINTA)
    pdf.multi_cell(0, 6, descripcion)
    pdf.ln(2)

    pdf.seccion("Desglose")
    pdf.set_fill_color(*FONDO)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*SUAVE)
    pdf.cell(92, 7, "CONCEPTO", fill=True)
    pdf.cell(22, 7, "CANT.", fill=True, align="C")
    pdf.cell(32, 7, "PRECIO", fill=True, align="R")
    pdf.cell(28, 7, "IMPORTE", fill=True, align="R", ln=True)
    pdf.set_text_color(*TINTA)
    pdf.set_font("Helvetica", "", 10)

    if not items:
        pdf.set_text_color(*SUAVE)
        pdf.cell(0, 8, _txt("Sin lineas de tarifario. El total refleja el precio acordado."), ln=True)
        pdf.set_text_color(*TINTA)

    for item in items:
        nombre_item = _txt(item.get("item", ""))[:48]
        pdf.cell(92, 8, nombre_item)
        pdf.cell(22, 8, str(item.get("cantidad", 1)), align="C")
        if consulta:
            pdf.cell(32, 8, blanco, align="R")
            pdf.cell(28, 8, blanco, align="R", ln=True)
        else:
            pdf.cell(32, 8, _eur(item.get("precio_unitario", 0)), align="R")
            pdf.cell(28, 8, _eur(item.get("subtotal", 0)), align="R", ln=True)
        pdf.set_draw_color(*LINEA)
        pdf.line(18, pdf.get_y(), 192, pdf.get_y())

    pdf.ln(2)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*SUAVE)
    for extra in extras:
        pdf.cell(0, 5, f"+ {_txt(extra)}", ln=True)

    pdf.ln(2)
    pdf.set_text_color(*TINTA)
    pdf.set_font("Helvetica", "", 10)
    if consulta:
        pdf.cell(146, 7, "Desplazamiento", align="R")
        pdf.cell(28, 7, blanco, align="R", ln=True)
        pdf.cell(146, 7, "Anclaje", align="R")
        pdf.cell(28, 7, blanco, align="R", ln=True)
    else:
        pdf.cell(146, 7, "Desplazamiento", align="R")
        pdf.cell(28, 7, _eur(desglose.get("coste_desplazamiento", 0)), align="R", ln=True)
        if km:
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(*SUAVE)
            pdf.cell(174, 4, km, align="R", ln=True)
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*TINTA)
        pdf.cell(146, 7, "Anclaje", align="R")
        pdf.cell(28, 7, _eur(desglose.get("coste_anclaje_estimado", 0)), align="R", ln=True)

    pdf.set_draw_color(*MARCA)
    pdf.set_line_width(0.4)
    pdf.line(110, pdf.get_y() + 1, 192, pdf.get_y() + 1)
    pdf.set_line_width(0.2)
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*MARCA)
    if consulta:
        pdf.cell(146, 8, "Total", align="R")
        pdf.cell(28, 8, "A confirmar", align="R", ln=True)
    else:
        pdf.cell(146, 8, "Total", align="R")
        pdf.cell(28, 8, _eur(precio), align="R", ln=True)
    if cobrado:
        pdf.set_font("Helvetica", "B", 9)
        extra_pago = f" por {metodo_pago}" if metodo_pago else ""
        pdf.cell(0, 6, _txt(f"Pagado por anticipado{extra_pago}"), align="R", ln=True)

    pdf.ln(4)
    pdf.set_text_color(*SUAVE)
    pdf.set_font("Helvetica", "", 8)
    if consulta:
        nota = "Consulta para cotizar a mano. Kiq confirmara el precio antes del servicio."
    else:
        nota = (
            "Precio orientativo. Incluye montaje profesional y desplazamiento en zona estandar. "
            "Un montador confirmara el detalle antes del servicio."
        )
    pdf.multi_cell(0, 4, _txt(nota))

    _add_fotos(pdf, payload.get("imagenes") or [])
    return bytes(pdf.output())


def _add_fotos(pdf: PresupuestoPDF, image_urls: list):
    urls = [u for u in image_urls if u][:4]
    if not urls:
        return

    pdf.seccion("Fotos de referencia")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*SUAVE)
    pdf.multi_cell(
        0,
        4,
        _txt("La foto es solo apoyo visual. El pedido cotizado es el de la descripcion, no otros muebles que aparezcan en la imagen."),
    )
    pdf.set_text_color(*TINTA)
    pdf.ln(2)

    x_start = 18
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
