"""
Fábrica de la aplicación Flask (Application Factory).
Configura extensiones, CORS y Blueprints.
"""
import os
from flask import Flask
from dotenv import load_dotenv
import stripe

# Importamos las extensiones
from .extensions import db, cors, jwt, migrate

# Importamos las rutas
from .calculator import calculator_bp
from .routes.auth_routes import auth_bp
from .routes.cliente_routes import cliente_bp
from .routes.montador_routes import montador_bp
from .routes.outlet_routes import outlet_bp
from .routes.order_routes import order_bp
from .routes.public_routes import public_bp

from .webhooks import webhooks_bp

def create_app():
    """Crea la app Flask."""
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)

    # --- CONFIGURACIÓN BÁSICA ---
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
        'DATABASE_URL', 'sqlite:///default_dev.db'
    )
    # Corrección para Render (Postgres requiere postgresql://)
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri and db_uri.startswith("postgres://"):
        app.config['SQLALCHEMY_DATABASE_URI'] = db_uri.replace(
            "postgres://", "postgresql://", 1
        )

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "dev-secret")

    # Configuración Stripe
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    app.config["STRIPE_PUBLIC_KEY"] = os.getenv("STRIPE_PUBLIC_KEY")

    # --- CREDENCIALES GOOGLE (Vision AI) ---
    try:
        credentials_path = os.path.join(app.root_path, '..', 'google-credentials.json')
        # Si la variable de entorno tiene el JSON entero, lo volcamos a un archivo
        if os.getenv('GOOGLE_CREDENTIALS_JSON'):
            with open(credentials_path, 'w', encoding='utf-8') as f:
                f.write(os.getenv('GOOGLE_CREDENTIALS_JSON'))

        if os.path.exists(credentials_path):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Nota: Configuración Google omitida: {e}")

    # --- INICIALIZAR EXTENSIONES ---
    db.init_app(app)

    # --- CONFIGURACIÓN CORS (PROFESIONAL) ---
    # Permitimos acceso total desde tu dominio real y localhost
    # supports_credentials=True es el estándar para permitir cookies/tokens seguros
    cors.init_app(app, resources={r"/*": {
        "origins": [
            "https://kiq.es",
            "https://www.kiq.es",
            "https://kiq-nextjs-tailwind.vercel.app",  
            "http://localhost:3000",
            "http://localhost:3001"
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
        "supports_credentials": True
    }})
    # -------------------------------------

    jwt.init_app(app)
    migrate.init_app(app, db)

    # --- REGISTRO DE RUTAS (BLUEPRINTS) ---

    # Calculadora (Prioridad)
    app.register_blueprint(calculator_bp)

    # Rutas Públicas
    app.register_blueprint(public_bp)

    # API Rutas (Prefijo /api)
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(cliente_bp, url_prefix='/api')
    app.register_blueprint(montador_bp, url_prefix='/api')
    app.register_blueprint(outlet_bp, url_prefix='/api')
    app.register_blueprint(order_bp, url_prefix='/api')

    # Webhooks (Stripe)
    app.register_blueprint(webhooks_bp)

    return app