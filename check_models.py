"""
Script de utilidad para listar los modelos de Gemini disponibles
y verificar que la API KEY funciona correctamente.
"""
import os
import google.generativeai as genai
from dotenv import load_dotenv

# Cargar las variables del .env
load_dotenv()

# Obtener la clave
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

def verificar_modelos():
    """Conecta con Google y lista los modelos de texto."""
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        
        print("--- BUSCANDO MODELOS DISPONIBLES EN TU PROYECTO ---")
        
        try:
            # Lista todos los modelos que soportan la generación de contenido
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    print(f"✅ Nombre válido: {m.name}")
                    
            print("-----------------------------------------------------")
        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"❌ Error de Conexión: La clave es válida, pero la API falló. {e}")
    else:
        print("⚠️ Error: No se pudo verificar la clave. Revisa tu archivo .env")

if __name__ == "__main__":
    verificar_modelos()