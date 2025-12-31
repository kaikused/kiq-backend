"""
Fábrica de la aplicación Flask (Application Factory).
Este archivo crea y configura la instancia de la app Flask.
"""
# --- Imports de librerías estándar ---
import os

# --- Imports de terceros ---
from flask import Flask
from dotenv import load_dotenv
import stripe

# --- Imports locales ---
from .models import Cliente, Trabajo, Link, Montador

# Importamos las rutas modulares
from .routes.auth_routes import auth_bp
from .routes.cliente_routes import cliente_bp
from .routes.montador_routes import montador_bp
from .routes.outlet_routes import outlet_bp
# 👇 NUEVO: Importamos el Blueprint de Pedidos
from .routes.order_routes import order_bp 

# Mantenemos los módulos externos que ya tenías
from .calculator import calculator_bp
from .webhooks import webhooks_bp 
from .extensions import db, cors, jwt, migrate

def create_app():
    """
    Fábrica de la aplicación Flask (Application Factory).
    """
    load_dotenv()  # Carga las variables de .env

    app = Flask(__name__, instance_relative_config=True)

    # --- Configuración de la App ---
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
        'DATABASE_URL', 'sqlite:///default_dev.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Guardamos la clave por defecto en una variable para acortar la línea
    default_jwt_key = "una-clave-secreta-muy-fuerte-por-defecto"
    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", default_jwt_key)

    # --- CONFIGURACIÓN DE STRIPE ---
    # La API key debe establecerse globalmente una vez
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    app.config["STRIPE_PUBLIC_KEY"] = os.getenv("STRIPE_PUBLIC_KEY")

    # Configuración de Google Credentials (INTACTO)
    try:
        credentials_path = os.path.join(
            app.root_path, '..', 'google-credentials.json'
        )
        if os.path.exists(credentials_path):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
        else:
            print("Advertencia: No se encontró 'google-credentials.json'.")
    # Se mantiene la excepción genérica por ser un chequeo de I/O y entorno
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Advertencia: Error en credenciales Google: {e}")

    # --- Inicializar Extensiones ---
    db.init_app(app)
    cors.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)

    # --- Registrar Blueprints (RUTAS) ---
    
    # 1. Nuevas Rutas Modulares
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(cliente_bp, url_prefix='/api')
    app.register_blueprint(montador_bp, url_prefix='/api')
    app.register_blueprint(outlet_bp, url_prefix='/api')
    # 👇 NUEVO: Registramos la ruta de pedidos
    app.register_blueprint(order_bp, url_prefix='/api') 

    # 2. Módulos Auxiliares (Intactos)
    app.register_blueprint(calculator_bp)
    app.register_blueprint(webhooks_bp) 

    # --- Crear tablas de BD ---
    with app.app_context():
        # Respetamos tu configuración de Alembic:
        # IMPORTANTE: Se comenta esta línea porque entra en conflicto con Alembic.
        # db.create_all()
        pass

    # Devolvemos la aplicación creada y configurada
    return app