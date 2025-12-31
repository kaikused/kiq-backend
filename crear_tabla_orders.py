"""
Script de mantenimiento para crear la tabla 'orders' en la base de datos.
Esta tabla gestiona los pedidos del Kiq Outlet de forma separada a los trabajos.
"""
from sqlalchemy import text
from app import create_app
from app.extensions import db

app = create_app()

with app.app_context():
    print("🏗️  Creando la tabla de Pedidos (Kiq Commerce)...")

    # Definimos la tabla de PEDIDOS separada de TRABAJOS
    SQL_COMMAND = """
    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,

        -- Relación con el Producto vendido
        product_id INTEGER NOT NULL REFERENCES product(id),

        -- ¿Quién compra? (Siempre un Cliente por ahora)
        comprador_id INTEGER NOT NULL REFERENCES cliente(id),

        -- ¿Quién vende? (Guardamos la referencia para facilitar consultas de ventas)
        vendedor_montador_id INTEGER REFERENCES montador(id),
        vendedor_cliente_id INTEGER REFERENCES cliente(id),

        -- Detalles Económicos
        total NUMERIC(10, 2) NOT NULL,
        metodo_pago VARCHAR(20) NOT NULL, -- 'stripe' o 'efectivo'
        payment_intent_id VARCHAR(100),   -- ID de la transacción

        -- Estado del Pedido (Logística)
        -- 'pendiente_pago': Creado pero no pagado
        -- 'pagado': Pagado/Reservado (Dinero en Kiq)
        -- 'entregado': El comprador ya lo tiene
        -- 'cancelado': Reembolsado o anulado
        estado VARCHAR(50) NOT NULL DEFAULT 'pendiente_pago',

        -- Auditoría
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
    );

    -- Índices para búsquedas rápidas (Mis Compras / Mis Ventas)
    CREATE INDEX IF NOT EXISTS idx_orders_comprador ON orders(comprador_id);
    CREATE INDEX IF NOT EXISTS idx_orders_vendedor_m ON orders(vendedor_montador_id);
    CREATE INDEX IF NOT EXISTS idx_orders_estado ON orders(estado);
    """

    try:
        db.session.execute(text(SQL_COMMAND))
        db.session.commit()
        print("✅ ¡Tabla 'orders' creada con éxito!")
        print("   La arquitectura de Comercio ahora está separada de Servicios.")
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"❌ Error: {e}")