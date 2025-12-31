"""
Módulo para gestionar la subida de archivos a Google Cloud Storage.
"""
import os
import uuid
from google.cloud import storage

# Configuración
BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "kiq-montajes-uploads")

def init_storage():
    """
    Inicializa las credenciales de Google Cloud si existen.
    Retorna True si se configura correctamente.
    """
    # Buscamos el archivo json en la raíz del proyecto
    basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    cred_path = os.path.join(basedir, 'google-credentials.json')

    if os.path.exists(cred_path):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
        return True

    print(f"⚠️ ADVERTENCIA: No se encontró {cred_path}")
    return False

def upload_image_to_gcs(file, folder="misc"):
    """
    Sube una imagen a GCS y retorna la URL pública.
    :param file: Objeto FileStorage de Flask
    :param folder: Carpeta destino en el bucket
    """
    try:
        # Asegurar credenciales antes de intentar subir
        if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
            init_storage()

        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)

        # Generar nombre único usando UUID para evitar colisiones
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
        filename = f"{uuid.uuid4()}.{ext}"
        blob_path = f"{folder}/{filename}"

        blob = bucket.blob(blob_path)

        # Subir archivo
        # (El archivo debe ser público a nivel de bucket para que esta URL funcione)
        file.seek(0) # Volver al inicio del stream antes de subir
        blob.upload_from_file(file, content_type=file.content_type)
        
        # ELIMINADO: blob.make_public() y su bloque try/except.

        # Retornar la URL pública del objeto
        return blob.public_url

    except Exception as e: # pylint: disable=broad-except
        # Capturamos Exception genérico para que la app no se caiga si falla la nube
        print(f"❌ Error crítico subiendo a GCS: {e}")
        return None