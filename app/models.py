"""
Define los modelos de la base de datos para la aplicación.
Incluye Link, Cliente, Trabajo, Montador, Sistema de Gemas, Verificación, PRODUCTOS y PEDIDOS.
"""
from datetime import datetime, timedelta
import random
from werkzeug.security import generate_password_hash, check_password_hash
# Imports de terceros
from sqlalchemy import Enum
# Imports locales
from .extensions import db


# --- MODELO DE VERIFICACIÓN ---
class VerificationCode(db.Model):
    """Almacena códigos temporales de verificación de email."""
    __tablename__ = 'verification_codes'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    code = db.Column(db.String(6), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def is_valid(self):
        """Verifica si el código se creó hace menos de 15 minutos."""
        return datetime.utcnow() < self.created_at + timedelta(minutes=15)

    @staticmethod
    def generate_code():
        """Genera un código numérico aleatorio de 6 dígitos."""
        return str(random.randint(100000, 999999))


# --- MODELO DE ENLACES ---
class Link(db.Model):
    """Modelo para los enlaces acortados de imágenes."""
    id = db.Column(db.Integer, primary_key=True)
    original_url = db.Column(db.String(512), nullable=False)
    short_code = db.Column(db.String(10), unique=True, nullable=False)

    def __repr__(self):
        return f"<Link {self.short_code}>"

# --- SISTEMA DE GEMAS (GAMIFICACIÓN) ---

class Wallet(db.Model):
    """
    Billetera de Gemas virtual.
    """
    id = db.Column(db.Integer, primary_key=True)
    saldo = db.Column(db.Integer, default=0, nullable=False)
    fecha_actualizacion = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relaciones Polimórficas
    cliente_id = db.Column(
        db.Integer, db.ForeignKey('cliente.id'), nullable=True, unique=True
    )
    montador_id = db.Column(
        db.Integer, db.ForeignKey('montador.id'), nullable=True, unique=True
    )

    transacciones = db.relationship('GemTransaction', backref='wallet', lazy=True)

    def __repr__(self):
        return f"<Wallet ID: {self.id} - Saldo: {self.saldo} 💎>"

class GemTransaction(db.Model):
    """
    Historial de movimientos de Gemas.
    """
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey('wallet.id'), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    tipo = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.String(200), nullable=True)
    fecha = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    trabajo_id = db.Column(db.Integer, db.ForeignKey('trabajo.id'), nullable=True)

    def __repr__(self):
        return f"<GemTx {self.cantidad} | {self.tipo}>"


# --- USUARIOS ---

class Cliente(db.Model):
    """Modelo para los Clientes."""
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    telefono = db.Column(db.String(20))
    fecha_registro = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    foto_url = db.Column(db.String(500), nullable=True)

    # Relaciones
    trabajos = db.relationship('Trabajo', backref='cliente', lazy=True)
    wallet = db.relationship(
        'Wallet', backref='cliente_owner', uselist=False, cascade="all, delete-orphan"
    )
    productos_en_venta = db.relationship(
        'Product', backref='vendedor_cliente', lazy=True
    )

    # Relación: Compras realizadas (Kiq Commerce)
    compras = db.relationship(
        'Order', foreign_keys='Order.comprador_id', backref='comprador', lazy=True
    )

    def set_password(self, password):
        """Crea el hash de la contraseña."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verifica el hash de la contraseña."""
        return check_password_hash(self.password_hash, password)

class Montador(db.Model):
    """Modelo para los Montadores."""
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    telefono = db.Column(db.String(20), nullable=True)
    zona_servicio = db.Column(db.String(200), nullable=True)
    fecha_registro = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    foto_url = db.Column(db.String(500), nullable=True)
    stripe_account_id = db.Column(db.String(100), nullable=True)
    bono_visto = db.Column(db.Boolean, default=False)

    # Relaciones
    trabajos_asignados = db.relationship('Trabajo', backref='montador', lazy=True)
    wallet = db.relationship(
        'Wallet', backref='montador_owner', uselist=False, cascade="all, delete-orphan"
    )
    productos_en_venta = db.relationship(
        'Product', backref='vendedor_montador', lazy=True
    )

    # Relación: Ventas realizadas
    ventas = db.relationship(
        'Order', foreign_keys='Order.vendedor_montador_id',
        backref='vendedor_montador', lazy=True
    )

    def set_password(self, password):
        """Crea el hash de la contraseña."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verifica el hash de la contraseña."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<Montador {self.id} - {self.nombre}>"

# --- TRABAJOS (SERVICIOS) ---
class Trabajo(db.Model):
    """Modelo para Servicios de Montaje."""
    ESTADOS_TRABAJO = [
        'cotizacion', 'pendiente', 'aceptado', 'en_progreso', 'revision_cliente',
        'completado', 'cancelado', 'incidencia', 'aprobado_cliente_stripe',
        'cancelado_incidencia'
    ]
    id = db.Column(db.Integer, primary_key=True)
    descripcion = db.Column(db.Text, nullable=False)
    direccion = db.Column(db.String(200), nullable=False)
    precio_calculado = db.Column(db.Float, nullable=False)
    estado = db.Column(
        Enum(*ESTADOS_TRABAJO, name='estado_trabajo_enum'),
        nullable=False, default='pendiente'
    )
    fecha_creacion = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    montador_id = db.Column(db.Integer, db.ForeignKey('montador.id'), nullable=True)
    payment_intent_id = db.Column(db.String(100), nullable=True, unique=True)
    metodo_pago = db.Column(
        db.String(20), nullable=False, default='stripe', server_default='stripe'
    )
    imagenes_urls = db.Column(db.JSON, nullable=True)
    etiquetas = db.Column(db.JSON, nullable=True)
    desglose = db.Column(db.JSON, nullable=True)
    foto_finalizacion = db.Column(db.String(512), nullable=True)

    def __repr__(self):
        return f"<Trabajo {self.id} - {self.estado}>"

# --- PRODUCTOS (OUTLET) ---
class Product(db.Model):
    """Muebles de segunda mano (Listado)."""
    __tablename__ = 'product'
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    precio = db.Column(db.Numeric(10, 2), nullable=False)
    estado = db.Column(db.String(50), default='disponible', nullable=False)
    ubicacion = db.Column(db.String(200), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    imagenes_urls = db.Column(db.JSON, nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=True)
    montador_id = db.Column(db.Integer, db.ForeignKey('montador.id'), nullable=True)
    # Columnas legacy o para estado del anuncio
    payment_intent_id = db.Column(db.String(100), nullable=True)
    metodo_pago = db.Column(db.String(20), default='stripe')

    def __repr__(self):
        return f"<Product {self.id} - {self.titulo}>"

# --- CLASE: PEDIDOS (KIQ COMMERCE) ---
class Order(db.Model):
    """
    Representa una transacción de compra-venta de un producto.
    Separado de 'Trabajo' para limpiar la lógica de negocio.
    """
    __tablename__ = 'orders'

    id = db.Column(db.Integer, primary_key=True)

    # Qué se vendió
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    product = db.relationship('Product', backref=db.backref('orders', lazy=True))

    # Quién compró
    comprador_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)

    # Quién vendió
    vendedor_montador_id = db.Column(
        db.Integer, db.ForeignKey('montador.id'), nullable=True
    )
    vendedor_cliente_id = db.Column(
        db.Integer, db.ForeignKey('cliente.id'), nullable=True
    )

    # Dinero
    total = db.Column(db.Float, nullable=False)
    metodo_pago = db.Column(db.String(20), nullable=False) # 'stripe', 'efectivo'
    payment_intent_id = db.Column(db.String(100), nullable=True) # ID de Stripe

    # Estado del Pedido
    estado = db.Column(db.String(50), nullable=False, default='pendiente_pago')

    # Auditoría
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<Order #{self.id} - {self.total}€ - {self.estado}>"