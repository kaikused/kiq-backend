from app.email_service import enviar_email_generico

# Pon aquí TU correo personal para probar
mi_correo = "fqvdo7@gmail.com" 

print("Enviando prueba...")
enviar_email_generico(mi_correo, "Prueba Kiq", "<h1>¡Funciona!</h1><p>Este es un email desde Python.</p>")