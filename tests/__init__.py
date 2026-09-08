"""Bootstrap de tests: evita cargar dependencias pesadas del app factory."""
import sys
from unittest.mock import MagicMock

_MOCKS = [
    "stripe",
    "flask",
    "flask_cors",
    "flask_jwt_extended",
    "flask_migrate",
    "flask_sqlalchemy",
    "google",
    "google.generativeai",
    "google.cloud",
    "google.cloud.vision",
    "google.cloud.storage",
    "google.auth",
    "google.auth.exceptions",
    "cloudinary",
    "cloudinary.uploader",
    "resend",
    "sqlalchemy",
    "sqlalchemy.exc",
    "werkzeug",
    "werkzeug.security",
    "dotenv",
    "requests",
    "requests.exceptions",
    "spacy",
]

for name in _MOCKS:
    sys.modules.setdefault(name, MagicMock())

# Submódulos de google
sys.modules.setdefault("google.auth.exceptions", MagicMock())
sys.modules.setdefault("google.auth.exceptions.DefaultCredentialsError", Exception)
