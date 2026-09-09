"""
Subida a Google Cloud Storage: mismo bucket que las fotos de cotización.
Credenciales desde GOOGLE_CREDENTIALS_JSON (Render) o google-credentials.json.
No usa Cloudinary. Las URLs van firmadas 7 días (el bucket puede ser privado).
"""
import json
import os
import re
import unicodedata
import uuid
from datetime import datetime, timedelta
from io import BytesIO

from google.cloud import storage
from google.oauth2 import service_account

BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "kiq-montajes-uploads")
URL_TTL_DAYS = 7
_CACHED_CREDS = None


def _credentials_file_path():
    basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(basedir, "google-credentials.json")


def _parse_service_account_info():
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if raw:
        raw = raw.strip()
        info = json.loads(raw)
        if isinstance(info.get("private_key"), str):
            info["private_key"] = info["private_key"].replace("\\n", "\n")
        return info

    path = _credentials_file_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    return None


def get_google_credentials():
    """Cuenta de servicio en memoria (sin depender de escribir disco en Render)."""
    global _CACHED_CREDS
    if _CACHED_CREDS is not None:
        return _CACHED_CREDS

    info = _parse_service_account_info()
    if not info:
        raise RuntimeError(
            "Faltan credenciales Google: GOOGLE_CREDENTIALS_JSON o google-credentials.json"
        )

    _CACHED_CREDS = service_account.Credentials.from_service_account_info(info)
    os.environ.setdefault(
        "GOOGLE_APPLICATION_CREDENTIALS",
        _credentials_file_path(),
    )
    email = info.get("client_email", "?")
    print(f"✅ Credenciales GCS listas ({email}) bucket={BUCKET_NAME}")
    return _CACHED_CREDS


def ensure_google_credentials():
    """Compatibilidad con create_app: prepara credenciales y, si puede, el JSON en disco."""
    try:
        creds = get_google_credentials()
        path = _credentials_file_path()
        info = _parse_service_account_info()
        if info:
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(info, handle)
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
            except OSError as write_err:
                print(f"⚠️ No se pudo escribir {path}: {write_err} (se usa credencial en memoria)")
        return creds is not None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"⚠️ ensure_google_credentials: {exc}")
        return False


def init_storage():
    return ensure_google_credentials()


def _gcs_bucket():
    creds = get_google_credentials()
    project = getattr(creds, "project_id", None)
    client = storage.Client(credentials=creds, project=project)
    return client.bucket(BUCKET_NAME), creds


def _signed_url(blob, credentials):
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(days=URL_TTL_DAYS),
        method="GET",
        credentials=credentials,
    )


def _read_bytes(file_or_bytes):
    if isinstance(file_or_bytes, (bytes, bytearray)):
        return bytes(file_or_bytes)
    if hasattr(file_or_bytes, "seek"):
        try:
            file_or_bytes.seek(0)
        except Exception:  # pylint: disable=broad-exception-caught
            pass
    data = file_or_bytes.read()
    if isinstance(data, str):
        data = data.encode("utf-8")
    return data


def slug_cliente(nombre: str) -> str:
    texto = unicodedata.normalize("NFKD", nombre or "cliente")
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto.lower()).strip("-")
    return (texto or "cliente")[:32]


def nueva_carpeta_cotizacion(nombre: str) -> str:
    """cotizaciones/luis-2026-09-08-a3f2 — identificable en el bucket."""
    slug = slug_cliente(nombre)
    fecha = datetime.utcnow().strftime("%Y-%m-%d")
    extra = uuid.uuid4().hex[:4]
    return f"cotizaciones/{slug}-{fecha}-{extra}"


def codigo_desde_carpeta(carpeta: str) -> str:
    return (carpeta or "").rstrip("/").split("/")[-1]


def carpeta_valida(code: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,80}", code or ""))


def comprimir_imagen(data: bytes, filename: str = "foto.jpg") -> tuple[bytes, str, str]:
    """Reduce fotos a JPEG ~1280px para no inflar PDF ni el bucket."""
    payload = bytes(data or b"")
    if not payload:
        return payload, "image/jpeg", "foto.jpg"
    try:
        from PIL import Image

        imagen = Image.open(BytesIO(payload))
        if imagen.mode in ("RGBA", "LA"):
            fondo = Image.new("RGB", imagen.size, (255, 255, 255))
            fondo.paste(imagen, mask=imagen.split()[-1])
            imagen = fondo
        else:
            imagen = imagen.convert("RGB")
        imagen.thumbnail((1280, 1280))
        salida = BytesIO()
        imagen.save(salida, format="JPEG", quality=72, optimize=True)
        comprimido = salida.getvalue()
        if len(comprimido) < len(payload):
            payload = comprimido
        return payload, "image/jpeg", "foto.jpg"
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"⚠️ No se pudo comprimir {filename}: {exc}")
        return payload, "image/jpeg", filename or "foto.jpg"


def upload_bytes_to_gcs(
    data,
    filename,
    folder="cotizaciones",
    content_type="application/octet-stream",
    unique_name=True,
):
    """Sube bytes al bucket y devuelve URL firmada. Lanza si Google falla."""
    payload = bytes(data)
    if not payload:
        raise RuntimeError("Archivo vacío: no se sube a GCS")

    bucket, creds = _gcs_bucket()
    safe_name = (filename or "archivo").replace(" ", "-")
    folder = (folder or "cotizaciones").strip("/")
    if unique_name:
        blob_path = f"{folder}/{uuid.uuid4()}-{safe_name}"
    else:
        blob_path = f"{folder}/{safe_name}"
    blob = bucket.blob(blob_path)
    if content_type == "application/pdf":
        blob.content_disposition = f'inline; filename="{safe_name}"'
        blob.cache_control = "no-cache, max-age=0"
    blob.upload_from_string(payload, content_type=content_type)
    url = _signed_url(blob, creds)
    print(f"✅ GCS OK gs://{BUCKET_NAME}/{blob_path} ({len(payload)} bytes)")
    return url, blob_path


def signed_url_for_blob(blob_path: str) -> str:
    """Regenera una URL firmada a partir de la ruta del objeto."""
    bucket, creds = _gcs_bucket()
    blob = bucket.blob(blob_path)
    return _signed_url(blob, creds)


def url_foto_almacenada(valor):
    """Ruta corta en DB → URL firmada. Si ya es http, se deja."""
    if not valor:
        return None
    if str(valor).startswith("http://") or str(valor).startswith("https://"):
        return valor
    try:
        return signed_url_for_blob(valor)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"⚠️ No se pudo firmar foto {valor}: {exc}")
        return None


def upload_image_to_gcs(file, folder="misc", as_path=False):
    """Sube una imagen (FileStorage o bytes). Devuelve URL firmada, ruta, o None."""
    try:
        filename = getattr(file, "filename", None) or "foto.jpg"
        content_type = getattr(file, "content_type", None) or "image/jpeg"
        payload = _read_bytes(file)
        url, path = upload_bytes_to_gcs(
            payload,
            filename,
            folder=folder,
            content_type=content_type,
        )
        return path if as_path else url
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"❌ Error subiendo imagen a GCS ({BUCKET_NAME}): {exc}")
        return None
