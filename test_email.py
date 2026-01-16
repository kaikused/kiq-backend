"""
Script manual para probar el envío de correos.
Ejecutar con: python test_email.py
"""
from dotenv import load_dotenv

# Cargamos entorno por seguridad
load_dotenv()

# Intentamos importar
try:
    from app.email_service import enviar_email_generico
except ImportError as exc:
    print("❌ Error: No se encuentra el módulo 'app'.")
    print("   Asegúrate de ejecutar este archivo desde la carpeta RAÍZ del proyecto.")
    # 'from exc' vincula el error original con la salida del sistema (Fix W0707)
    raise SystemExit(1) from exc

# TU CORREO (Mayúsculas porque es una constante a nivel de módulo)
MI_CORREO = "fqvdo7@gmail.com"

print(f"📧 Intentando enviar correo a: {MI_CORREO} ...")

EXITO = enviar_email_generico(
    destinatario=MI_CORREO,
    asunto="🧪 Prueba de Sistema Kiq",
    contenido_html="""
    <div style="font-family: sans-serif; padding: 20px; border: 2px solid #6d28d9; border-radius: 10px;">
        <h1 style="color: #6d28d9;">¡Funciona! 🚀</h1>
        <p>Si estás leyendo esto, tu configuración de <strong>Resend</strong> está perfecta.</p>
        <p>El backend de Kiq Montajes está listo para enviar correos.</p>
    </div>
    """
)

if EXITO:
    print("✅ ¡El sistema dice que se envió! Revisa tu bandeja de entrada (y Spam).")
else:
    print("❌ Falló el envío. Revisa la consola para ver el error.")