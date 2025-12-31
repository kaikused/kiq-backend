"""
Rutas para la gestión de montadores: Perfil, Stripe, Trabajos
y Reporte de incidencias.
"""
import json
import os
import stripe
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from sqlalchemy.exc import SQLAlchemyError

from app.models import Cliente, Trabajo, Montador, GemTransaction
from app.extensions import db
from app.storage import upload_image_to_gcs
from app.gems_service import recargar_gemas

montador_bp = Blueprint('montador', __name__)

# Configuración de Packs (Constante global)
PACKS_CONFIG = {
    'pack_small': {'amount': 500, 'gems': 50, 'name': 'Puñado de Gemas'},
    'pack_medium': {'amount': 1000, 'gems': 120, 'name': 'Bolsa de Gemas'},
    'pack_large': {'amount': 2000, 'gems': 300, 'name': 'Cofre de Gemas'}
}

# --- GESTIÓN DE TRABAJOS ---

@montador_bp.route('/montador/trabajos/disponibles', methods=['GET'])
@jwt_required()
def get_trabajos_disponibles():
    """Obtiene trabajos pendientes y sin asignar."""
    try:
        trabajos = Trabajo.query.filter_by(
            estado='pendiente', montador_id=None
        ).all()
        res = []
        for t in trabajos:
            cliente = Cliente.query.get(t.cliente_id)

            # Manejo de desglose (JSON en DB)
            desglose_data = t.desglose
            if isinstance(desglose_data, str):
                try:
                    desglose_data = json.loads(desglose_data)
                except json.JSONDecodeError:
                    desglose_data = None

            res.append({
                "trabajo_id": t.id,
                "descripcion": t.descripcion,
                "direccion": t.direccion,
                "precio_calculado": t.precio_calculado,
                "fecha_creacion": t.fecha_creacion.isoformat(),
                "imagenes_urls": t.imagenes_urls,
                "etiquetas": t.etiquetas,
                "cliente_nombre": cliente.nombre if cliente else "Usuario Kiq",
                "metodo_pago": t.metodo_pago,
                "desglose": desglose_data
            })
        return jsonify(res), 200
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error en get_trabajos_disponibles: {e}")
        return jsonify({"error": "Error al obtener trabajos"}), 500


@montador_bp.route('/montador/mis-trabajos', methods=['GET'])
@jwt_required()
def get_mis_trabajos_montador():
    """Obtiene los trabajos asignados al montador."""
    montador_id = get_jwt_identity()
    try:
        trabajos = Trabajo.query.filter_by(montador_id=montador_id).order_by(
            Trabajo.fecha_creacion.desc()
        ).all()
        res = []
        for t in trabajos:
            c = Cliente.query.get(t.cliente_id)
            # Manejo de desglose (JSON en DB)
            desglose_data = t.desglose
            if isinstance(desglose_data, str):
                try:
                    desglose_data = json.loads(desglose_data)
                except json.JSONDecodeError:
                    desglose_data = None

            # Info del cliente (CON FOTO para el chat)
            cliente_info = None
            if c:
                cliente_info = {
                    "nombre": c.nombre,
                    "foto_url": c.foto_url
                }

            res.append({
                "trabajo_id": t.id,
                "descripcion": t.descripcion,
                "direccion": t.direccion,
                "precio_calculado": t.precio_calculado,
                "estado": t.estado,
                "cliente_nombre": c.nombre if c else "Cliente",
                "cliente_info": cliente_info,
                "imagenes_urls": t.imagenes_urls,
                "desglose": desglose_data,
                "metodo_pago": t.metodo_pago
            })
        return jsonify(res), 200
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error en get_mis_trabajos_montador: {e}")
        return jsonify({"error": str(e)}), 500


@montador_bp.route('/montador/trabajo/<int:trabajo_id>/aceptar', methods=['POST'])
@jwt_required()
def aceptar_trabajo(trabajo_id):
    """
    El montador acepta un trabajo disponible.
    Si es pago en efectivo, se cobra la comisión en Gemas aquí.
    """
    montador_id = int(get_jwt_identity())

    try:
        montador = Montador.query.get(montador_id)
        trabajo = Trabajo.query.get(trabajo_id)

        if not trabajo or trabajo.estado != 'pendiente' or trabajo.montador_id is not None:
            return jsonify({"error": "Trabajo no disponible"}), 400

        # Lógica de cobro de comisión (Gemas)
        if trabajo.metodo_pago == 'efectivo_gemas':
            # Calcular coste (10% del precio * 10 ratio = Precio en gemas)
            coste_gemas = int(trabajo.precio_calculado * 0.10 * 10)

            # Excepción: Primer trabajo gratis
            trabajos_previos = Trabajo.query.filter_by(montador_id=montador_id).count()
            if trabajos_previos == 0:
                coste_gemas = 0

            # Verificar saldo
            if montador.wallet.saldo < coste_gemas:
                return jsonify({"error": "Saldo insuficiente de Gemas"}), 402

            # Cobrar
            if coste_gemas > 0:
                # Corrección E1123: Eliminado argumento 'tipo_transaccion' no soportado
                recargar_gemas(
                    wallet_id=montador.wallet.id,
                    cantidad_recarga=-coste_gemas, # Negativo para restar
                    descripcion=f'Comisión por trabajo #{trabajo.id}'
                )

        trabajo.montador_id = montador.id
        trabajo.estado = 'aceptado'
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "¡Trabajo aceptado! Contacta con el cliente."
        }), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error SQL al aceptar trabajo: {e}")
        return jsonify({"error": "Error de base de datos"}), 500
    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@montador_bp.route(
    '/montador/trabajo/<int:trabajo_id>/finalizar-con-evidencia', methods=['POST']
)
@jwt_required()
def finalizar_con_evidencia(trabajo_id):
    """Sube evidencia y finaliza el trabajo."""
    claims = get_jwt()
    if claims.get('tipo') != 'montador':
        return jsonify({"error": "Acceso no autorizado"}), 403
    montador_id = int(get_jwt_identity())

    if 'imagen' not in request.files:
        return jsonify({"error": "Es obligatorio subir una foto."}), 400
    file = request.files['imagen']
    if file.filename == '':
        return jsonify({"error": "Archivo vacío."}), 400

    try:
        trabajo = Trabajo.query.filter_by(
            id=trabajo_id, montador_id=montador_id
        ).first()
        if not trabajo:
            return jsonify({"error": "Trabajo no encontrado"}), 404
        if trabajo.estado != 'aceptado':
            return jsonify({"error": "Estado incorrecto"}), 400

        url_publica = upload_image_to_gcs(file, folder="evidencias")
        if not url_publica:
            return jsonify({"error": "Error al subir a GCS."}), 500

        trabajo.foto_finalizacion = url_publica
        trabajo.estado = 'revision_cliente'
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Evidencia subida.",
            "estado": "revision_cliente",
            "foto": url_publica
        }), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error en finalizar_con_evidencia: {e}")
        return jsonify({"error": str(e)}), 500


@montador_bp.route('/montador/trabajo/<int:trabajo_id>/reportar-fallido', methods=['POST'])
@jwt_required()
def reportar_trabajo_fallido(trabajo_id):
    """
    Permite al montador cancelar un trabajo si el cliente no responde.
    REEMBOLSA AUTOMÁTICAMENTE LAS GEMAS.
    """
    montador_id = int(get_jwt_identity())

    try:
        trabajo = Trabajo.query.filter_by(id=trabajo_id, montador_id=montador_id).first()

        if not trabajo:
            return jsonify({"error": "Trabajo no encontrado"}), 404

        if trabajo.estado != 'aceptado':
            return jsonify({"error": "Solo se pueden cancelar trabajos activos"}), 400

        # 1. Calcular cuánto pagó para devolverlo (si pagó)
        gemas_a_devolver = 0

        # Solo devolvemos si el método era gemas
        if trabajo.metodo_pago == 'efectivo_gemas':
            # Buscamos en el historial si hubo un pago para este trabajo
            tx_pago = GemTransaction.query.filter_by(
                wallet_id=trabajo.montador.wallet.id,
                trabajo_id=trabajo.id,
                tipo='PAGO_SERVICIO'
            ).first()

            # Si hubo transacción y fue negativa (gasto), devolvemos esa cantidad en positivo
            if tx_pago and tx_pago.cantidad < 0:
                gemas_a_devolver = abs(tx_pago.cantidad)

        # 2. Reembolsar
        if gemas_a_devolver > 0:
            # Corrección E1123: Eliminado argumento 'tipo_transaccion' no soportado
            recargar_gemas(
                wallet_id=trabajo.montador.wallet.id,
                cantidad_recarga=gemas_a_devolver,
                descripcion=f'Reembolso por trabajo fallido #{trabajo.id}'
            )

        # 3. Actualizar estado del trabajo
        trabajo.estado = 'cancelado_incidencia'
        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Trabajo cancelado. Se te han devuelto {gemas_a_devolver} gemas."
        }), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error en reportar_trabajo_fallido: {e}")
        return jsonify({"error": str(e)}), 500


# --- STRIPE Y PAGOS ---

@montador_bp.route('/montador/stripe-onboarding', methods=['POST'])
@jwt_required()
def montador_stripe_onboarding():
    """Genera el enlace de onboarding para Stripe."""
    montador_id = get_jwt_identity()
    montador = Montador.query.get(montador_id)
    try:
        account_link = stripe.AccountLink.create(
            account=montador.stripe_account_id,
            refresh_url="http://localhost:3000/panel-montador",
            return_url="http://localhost:3000/panel-montador?status=success",
            type="account_onboarding",
        )
        return jsonify({"url": account_link.url})
    except stripe.error.StripeError as e:
        return jsonify({"error": f"Error de Stripe: {e.user_message}"}), 500
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error general en montador_stripe_onboarding: {e}")
        return jsonify({"error": str(e)}), 500


@montador_bp.route('/pagos/crear-sesion-gemas', methods=['POST'])
@jwt_required()
def crear_sesion_gemas():
    """Crea una sesión de pago en Stripe para comprar packs de gemas."""
    user_id = get_jwt_identity()
    claims = get_jwt()

    data = request.json
    pack_id = data.get('packId')

    # Corrección C0103: Usamos la constante global PACKS_CONFIG definida arriba
    pack = PACKS_CONFIG.get(pack_id)
    if not pack:
        return jsonify({'error': 'Pack no válido'}), 400

    try:
        base_url = os.getenv('FRONTEND_URL', 'http://localhost:3000')
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {
                        'name': pack['name'],
                        'description': f"Recarga de {pack['gems']} Gemas en Kiq",
                    },
                    'unit_amount': pack['amount'],
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{base_url}/panel-montador?compra_gemas=exito',
            cancel_url=f'{base_url}/panel-montador?compra_gemas=cancelado',
            metadata={
                'montador_id': user_id,
                'tipo_usuario': claims.get('tipo'),
                'cantidad_gemas': pack['gems'],
                'transaction_type': 'RECARGA'
            }
        )
        return jsonify({'url': session.url}), 200

    except stripe.error.StripeError as e:
        return jsonify({"error": f"Error de Stripe: {e.user_message}"}), 500
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error general en crear_sesion_gemas: {e}")
        return jsonify({'error': str(e)}), 500
    