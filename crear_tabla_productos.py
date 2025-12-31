from app import create_app
from app.extensions import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("🏗️  Creando la tabla de Productos (Kiq Outlet)...")
    
    # Definimos la tabla SQL con lógica polimórfica (Cliente O Montador)
    sql = """
    CREATE TABLE IF NOT EXISTS product (
        id SERIAL PRIMARY KEY,
        
        -- Información básica
        titulo VARCHAR(200) NOT NULL,
        descripcion TEXT,
        precio NUMERIC(10, 2) NOT NULL,
        
        -- Estado y Multimedia
        estado VARCHAR(50) DEFAULT 'disponible', 
        imagenes_urls JSON, 
        
        -- Ubicación (Clave para el Feed)
        ubicacion VARCHAR(200),
        
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
        db.session.execute(text(sql))
        db.session.commit()
        print("✅ ¡Tabla 'product' creada con éxito!")
        print("   Ahora tanto Clientes como Montadores pueden publicar cosas.")
    except Exception as e:
        print(f"❌ Error: {e}")