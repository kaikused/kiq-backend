import os
from app import create_app
from app.extensions import db
from sqlalchemy import text

# Inicializamos tu app para poder acceder a la base de datos
app = create_app()

with app.app_context():
    print("🔄 Conectando a la base de datos...")
    try:
        # El comando SQL que añade la columna
        sql_command = text("ALTER TABLE montador ADD COLUMN bono_visto BOOLEAN DEFAULT FALSE;")
        
        # Ejecutamos el comando
        db.session.execute(sql_command)
        db.session.commit()
        
        print("✅ ¡ÉXITO! La columna 'bono_visto' ha sido creada.")
        print("   Ahora los montadores tienen la casilla para marcar si vieron el bono.")
        
    except Exception as e:
        # Si da error, suele ser porque ya existe o hubo un problema de conexión
        print(f"⚠️ Nota del sistema: {e}")
        print("   (Si el error dice 'already exists', significa que ya estaba lista y no debes preocuparte)")