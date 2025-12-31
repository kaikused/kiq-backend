# init_db.py
import os
from dotenv import load_dotenv

# --- 1. CARGA EXPLÍCITA DEL .ENV ---
# Obtenemos la ruta absoluta de la carpeta actual
basedir = os.path.abspath(os.path.dirname(__file__))
env_path = os.path.join(basedir, '.env')

print(f"📂 Buscando archivo .env en: {env_path}")

# Forzamos la carga desde esa ruta específica
if os.path.exists(env_path):
    load_dotenv(env_path, override=True)
    print("✅ Archivo .env encontrado y cargado.")
else:
    print("❌ ERROR: ¡No existe el archivo .env en esa ruta!")

# Verificamos qué ha leído
db_url_leida = os.environ.get("DATABASE_URL")
print(f"🧐 DATABASE_URL actual: {db_url_leida}")

# --- 2. INICIO DE LA APP ---
from app import create_app
from app.extensions import db
from sqlalchemy import text

app = create_app()

# Forzamos la configuración en la app por si acaso no la pilló
if db_url_leida:
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url_leida

with app.app_context():
    try:
        print(f"🔌 Intentando conectar a: {app.config['SQLALCHEMY_DATABASE_URI']}")

        # 3. Probar conexión real
        db.session.execute(text('SELECT 1'))
        print("✅ ¡CONEXIÓN EXITOSA A POSTGRESQL!")
        
        # 4. Crear tablas
        print("🛠️ Creando tablas...")
        db.create_all()
        print("✅ Tablas creadas correctamente.")
        
        # 5. Verificar qué tablas existen
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"📊 Tablas en la DB: {tables}")
        
    except Exception as e:
        print(f"❌ ERROR FATAL: {e}")
        print("Consejo: Verifica tu contraseña en el archivo .env")