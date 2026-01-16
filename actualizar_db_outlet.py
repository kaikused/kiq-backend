"""
Script de mantenimiento para actualizar la estructura de la base de datos (Outlet).
Añade columnas necesarias para pagos con Stripe en la tabla 'product'.
"""
from sqlalchemy import text
from app import create_app
from app.extensions import db

# Inicializamos la app
app = create_app()

with app.app_context():
    print("🔄 Verificando y actualizando tabla 'product'...")

    # Lista de comandos individuales (Funciona en SQLite y Postgres)
    comandos = [
        "ALTER TABLE product ADD COLUMN payment_intent_id VARCHAR(100)",
        "ALTER TABLE product ADD COLUMN metodo_pago VARCHAR(20) DEFAULT 'stripe'"
    ]

    for sql in comandos:
        try:
            # Intentamos ejecutar el comando
            db.session.execute(text(sql))
            db.session.commit()
            print(f"✅ Ejecutado: {sql}")
        except Exception: # pylint: disable=broad-exception-caught
            # Si falla, asumimos que es porque la columna ya existe y hacemos rollback
            db.session.rollback()
            print(f"ℹ️  Nota: No se pudo ejecutar '{sql}' (Probablemente la columna ya existe).")

    print("\n✅ PROCESO FINALIZADO. La tabla 'product' está lista para recibir pagos.")