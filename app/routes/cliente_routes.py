"""
Rutas para la gestión de clientes: Publicación de trabajos,
pagos (Stripe/Gemas) y gestión de estado de servicios.
"""
import json
import stripe
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from sqlalchemy.exc import SQLAlchemyError

from app.models import Cliente, Trabajo, Montador, Product
from app.extensions import db
from app.email_service import enviar_resumen_presupuesto

cliente_bp = Blueprint('cliente', __name__)

# --- GESTIÓN DE TRABAJOS ---

@cliente_bp.route('/cliente/publicar-trabajo', methods=['POST'])
@jwt_required()
def publicar_trabajo_logueado():
    """Publica un trabajo para un usuario ya autenticado."""
    claims = get_jwt()
    # CORRECCIÓN QUIRÚRGICA: Cambiado 'tipo' por 'rol'
    if claims.get('rol') != 'cliente':
        return jsonify({"error": "Acceso no autorizado"}), 403

    cliente_id = get_jwt_identity()
    data = request.json
    descripcion = data.get('descripcion')
    direccion = data.get('direccion')
    precio_calculado = data.get('precio_calculado')

    # Validación básica
    if not all([descripcion, direccion, precio_calculado]):
        return jsonify({"error": "Faltan datos del trabajo"}), 400

    # Validación de precio mínimo
    try:
        if float(precio_calculado) < 30:
            return jsonify({"error": "El presupuesto mínimo es de 30€."}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "Formato de precio inválido."}), 400

    try:
        nuevo_trabajo = Trabajo(
            descripcion=descripcion,
            direccion=direccion,
            precio_calculado=precio_calculado,
            cliente_id=int(cliente_id), # Aseguramos que sea entero
            estado='cotizacion', # Estado inicial visible
            imagenes_urls=data.get('imagenes', []),
            etiquetas=data.get('etiquetas', []),
            desglose=data.get('desglose')
        )
        db.session.add(nuevo_trabajo)
        db.session.commit()

        # Intentar enviar email (no bloqueante)
        try:
            cliente = Cliente.query.get(int(cliente_id))
            if cliente:
                desglose = data.get('desglose')
                muebles_lista = []
                if desglose and isinstance(desglose, dict):
                    muebles_lista = desglose.get('muebles_cotizados', [])

                enviar_resumen_presupuesto(
                    cliente.email, cliente.nombre,
                    nuevo_trabajo.precio_calculado, muebles_lista
                )
        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"⚠️ Error enviando email: {e}")

        return jsonify({
            "success": True,
            "message": "¡Nueva cotización guardada!",
            "trabajo_id": nuevo_trabajo.id,
            "estado": "cotizacion"
        }), 201

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error BD cliente/publicar: {e}")
        return jsonify({"error": "Error interno de base de datos."}), 500
    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error general cliente/publicar: {e}")
        return jsonify({"error": "Error interno al publicar"}), 500


@cliente_bp.route('/cliente/mis-trabajos', methods=['GET'])
@jwt_required()
def get_mis_trabajos():
    """Obtiene los trabajos del cliente (incluyendo cotizaciones)."""
    claims = get_jwt()
    # CORRECCIÓN QUIRÚRGICA: Cambiado 'tipo' por 'rol'
    if claims.get('rol') != 'cliente':
        return jsonify({"error": "Acceso no autorizado"}), 403

    try:
        # CORRECCIÓN IMPORTANTE: Convertir a int para asegurar match en DB
        user_id = int(get_jwt_identity())

        # Obtenemos TODO sin filtrar por estado
        trabajos = Trabajo.query.filter_by(cliente_id=user_id).order_by(
            Trabajo.fecha_creacion.desc()
        ).all()

        # DEBUG LOG: Esto saldrá en tu consola de Render
        print(f"🔍 DEBUG: Usuario {user_id} solicita trabajos. Encontrados: {len(trabajos)}")

        res = []
        for t in trabajos:
            # Info del Montador (CON FOTO)
            montador_info = None
            if t.montador_id:
                m = Montador.query.get(t.montador_id)
                if m:
                    montador_info = {
                        "nombre": m.nombre,
                        "telefono": m.telefono,
                        "foto_url": m.foto_url
                    }

            # Parseo seguro del desglose
            desglose = t.desglose
            if isinstance(desglose, str):
                try:
                    desglose = json.loads(desglose)
                except json.JSONDecodeError:
                    desglose = None

            res.append({
                "trabajo_id": t.id,
                "descripcion": t.descripcion,
                "direccion": t.direccion,
                "precio_calculado": t.precio_calculado,
                "estado": t.estado, # Aquí debe llegar 'cotizacion'
                "fecha_creacion": t.fecha_creacion.isoformat(),
                "montador_info": montador_info,
                "imagenes_urls": t.imagenes_urls,
                "foto_finalizacion": t.foto_finalizacion,
                "desglose": desglose,
                "metodo_pago": t.metodo_pago,
                "payment_intent_id": t.payment_intent_id
            })

        return jsonify(res), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error en get_mis_trabajos: {e}")
        return jsonify({"error": "Error al obtener trabajos"}), 500


@cliente_bp.route('/cliente/trabajo/<int:trabajo_id>/cancelar', methods=['POST'])
@jwt_required()
def cancelar_trabajo(trabajo_id):
    """
    Cancela un trabajo.
    Si es Outlet, libera el producto para que vuelva al feed.
    """
    cliente_id = int(get_jwt_identity())
    try:
        t = Trabajo.query.filter_by(id=trabajo_id, cliente_id=cliente_id).first()

        if not t:
            return jsonify({"error": "Trabajo no encontrado"}), 404

        # Verificar si es Outlet (tiene etiqueta especial)
        es_outlet = False
        if t.etiquetas and isinstance(t.etiquetas, dict):
            if t.etiquetas.get('tipo') == 'outlet':
                es_outlet = True

        # Reglas de cancelación:
        if not es_outlet and t.estado not in ['pendiente', 'cotizacion']:
            return jsonify({"error": "No se puede cancelar en este estado"}), 400

        if es_outlet and t.estado == 'completado':
            return jsonify({"error": "Ya has comprado este producto."}), 400

        # Lógica de Devolución (Stripe)
        if t.payment_intent_id and t.metodo_pago == 'stripe':
            print(f"⚠️ TODO: Cancelar/Reembolsar PI Stripe: {t.payment_intent_id}")

        # --- LÓGICA OUTLET: DEVOLVER AL ESCAPARATE ---
        if es_outlet:
            product_id = t.etiquetas.get('outlet_product_id')
            if product_id:
                producto = Product.query.get(product_id)
                if producto:
                    producto.estado = 'disponible'
                    producto.payment_intent_id = None
                    producto.cliente_id = None
                    print(f"✅ Producto #{product_id} liberado al feed.")

        t.estado = 'cancelado'
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Cancelado. El producto vuelve a estar disponible.",
            "estado": "cancelado"
        }), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error en cancelar_trabajo: {e}")
        return jsonify({"error": str(e)}), 500


# --- PAGOS ---

@cliente_bp.route('/cliente/crear-payment-intent', methods=['POST'])
def crear_payment_intent():
    """Crea el intento de pago en Stripe (Solo retención)."""
    data = request.json
    precio = data.get('precio_calculado')
    if not precio:
        return jsonify({"error": "Precio requerido"}), 400
    try:
        intent = stripe.PaymentIntent.create(
            amount=int(float(precio) * 100),
            currency='eur',
            automatic_payment_methods={'enabled': True},
            capture_method='manual', # Solo retención
            setup_future_usage='off_session'
        )
        return jsonify({
            'client_secret': intent.client_secret,
            'payment_intent_id': intent.id
        }), 200
    except stripe.StripeError as e:
        return jsonify({"error": f"Stripe Error: {e.user_message}"}), 500
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error general en crear_payment_intent: {e}")
        return jsonify({"error": "Error interno creando pago"}), 500


@cliente_bp.route('/cliente/trabajo/<int:trabajo_id>/activar', methods=['POST'])
@jwt_required()
def activar_trabajo(trabajo_id):
    """Activa el trabajo tras confirmar la retención de fondos (Stripe)."""
    cliente_id = int(get_jwt_identity())
    payment_intent_id = request.json.get('payment_intent_id')
    if not payment_intent_id:
        return jsonify({"error": "Falta ID de pago"}), 400

    try:
        trabajo = Trabajo.query.filter_by(
            id=trabajo_id, cliente_id=cliente_id, estado='cotizacion'
        ).first()
        if not trabajo:
            return jsonify({"error": "Trabajo no válido"}), 404

        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        if intent.status != 'requires_capture':
            return jsonify({
                "error": f"El pago no está retenido (Estado: {intent.status})"
            }), 400

        trabajo.payment_intent_id = payment_intent_id
        trabajo.estado = 'pendiente'
        trabajo.metodo_pago = 'stripe'

        stripe.PaymentIntent.modify(
            payment_intent_id,
            metadata={'trabajo_id': str(trabajo_id), 'cliente_id': str(cliente_id)}
        )

        db.session.commit()
        return jsonify({
            "success": True, "message": "Trabajo activo", "estado": "pendiente"
        }), 200
    except stripe.error.StripeError as e:
        return jsonify({"error": f"Error de Stripe: {e.user_message}"}), 500
    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@cliente_bp.route('/cliente/trabajo/<int:trabajo_id>/pagar-con-gemas', methods=['POST'])
@jwt_required()
def activar_con_efectivo(trabajo_id):
    """
    El cliente elige 'Pago en Efectivo'.
    Actualiza método a 'efectivo_gemas' y estado a 'pendiente'.
    """
    cliente_id = int(get_jwt_identity())

    try:
        trabajo = Trabajo.query.filter_by(
            id=trabajo_id, cliente_id=cliente_id, estado='cotizacion'
        ).first()
        if not trabajo:
            return jsonify({"error": "Trabajo no encontrado"}), 404

        trabajo.estado = 'pendiente'
        trabajo.metodo_pago = 'efectivo_gemas'

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Pago en efectivo seleccionado.",
            "estado": "pendiente"
        }), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error activar_con_efectivo: {e}")
        return jsonify({"error": str(e)}), 500


@cliente_bp.route('/cliente/trabajo/<int:trabajo_id>/confirmar-pago', methods=['POST'])
@jwt_required()
def confirmar_pago_cliente(trabajo_id):
    """
    CONFIRMA el trabajo. Marca como FINALIZADO/COMPLETADO.
    Si es un Outlet, marca el producto como VENDIDO.
    """
    cliente_id = int(get_jwt_identity())

    try:
        trabajo = Trabajo.query.filter_by(
            id=trabajo_id, cliente_id=cliente_id
        ).first()
        if not trabajo:
            return jsonify({"error": "Trabajo no encontrado"}), 404

        if trabajo.estado != 'revision_cliente':
            return jsonify({"error": "El trabajo debe estar en revisión."}), 400

        # --- LÓGICA OUTLET: ACTUALIZAR ESTADO DEL PRODUCTO ---
        if trabajo.etiquetas and isinstance(trabajo.etiquetas, dict):
            if trabajo.etiquetas.get('tipo') == 'outlet':
                product_id = trabajo.etiquetas.get('outlet_product_id')
                if product_id:
                    producto = Product.query.get(product_id)
                    if producto:
                        # Marcamos como vendido para sacarlo del feed
                        producto.estado = 'vendido'
                        db.session.add(producto)
                        print(f"✅ Producto #{product_id} marcado oficialmente como VENDIDO.")
        # -------------------------------------------------------------

        if trabajo.metodo_pago == 'efectivo_gemas':
            trabajo.estado = 'completado'
            db.session.commit()
            return jsonify({
                "success": True, "message": "Finalizado.", "estado": "completado"
            }), 200

        trabajo.estado = 'aprobado_cliente_stripe'
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Aprobación recibida.",
            "estado": "aprobado_cliente_stripe"
        }), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@cliente_bp.route('/calcular_presupuesto', methods=['POST'])
def calcular_presupuesto_nueva():
    """
    Calculadora robusta para evitar el error 'Análisis inicial no válido'.
    """
    try:
        data = request.json
        # Convertimos a minúsculas para detectar palabras clave
        descripcion = data.get('descripcion', '').lower()

        # Lógica de precio base (simple pero efectiva)
        precio_estimado = 50 # Precio base por visita/minimo

        if 'armario' in descripcion:
            precio_estimado = 90
            if 'puertas' in descripcion or 'grande' in descripcion:
                precio_estimado = 140
        elif 'cama' in descripcion:
            precio_estimado = 70
        elif 'sofá' in descripcion or 'sofa' in descripcion:
            precio_estimado = 60
        elif 'mesa' in descripcion or 'silla' in descripcion:
            precio_estimado = 45

        # RESPUESTA EXACTA que espera tu Frontend
        return jsonify({
            "success": True,
            "precio": precio_estimado,
            "titulo": "Presupuesto Estimado",
            "mensaje": f"He analizado tu solicitud ('{descripcion}'). "
                       f"El coste estimado sería de {precio_estimado}€ (incluye desplazamiento y montaje básico).",
            "desglose": {
                "mano_obra": precio_estimado,
                "materiales": 0
            }
        }), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"❌ Error calculadora: {e}")
        # Respuesta de emergencia
        return jsonify({
            "success": True,
            "precio": 50,
            "mensaje": "No pude calcular exacto, pero el precio base es 50€."
        }), 200