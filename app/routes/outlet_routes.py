"""
Rutas para el Módulo Kiq Outlet (Marketplace de Segunda Mano).
Permite publicar productos, consultar el feed, iniciar chats y PAGAR.
"""
import stripe
from flask import Blueprint, request, jsonify, make_response
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from sqlalchemy.exc import SQLAlchemyError

from app.models import Product, Montador, Cliente, Trabajo
from app.extensions import db
from app.storage import upload_image_to_gcs

outlet_bp = Blueprint('outlet', __name__)

# --- GESTIÓN DE PRODUCTOS ---

@outlet_bp.route('/outlet/publicar', methods=['POST'])
@jwt_required()
def publicar_producto_outlet():
    """Permite a un Montador (o Cliente) publicar un mueble recuperado."""
    user_id = get_jwt_identity()
    claims = get_jwt()
    # CORREGIDO: Usamos 'rol' en lugar de 'tipo'
    tipo_usuario = claims.get('rol')

    titulo = request.form.get('titulo')
    precio = request.form.get('precio')

    if not titulo or not precio:
        return jsonify({"error": "Título y precio son obligatorios"}), 400

    if 'imagen' not in request.files:
        return jsonify({"error": "Falta la foto del producto"}), 400

    file = request.files['imagen']
    if file.filename == '':
        return jsonify({"error": "Archivo vacío"}), 400

    try:
        url_publica = upload_image_to_gcs(file, folder="outlet")
        if not url_publica:
            return jsonify({"error": "Error al subir imagen"}), 500

        nuevo_prod = Product(
            titulo=titulo,
            descripcion=request.form.get('descripcion', ''),
            precio=float(precio),
            estado='disponible',
            imagenes_urls=[url_publica],
            ubicacion=request.form.get('ubicacion', 'Málaga')
        )

        if tipo_usuario == 'montador':
            nuevo_prod.montador_id = int(user_id)
        else:
            nuevo_prod.cliente_id = int(user_id)

        db.session.add(nuevo_prod)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "¡Producto publicado!",
            "product_id": nuevo_prod.id,
            "foto_url": url_publica
        }), 201

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error BD outlet/publicar: {e}")
        return jsonify({"error": "Error de base de datos"}), 500
    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error general outlet/publicar: {e}")
        return jsonify({"error": str(e)}), 500


@outlet_bp.route('/outlet/feed', methods=['GET'])
def get_outlet_feed():
    """Devuelve el muro de productos disponibles."""
    try:
        # 1. Filtramos estrictamente por 'disponible'
        productos = Product.query.filter_by(estado='disponible').order_by(
            Product.fecha_creacion.desc()
        ).limit(50).all()

        # LOG DEBUG: Ver qué está devolviendo la BD realmente
        # print(f"🔍 FEED: Encontrados {len(productos)}")

        res = []
        for p in productos:
            vendedor_nombre = "Usuario Kiq"
            vendedor_tipo = "cliente"
            vendedor_foto = None

            if p.montador_id:
                m = Montador.query.get(p.montador_id)
                if m:
                    vendedor_nombre = m.nombre
                    vendedor_tipo = "montador"
                    vendedor_foto = m.foto_url
            elif p.cliente_id:
                c = Cliente.query.get(p.cliente_id)
                if c:
                    vendedor_nombre = c.nombre
                    vendedor_foto = c.foto_url

            res.append({
                "id": p.id,
                "titulo": p.titulo,
                "precio": float(p.precio),
                "imagen": p.imagenes_urls[0] if p.imagenes_urls else None,
                "ubicacion": p.ubicacion,
                "vendedor": {
                    "nombre": vendedor_nombre,
                    "tipo": vendedor_tipo,
                    "foto": vendedor_foto
                },
                "fecha": p.fecha_creacion.isoformat()
            })

        # 2. Preparamos la respuesta
        response = make_response(jsonify(res), 200)        
        # 3. 🛡️ FORZAR NO-CACHE (Crucial para que desaparezcan los vendidos al instante)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

        return response

    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error en get_outlet_feed: {e}")
        return jsonify({"error": "Error cargando el feed"}), 500


@outlet_bp.route('/outlet/producto/<int:product_id>', methods=['GET'])
def get_producto_detalle(product_id):
    """Obtiene el detalle de un producto público."""
    try:
        p = Product.query.get(product_id)
        if not p:
            return jsonify({"error": "Producto no encontrado"}), 404

        vendedor_nombre = "Usuario Kiq"
        vendedor_tipo = "cliente"
        vendedor_foto = None
        vendedor_id = None

        if p.montador_id:
            m = Montador.query.get(p.montador_id)
            if m:
                vendedor_nombre = m.nombre
                vendedor_tipo = "montador"
                vendedor_foto = m.foto_url
                vendedor_id = m.id
        elif p.cliente_id:
            c = Cliente.query.get(p.cliente_id)
            if c:
                vendedor_nombre = c.nombre
                vendedor_foto = c.foto_url
                vendedor_id = c.id

        data = {
            "id": p.id,
            "titulo": p.titulo,
            "descripcion": p.descripcion,
            "precio": float(p.precio),
            "imagenes": p.imagenes_urls if p.imagenes_urls else [],
            "ubicacion": p.ubicacion,
            "estado": p.estado,
            "fecha": p.fecha_creacion.isoformat(),
            "vendedor": {
                "id": vendedor_id,
                "nombre": vendedor_nombre,
                "tipo": vendedor_tipo,
                "foto": vendedor_foto
            }
        }
        
        # También desactivamos caché para el detalle
        response = make_response(jsonify(data), 200)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error en get_producto_detalle: {e}")
        return jsonify({"error": "Error interno"}), 500


@outlet_bp.route('/outlet/iniciar-chat', methods=['POST'])
@jwt_required()
def iniciar_chat_outlet():
    """Crea un 'Trabajo' ficticio para chatear sobre un producto."""
    try:
        user_id = int(get_jwt_identity())
        claims = get_jwt()
        # CORREGIDO: Usamos 'rol' en lugar de 'tipo'
        tipo_comprador = claims.get('rol')

        data = request.json
        product_id = data.get('producto_id')

        if not product_id:
            return jsonify({"error": "Falta ID producto"}), 400

        producto = Product.query.get(product_id)
        if not producto:
            return jsonify({"error": "Producto no encontrado"}), 404

        # Permitimos chatear si está reservado, PERO NO SI ESTÁ VENDIDO
        if producto.estado == 'vendido':
            return jsonify({"error": "Este producto ya se vendió."}), 400
              
        if producto.estado not in ['disponible', 'reservado']:
            return jsonify({"error": "No disponible"}), 400

        if not producto.montador_id:
            return jsonify({"error": "Vendedor no válido"}), 400

        vendedor_id = producto.montador_id

        if tipo_comprador == 'montador' and user_id == vendedor_id:
            return jsonify({"error": "No puedes chatear contigo mismo"}), 400

        # Buscar chat existente
        trabajos_existentes = Trabajo.query.filter_by(
            cliente_id=user_id,
            montador_id=vendedor_id
        ).all()

        job_id = None

        for t in trabajos_existentes:
            if t.etiquetas and isinstance(t.etiquetas, dict):
                if str(t.etiquetas.get('outlet_product_id')) == str(product_id):
                    job_id = t.id
                    break

        if not job_id:
            nuevo_chat = Trabajo(
                descripcion=f"Interés en Outlet: {producto.titulo}",
                direccion="Recogida Outlet",
                precio_calculado=float(producto.precio),
                cliente_id=user_id,
                montador_id=vendedor_id,
                estado='aceptado',
                metodo_pago='efectivo_gemas',
                etiquetas={'outlet_product_id': producto.id, 'tipo': 'outlet'},
                imagenes_urls=producto.imagenes_urls
            )
            db.session.add(nuevo_chat)
            db.session.commit()
            job_id = nuevo_chat.id

        return jsonify({
            "success": True,
            "job_id": job_id,
            "message": "Chat iniciado"
        }), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error en iniciar_chat_outlet: {e}")
        return jsonify({"error": str(e)}), 500


# --- MÓDULO DE PAGOS ---

@outlet_bp.route('/outlet/comprar/stripe', methods=['POST'])
@jwt_required()
def crear_intento_pago_producto():
    """Paso 1: Crear PaymentIntent en Stripe (Retención)."""
    data = request.json
    product_id = data.get('product_id')

    product = Product.query.get(product_id)
    if not product or product.estado != 'disponible':
        return jsonify({"error": "Producto no disponible"}), 400

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(float(product.precio) * 100),
            currency='eur',
            automatic_payment_methods={'enabled': True},
            capture_method='manual',
            metadata={
                'tipo': 'compra_outlet',
                'product_id': str(product.id),
                'comprador_id': get_jwt_identity()
            }
        )
        return jsonify({
            'client_secret': intent.client_secret,
            'payment_intent_id': intent.id
        }), 200

    except stripe.StripeError as e:
        return jsonify({"error": f"Stripe Error: {e.user_message}"}), 500
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error pago stripe outlet: {e}")
        return jsonify({"error": "Error interno"}), 500


@outlet_bp.route('/outlet/comprar/confirmar-stripe', methods=['POST'])
@jwt_required()
def confirmar_compra_stripe_outlet():
    """Paso 2: Confirmar reserva tras pago con tarjeta."""
    data = request.json
    product_id = data.get('product_id')
    payment_intent_id = data.get('payment_intent_id')

    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "No existe"}), 404

    product.estado = 'reservado'
    product.metodo_pago = 'stripe'
    product.payment_intent_id = payment_intent_id
    
    db.session.commit()
    
    return jsonify({"success": True, "message": "Producto reservado"}), 200


@outlet_bp.route('/outlet/mis-productos', methods=['GET'])
@jwt_required()
def get_mis_productos_publicados():
    """Devuelve TODOS los productos publicados por el usuario (disponibles o vendidos)."""
    user_id = int(get_jwt_identity())
    claims = get_jwt()

    try:
        # CORREGIDO: Usamos 'rol' en lugar de 'tipo'
        if claims.get('rol') == 'montador':
            productos = Product.query.filter_by(montador_id=user_id).order_by(
                Product.fecha_creacion.desc()
            ).all()
        else:
            productos = Product.query.filter_by(cliente_id=user_id).order_by(
                Product.fecha_creacion.desc()
            ).all()

        res = []
        for p in productos:
            res.append({
                "id": p.id,
                "titulo": p.titulo,
                "precio": float(p.precio),
                "estado": p.estado,  # disponible, reservado, vendido
                "imagen": p.imagenes_urls[0] if p.imagenes_urls else None,
                "fecha": p.fecha_creacion.isoformat(),
            })

        # No cache para ver los cambios al instante
        response = make_response(jsonify(res), 200)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error en get_mis_productos: {e}")
        return jsonify({"error": "Error interno"}), 500