"""
Subida de archivos a Google Cloud Storage (fotos de cotización, outlet, evidencias y PDFs).
Usa el mismo bucket y las mismas credenciales que Vision AI.
Las URLs son firmadas (7 días): el bucket puede ser privado.
"""
import json
import os
import uuid
from datetime import timedelta

from google.cloud import storage
from google.oauth2 import service_account

BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "kiq-montajes-uploads")
URL_TTL_DAYS = 7


def _credentials_path():
    basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(basedir, "google-credentials.json")


def ensure_google_credentials():
    """
    Deja listo google-credentials.json a partir del env de Render
    o del archivo local. Devuelve la ruta o None.
    """
    cred_path = _credentials_path()
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON")

    if raw:
        raw = raw.strip()
        try:
            info = json.loads(raw)
            if isinstance(info.get("private_key"), str):
                info["private_key"] = info["private_key"].replace("\\n", "\n")
            with open(cred_path, "w", encoding="utf-8") as handle:
                json.dump(info, handle)
        except json.JSONDecodeError:
            with open(cred_path, "w", encoding="utf-8") as handle:
                handle.write(raw)

    if os.path.exists(cred_path):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
        return cred_path

    print(f"⚠️ No hay credenciales Google en {cred_path}")
    return None


def _load_credentials():
    path = ensure_google_credentials()
    if not path:
        raise RuntimeError("Faltan credenciales de Google Cloud Storage")
    return service_account.Credentials.from_service_account_file(path)


def _gcs_client():
    creds = _load_credentials()
    project = getattr(creds, "project_id", None)
    client = storage.Client(credentials=creds, project=project)
    return client, creds


def _signed_url(blob, credentials):
    """URL que WhatsApp y el navegador pueden abrir sin bucket público."""
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(days=URL_TTL_DAYS),
        method="GET",
        credentials=credentials,
    )


def init_storage():
    """Compatibilidad con llamadas antiguas."""
    return ensure_google_credentials() is not None


def upload_image_to_gcs(file, folder="misc"):
    """Sube una imagen al bucket y devuelve URL firmada."""
    try:
        client, creds = _gcs_client()
        bucket = client.bucket(BUCKET_NAME)
        ext = (
            file.filename.rsplit(".", 1)[1].lower()
            if file.filename and "." in file.filename
            else "jpg"
        )
        blob_path = f"{folder}/{uuid.uuid4()}.{ext}"
        blob = bucket.blob(blob_path)
        file.seek(0)
        blob.upload_from_file(
            file,
            content_type=file.content_type or "image/jpeg",
        )
        url = _signed_url(blob, creds)
        print(f"✅ GCS imagen subida: {blob_path}")
        return url
    except Exception as exc:  # pylint: disable=broad-except
        print(f"❌ Error subiendo imagen a GCS ({BUCKET_NAME}): {exc}")
        return None


def upload_bytes_to_gcs(data, filename, folder="presupuestos", content_type="application/pdf"):
    """Sube un PDF (u otros bytes) al mismo bucket y devuelve URL firmada."""
    client, creds = _gcs_client()
    bucket = client.bucket(BUCKET_NAME)
    safe_name = filename.replace(" ", "-")
    blob_path = f"{folder}/{uuid.uuid4()}-{safe_name}"
    blob = bucket.blob(blob_path)
    blob.content_disposition = f'inline; filename="{safe_name}"'
    blob.upload_from_string(bytes(data), content_type=content_type)
    url = _signed_url(blob, creds)
    print(f"✅ GCS PDF subido: {blob_path}")
    return url
