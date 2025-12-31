"""
Punto de entrada principal para la aplicación Flask (kiq-backend).
Configura y ejecuta la app.
"""
from dotenv import load_dotenv  # Importación de librería de terceros
from app import create_app      # Importación de módulo local

# Carga las variables del archivo .env antes de inicializar la app
load_dotenv()

# Llama a la función "fábrica" que acabamos de crear en __init__.py
app = create_app()

if __name__ == '__main__':
    # Ejecuta la aplicación
    app.run(debug=True, port=5000)
# (Asegúrate de dejar una línea en blanco aquí al final)
