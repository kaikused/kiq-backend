"""
Módulo para gestionar la subida de archivos a Google Cloud Storage.
"""
import os
import uuid
from datetime import timedelta
from io import BytesIO
from google.cloud import storage

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


def upload_bytes_to_gcs(data, filename, folder="presupuestos", content_type="application/pdf"):
    """Sube bytes a GCS y retorna la URL pública."""
    try:
        if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
            init_storage()

        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob_path = f"{folder}/{uuid.uuid4()}-{filename}"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(bytes(data), content_type=content_type)
        try:
            return blob.generate_signed_url(
                version="v4",
                expiration=timedelta(days=7),
                method="GET",
            )
        except Exception as signed_err:  # pylint: disable=broad-except
            print(f"⚠️ Signed URL GCS falló: {signed_err}")
            try:
                blob.make_public()
            except Exception:  # pylint: disable=broad-except
                pass
            return blob.public_url
    except Exception as e:  # pylint: disable=broad-except
        print(f"❌ Error subiendo PDF a GCS: {e}")
        return _upload_pdf_cloudinary(data, filename)


def _upload_pdf_cloudinary(data, filename):
    """Respaldo si GCS no está disponible."""
    try:
        import cloudinary
        import cloudinary.uploader

        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
            api_key=os.getenv("CLOUDINARY_API_KEY"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET"),
            secure=True,
        )
        result = cloudinary.uploader.upload(
            BytesIO(bytes(data)),
            resource_type="raw",
            folder="presupuestos",
            filename=filename,
            use_filename=True,
            unique_filename=True,
        )
        return result.get("secure_url")
    except Exception as e:  # pylint: disable=broad-except
        print(f"❌ Error subiendo PDF a Cloudinary: {e}")
        return None