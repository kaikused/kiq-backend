"""
Script de mantenimiento para crear la tabla 'product' (Kiq Outlet).
Define la estructura para la compra-venta de muebles con seguridad de propietario.
"""
from sqlalchemy import text
from app import create_app
from app.extensions import db

app = create_app()

with app.app_context():
    print("🏗️  Creando la tabla de Productos (Kiq Outlet)...")
    
    # Definimos la tabla SQL con lógica polimórfica (Cliente O Montador)
    # Incluimos payment_intent_id y metodo_pago para que nazca completa.
    SQL_COMMAND = """
    CREATE TABLE IF NOT EXISTS product (
        id SERIAL PRIMARY KEY,
        
        -- Información básica
        titulo VARCHAR(200) NOT NULL,
        descripcion TEXT,
        precio NUMERIC(10, 2) NOT NULL,
        
        -- Estado y Multimedia
        estado VARCHAR(50) DEFAULT 'disponible', 
        imagenes_urls JSON, 
        
        -- Pagos y Logística
        ubicacion VARCHAR(200),
        payment_intent_id VARCHAR(100),
        metodo_pago VARCHAR(20) DEFAULT 'stripe',
        
        -- Auditoría
        fecha_creacion TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
        
        -- DUEÑO (Puede ser Cliente o Montador)
        cliente_id INTEGER REFERENCES cliente(id),
        montador_id INTEGER REFERENCES montador(id),
        
        -- Regla de seguridad: Al menos uno debe ser el dueño
        CONSTRAINT check_owner CHECK (cliente_id IS NOT NULL OR montador_id IS NOT NULL)
    );
    
    -- Índices para velocidad
    CREATE INDEX IF NOT EXISTS idx_product_estado ON product(estado);
    CREATE INDEX IF NOT EXISTS idx_product_fecha ON product(fecha_creacion DESC);
    """
    
    try:
        db.session.execute(text(SQL_COMMAND))
        db.session.commit()
        print("✅ ¡Tabla 'product' creada con éxito!")
        print("   Ahora tanto Clientes como Montadores pueden publicar cosas.")
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"❌ Error: {e}")