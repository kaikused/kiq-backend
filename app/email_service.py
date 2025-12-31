"""
Módulo para el envío de correos electrónicos transaccionales usando Resend.
"""
import os
import resend
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configurar la API Key
resend.api_key = os.getenv('RESEND_API_KEY')

# Configuración del remitente
REMITENTE_DEFAULT = "Kiq Montajes <info@kiq.es>"

def enviar_email_generico(destinatario, asunto, contenido_html):
    """
    Función base para enviar cualquier correo.
    Captura cualquier error para evitar romper el flujo principal.
    """
    try:
        params = {
            "from": REMITENTE_DEFAULT,
            "to": [destinatario],
            "subject": asunto,
            "html": contenido_html,
        }

        email = resend.Emails.send(params)
        print(f"📧 Email enviado a {destinatario}: ID {email.get('id')}")
        return True

    except Exception as error: # pylint: disable=broad-exception-caught
        print(f"❌ Error enviando email: {error}")
        return False

def enviar_resumen_presupuesto(email_cliente, nombre_cliente, precio, items_resumen):
    """
    Envía un correo bonito al cliente con el precio final.
    """
    # Construimos una lista HTML simple de los muebles
    lista_items = "".join(
        [f"<li>{item['item']} (x{item['cantidad']})</li>" for item in items_resumen]
    )

    html_content = f"""
    <div style="font-family: sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
        <h1 style="color: #6d28d9;">¡Hola, {nombre_cliente}!</h1>
        <p>Gracias por confiar en <strong>Kiq Montajes</strong>.
           Aquí tienes el resumen de tu solicitud:</p>
        
        <div style="background-color: #f3f4f6; padding: 20px; border-radius: 10px; margin: 20px 0;">
            <h2 style="margin-top: 0;">Tu Presupuesto: {precio}€</h2>
            <p>Incluye desplazamiento y montaje profesional.</p>
            <ul>
                {lista_items}
            </ul>
        </div>

        <p>Un montador experto de tu zona (Málaga) revisará tu solicitud en breve.</p>
        <hr style="border: 0; border-top: 1px solid #eee; margin: 30px 0;">
        <p style="font-size: 12px; color: #999;">Kiq Technologies © 2025</p>
    </div>
    """

    return enviar_email_generico(
        destinatario=email_cliente,
        asunto=f"🚀 Tu presupuesto Kiq: {precio}€",
        contenido_html=html_content
    )

def enviar_codigo_verificacion(email_destino, codigo):
    """
    Envía el código OTP al usuario para verificar su cuenta.
    """
    html_content = f"""
    <div style="font-family: sans-serif; text-align: center; padding: 20px; max-width: 500px; margin: 0 auto; border: 1px solid #eee; border-radius: 10px;">
        <h2 style="color: #333;">Verifica tu correo en Kiq</h2>
        <p>Estás a un paso de completar tu solicitud. Usa este código:</p>
        
        <div style="background: #f3f4f6; padding: 15px; font-size: 32px; font-weight: bold; letter-spacing: 5px; color: #6d28d9; margin: 25px 0; border-radius: 8px;">
            {codigo}
        </div>
        
        <p style="font-size: 14px; color: #666;">Si no has solicitado esto, ignora este correo.</p>
        <p style="font-size: 12px; color: #999; margin-top: 20px;">Este código expira en 15 minutos.</p>
    </div>
    """
    
    return enviar_email_generico(
        destinatario=email_destino,
        asunto=f"🔐 Tu código de seguridad: {codigo}",
        contenido_html=html_content
    )