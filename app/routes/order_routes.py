"""
Rutas para el motor de comercio (Kiq Commerce).
Gestiona la creación de pedidos (Orders), pagos y consultas de historial.
"""
# 1. Imports de terceros
import stripe
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
# Eliminado SQLAlchemyError que no se usaba

# 2. Imports locales
from app.models import Product, Order, Cliente
from app.extensions import db

order_bp = Blueprint('orders', __name__)

# --- COMPRA CON TARJETA (STRIPE) ---

@order_bp.route('/orders/crear-intent-stripe', methods=['POST'])
@jwt_required()
def crear_intent_stripe():
    """
    Paso 1: Inicia el proceso de pago con tarjeta.
    Genera un PaymentIntent en Stripe pero NO crea la orden todavía.
    """
    data = request.json
    product_id = data.get('product_id')

    # Validaciones
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "Producto no encontrado"}), 404
    if product.estado != 'disponible':
        return jsonify({"error": "Este producto ya no está disponible"}), 400

    try:
        # Creamos la intención en Stripe
        intent = stripe.PaymentIntent.create(
            amount=int(float(product.precio) * 100), # Céntimos
            currency='eur',
            automatic_payment_methods={'enabled': True},
            metadata={
                'tipo': 'orden_compra',
                'product_id': str(product.id),
                'comprador_id': get_jwt_identity()
            }
        )

        return jsonify({
            'client_secret': intent.client_secret,
            'payment_intent_id': intent.id
        }), 200

    except stripe.StripeError as e:
        return jsonify({"error": f"Error Stripe: {e.user_message}"}), 500
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error creando intent orden: {e}")
        return jsonify({"error": "Error interno"}), 500


@order_bp.route('/orders/confirmar-stripe', methods=['POST'])
@jwt_required()
def confirmar_compra_stripe():
    """
    Paso 2: El cliente pagó en Stripe. Creamos la Order en BD y marcamos producto.
    """
    user_id = int(get_jwt_identity())
    data = request.json
    product_id = data.get('product_id')
    payment_intent_id = data.get('payment_intent_id')

    product = Product.query.get(product_id)
    if not product or product.estado != 'disponible':
        return jsonify({"error": "Producto no disponible o inexistente"}), 400

    try:
        # 1. Crear el Pedido (Order)
        nueva_orden = Order(
            product_id=product.id,
            comprador_id=user_id,
            vendedor_montador_id=product.montador_id,
            vendedor_cliente_id=product.cliente_id,
            total=float(product.precio),
            metodo_pago='stripe',
            payment_intent_id=payment_intent_id,
            estado='pagado' # Dinero recibido en Stripe
        )

        # 2. Actualizar el Producto
        product.estado = 'vendido'

        db.session.add(nueva_orden)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "¡Compra realizada con éxito!",
            "order_id": nueva_orden.id
        }), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error confirmando orden stripe: {e}")
        return jsonify({"error": "Error registrando el pedido"}), 500


# --- COMPRA EN EFECTIVO (RESERVA) ---

@order_bp.route('/orders/crear-reserva', methods=['POST'])
@jwt_required()
def crear_reserva_efectivo():
    """
    El cliente quiere pagar en mano.
    Creamos la Order como 'pendiente_pago' y reservamos el producto.
    """
    user_id = int(get_jwt_identity())
    data = request.json
    product_id = data.get('product_id')

    product = Product.query.get(product_id)
    if not product or product.estado != 'disponible':
        return jsonify({"error": "Producto no disponible"}), 400

    try:
        # 1. Crear el Pedido (Reserva)
        nueva_orden = Order(
            product_id=product.id,
            comprador_id=user_id,
            vendedor_montador_id=product.montador_id,
            vendedor_cliente_id=product.cliente_id,
            total=float(product.precio),
            metodo_pago='efectivo',
            estado='pendiente_pago' # Se paga en mano
        )

        # 2. Actualizar el Producto
        product.estado = 'reservado'

        db.session.add(nueva_orden)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Producto reservado. Coordina la entrega.",
            "order_id": nueva_orden.id
        }), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error creando reserva: {e}")
        return jsonify({"error": "Error al reservar"}), 500


# --- CONSULTA DE PEDIDOS (HISTORIAL COMPRAS) ---

@order_bp.route('/orders/mis-compras', methods=['GET'])
@jwt_required()
def get_mis_compras():
    """Devuelve la lista de cosas que he comprado."""
    user_id = int(get_jwt_identity())
    claims = get_jwt()
    
    # CORREGIDO: Usamos 'rol' en lugar de 'tipo'
    if claims.get('rol') != 'cliente':
        return jsonify({"error": "Solo clientes compran"}), 403

    try:
        ordenes = Order.query.filter_by(comprador_id=user_id).order_by(
            Order.created_at.desc()
        ).all()
        res = []
        for o in ordenes:
            # Obtenemos datos frescos del producto
            prod = Product.query.get(o.product_id)
            if prod: # Protección por si el producto se borró
                res.append({
                    "order_id": o.id,
                    "fecha": o.created_at.isoformat(),
                    "estado_pedido": o.estado,
                    "total": o.total,
                    "metodo_pago": o.metodo_pago,
                    "producto": {
                        "id": prod.id,
                        "titulo": prod.titulo,
                        "imagen": prod.imagenes_urls[0] if prod.imagenes_urls else None,
                        "ubicacion": prod.ubicacion
                    }
                })
        return jsonify(res), 200
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error listando compras: {e}")
        return jsonify({"error": "Error obteniendo compras"}), 500


# --- CONSULTA DE VENTAS (HISTORIAL MONTADOR) ---

@order_bp.route('/orders/mis-ventas', methods=['GET'])
@jwt_required()
def get_mis_ventas():
    """
    Devuelve la lista de productos que el usuario (Montador) ha vendido.
    """
    user_id = int(get_jwt_identity())
    claims = get_jwt()
    
    # CORREGIDO: Usamos 'rol' en lugar de 'tipo'
    rol = claims.get('rol')

    if rol != 'montador':
        return jsonify({"error": "Solo montadores tienen ventas"}), 403

    try:
        # Buscamos órdenes donde este usuario sea el vendedor
        ventas = Order.query.filter_by(vendedor_montador_id=user_id).order_by(
            Order.created_at.desc()
        ).all()

        res = []
        for v in ventas:
            prod = Product.query.get(v.product_id)
            comprador = Cliente.query.get(v.comprador_id)

            if prod and comprador: # Protección de datos nulos
                res.append({
                    "order_id": v.id,
                    "fecha": v.created_at.isoformat(),
                    "estado_pedido": v.estado, # 'pagado', 'pendiente_pago', 'entregado'
                    "total": v.total,
                    "metodo_pago": v.metodo_pago,
                    "producto": {
                        "id": prod.id,
                        "titulo": prod.titulo,
                        "imagen": prod.imagenes_urls[0] if prod.imagenes_urls else None
                    },
                    "comprador": {
                        "nombre": comprador.nombre,
                        "id": comprador.id
                    }
                })
        return jsonify(res), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error listando ventas: {e}")
        return jsonify({"error": "Error obteniendo ventas"}), 500