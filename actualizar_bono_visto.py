"""
Script de mantenimiento: Añade la columna 'bono_visto' a la tabla Montador.
Necesario para que el frontend sepa cuándo ocultar la animación de bienvenida.
"""
from sqlalchemy import text
from app import create_app
from app.extensions import db

# Inicializamos tu app
app = create_app()

with app.app_context():
    print("🔄 Conectando a la base de datos...")
    try:
        # El comando SQL que añade la columna
        sql_command = text("ALTER TABLE montador ADD COLUMN bono_visto BOOLEAN DEFAULT FALSE")
        
        # Ejecutamos el comando
        db.session.execute(sql_command)
        db.session.commit()
        
        print("✅ ¡ÉXITO! La columna 'bono_visto' ha sido creada.")
        print("   Ahora los montadores tienen la casilla para marcar si vieron el bono.")
        
    except Exception as e: # pylint: disable=broad-exception-caught
        # Si da error, suele ser porque ya existe
        db.session.rollback()
        print(f"ℹ️  Nota del sistema: {e}")
        print("   (Si dice 'already exists' o 'duplicate column', todo está bien).")