"""Mocks de dependencias antes de importar módulos de app."""
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
    sys.modules[name] = MagicMock()

sys.modules["google.auth.exceptions"].DefaultCredentialsError = Exception
