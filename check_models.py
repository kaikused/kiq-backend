import google.generativeai as genai
import os
from dotenv import load_dotenv  # <-- Importar dotenv

# Cargar las variables del .env para este script
load_dotenv()                   # <-- Cargar las variables

# Ahora sí podemos obtener la clave
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY') 

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    
    print("--- BUSCANDO MODELOS DISPONIBLES EN TU PROYECTO ---")
    
    try:
        # Lista todos los modelos que soportan la generación de contenido
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"✅ Nombre válido: {m.name}")
                
        print("-----------------------------------------------------")
    except Exception as e:
        print(f"❌ Error de Conexión: La clave es válida, pero la API falló. {e}")
else:
    print("⚠️ Error: No se pudo verificar la clave. Revisa tu archivo .env.")