"""
Fábrica de la aplicación Flask (Application Factory).
"""
import os
from flask import Flask
from dotenv import load_dotenv
import stripe

from .extensions import db, cors, jwt, migrate

# Importamos las rutas
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

    # Configuración
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
        'DATABASE_URL', 'sqlite:///default_dev.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "dev-secret")
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    app.config["STRIPE_PUBLIC_KEY"] = os.getenv("STRIPE_PUBLIC_KEY")

    # Credenciales Google
    try:
        credentials_path = os.path.join(app.root_path, '..', 'google-credentials.json')
        if os.getenv('GOOGLE_CREDENTIALS_JSON'):
            with open(credentials_path, 'w', encoding='utf-8') as f:
                f.write(os.getenv('GOOGLE_CREDENTIALS_JSON'))

        if os.path.exists(credentials_path):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Nota: Configuración Google omitida: {e}")

    # Inicializar extensiones
    db.init_app(app)
    cors.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)

    # Registro de Rutas
    app.register_blueprint(public_bp)

    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(cliente_bp, url_prefix='/api')
    app.register_blueprint(montador_bp, url_prefix='/api')
    app.register_blueprint(outlet_bp, url_prefix='/api')
    app.register_blueprint(order_bp, url_prefix='/api')

    app.register_blueprint(webhooks_bp)

    return app