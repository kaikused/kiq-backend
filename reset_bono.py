"""
Script de utilidad para resetear la visualización del bono de bienvenida.
Útil para testing: permite ver el modal de bienvenida otra vez en un usuario existente.
"""
from app import create_app
from app.extensions import db
from app.models import Montador

# Inicializamos la app
app = create_app()

with app.app_context():
    print("🔄 --- RESETEAR ESTADO DEL BONO ---")
    
    # Solicitamos el email (funciona en terminal local y Shell de Render)
    email = input("📧 Introduce el email del montador: ")
    
    montador = Montador.query.filter_by(email=email).first()
    
    if montador:
        try:
            print(f"   Usuario encontrado: {montador.nombre}")
            print(f"   Estado actual 'bono_visto': {montador.bono_visto}")
            
            montador.bono_visto = False
            db.session.commit()
            
            print(f"✅ ¡Listo! Bono reseteado para {montador.email}.")
            print("   Ahora, al entrar en el Panel, volverá a ver la animación.")
            
        except Exception as e: # pylint: disable=broad-exception-caught
            db.session.rollback()
            print(f"❌ Error al guardar en base de datos: {e}")
    else:
        print("❌ Error: Usuario no encontrado. Verifica que el email sea exacto.")