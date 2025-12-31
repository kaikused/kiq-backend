"""
Define y exporta las instancias de las extensiones de Flask (DB, CORS, JWT).
"""
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_jwt_extended import JWTManager  # <-- AÑADE ESTA LÍNEA
from flask_migrate import Migrate

# Simplemente creamos las instancias aquí
db = SQLAlchemy()
cors = CORS()
jwt = JWTManager()  # <-- AÑADE ESTA LÍNEA
migrate = Migrate()

# <-- ¡Asegúrate de que haya una línea vacía aquí al final!
