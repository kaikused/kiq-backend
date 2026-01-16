"""
Punto de entrada principal para la aplicación Flask (kiq-backend).
Configura y ejecuta la app usando el patrón Application Factory.
"""
from dotenv import load_dotenv
from app import create_app

# Carga las variables del archivo .env antes de inicializar la app
# Esto es CRUCIAL para que create_app() encuentre la DATABASE_URL y claves.
load_dotenv()

# Llama a la función "fábrica" definida en app/__init__.py
app = create_app()

if __name__ == '__main__':
    # Ejecuta la aplicación en modo desarrollo (solo si ejecutas python run.py)
    # En producción (Render), Gunicorn ignorará esto y usará 'app' directamente.
    app.run(debug=True, port=5000)