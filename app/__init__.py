"""
Fábrica de la aplicación Flask (Application Factory).
Configura extensiones, CORS y Blueprints.
"""
import os
from flask import Flask
from dotenv import load_dotenv
import stripe
from sqlalchemy import text

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
        if os.getenv('GOOGLE_CREDENTIALS_JSON'):
            with open(credentials_path, 'w', encoding='utf-8') as f:
                f.write(os.getenv('GOOGLE_CREDENTIALS_JSON'))

        if os.path.exists(credentials_path):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Nota: Configuración Google omitida: {e}")

    # --- INICIALIZAR EXTENSIONES ---
    db.init_app(app)

    # 🚑 PARCHE DE EMERGENCIA DB (Auto-Fix Columnas Faltantes) 🚑
    with app.app_context():
        try:
            db.create_all()
            with db.engine.connect() as conn:
                # Intento 1: Tabla 'cliente' (según logs de error)
                try:
                    conn.execute(text("ALTER TABLE cliente ADD COLUMN IF NOT EXISTS direccion VARCHAR(200)"))
                    conn.commit()
                    print("✅ DB Patch: Columna 'direccion' añadida a 'cliente'.")
                except Exception: # pylint: disable=broad-exception-caught
                    pass
                
                # Intento 2: Tabla 'clientes' (según modelo actual)
                try:
                    conn.execute(text("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS direccion VARCHAR(200)"))
                    conn.commit()
                    print("✅ DB Patch: Columna 'direccion' añadida a 'clientes'.")
                except Exception: # pylint: disable=broad-exception-caught
                    pass
                    
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"⚠️ Error leve en DB Patch: {e}")
    # ----------------------------------------------------

    # --- CONFIGURACIÓN CORS ---
    cors.init_app(app, resources={r"/*": {
        "origins": [
            "https://kiq.es",
            "https://www.kiq.es",
            "https://kiq-nextjs-tailwind.vercel.app",
            "http://localhost:3000",
            "http://localhost:3001"
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": [
            "Content-Type", "Authorization", "X-Requested-With", "Cache-Control"
        ],
        "supports_credentials": True
    }})

    jwt.init_app(app)
    migrate.init_app(app, db)

    # --- REGISTRO DE RUTAS ---
    app.register_blueprint(calculator_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(cliente_bp, url_prefix='/api')
    app.register_blueprint(montador_bp, url_prefix='/api')
    app.register_blueprint(outlet_bp, url_prefix='/api')
    app.register_blueprint(order_bp, url_prefix='/api')
    app.register_blueprint(webhooks_bp)

    return app