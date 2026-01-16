"""
Módulo de Webhooks para Stripe.
Maneja las notificaciones asíncronas de pagos y cambios de estado.
"""
import os
import stripe
from flask import Blueprint, request, jsonify
from dotenv import load_dotenv

# Importaciones locales necesarias
from app.extensions import db
from app.models import Montador, Trabajo, Product
from app import gems_service
from app.gems_service import obtener_o_crear_wallet

# Cargar variables de entorno
load_dotenv()

# Configurar Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
ENDPOINT_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

webhooks_bp = Blueprint('webhooks', __name__)

# --- LÓGICA DEL MANEJADOR DE EVENTOS ---

def handle_checkout_completed(session):
    """Maneja el evento checkout.session.completed (Recarga de Gemas)."""

    # 1. Recuperar datos
    montador_id = session.get('metadata', {}).get('montador_id')
    cantidad_gemas_str = session.get('metadata', {}).get('cantidad_gemas')

    if not montador_id or not cantidad_gemas_str:
        print("⚠️ Metadatos faltantes en checkout.session.completed.")
        return False

    try:
        cantidad_gemas = int(cantidad_gemas_str)
        montador = Montador.query.get(montador_id)

        if not montador or not montador.wallet:
            # Intentar recuperar wallet si no existe (autocuración)
            if montador:
                obtener_o_crear_wallet(montador.id, 'montador')
                # Commit intermedio para asegurar que la wallet exista antes de recargar
                db.session.commit()
            else:
                print(f"⚠️ Montador no encontrado ID {montador_id}.")
                return False

        # 2. Registrar el crédito de Gemas
        gems_service.recargar_gemas(
            montador.wallet.id,
            cantidad_gemas,
            f"Recarga Stripe (Session: {session.get('id')})"
        )

        db.session.commit()
        print(f"✅ Recarga exitosa: {cantidad_gemas} gemas al montador {montador_id}")
        return True

    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"❌ Error procesando recarga de gemas: {e}")
        return False


def handle_payment_intent_succeeded(payment_intent):
    """
    Maneja el evento payment_intent.succeeded.
    Puede ser:
    A) Pago de un Servicio (Trabajo)
    B) Compra de un Producto (Outlet)
    """
    metadata = payment_intent.get('metadata', {})
    tipo_operacion = metadata.get('tipo') # 'orden_compra', 'compra_outlet', o implícito trabajo

    # --- CASO A: COMPRA OUTLET / PRODUCTO ---
    if tipo_operacion in ['orden_compra', 'compra_outlet']:
        product_id = metadata.get('product_id')
        if not product_id:
            return False

        try:
            prod = Product.query.get(product_id)
            if prod:
                prod.estado = 'vendido'
                prod.payment_intent_id = payment_intent.get('id')
                prod.metodo_pago = 'stripe'
                db.session.commit()
                print(f"✅ Producto #{product_id} marcado como VENDIDO tras pago Stripe.")
                return True
        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"❌ Error procesando venta producto {product_id}: {e}")
            db.session.rollback()
            return False

    # --- CASO B: PAGO DE SERVICIO (TRABAJO) ---
    trabajo_id = metadata.get('trabajo_id')

    if not trabajo_id:
        print("⚠️ Evento ignorado: No hay trabajo_id ni es compra de producto.")
        return False

    try:
        trabajo = Trabajo.query.get(trabajo_id)
        if not trabajo:
            print(f"⚠️ Trabajo {trabajo_id} no encontrado.")
            return False

        # Si el pago tuvo éxito, pasamos el trabajo al siguiente estado lógico
        # Si estaba en 'cotizacion', pasa a 'pendiente' (ya se retuvo/pagó)
        if trabajo.estado == 'cotizacion':
            trabajo.estado = 'pendiente'
            trabajo.metodo_pago = 'stripe'
            trabajo.payment_intent_id = payment_intent.get('id')
            db.session.commit()
            print(f"✅ Trabajo #{trabajo_id} activado tras pago exitoso.")
            return True

        # Si estaba en 'aprobado_cliente_stripe', significa que se capturó el pago final
        if trabajo.estado == 'aprobado_cliente_stripe':
            trabajo.estado = 'completado'
            db.session.commit()

            # TRANSFERENCIA AL MONTADOR (Split Payment)
            # Solo si hay un montador asignado y tiene Stripe Connect
            if trabajo.montador and trabajo.montador.stripe_account_id:
                try:
                    amount = payment_intent.get('amount') # Céntimos
                    # Kiq se queda el 10%, Montador el 90%
                    amount_transfer = int(amount * 0.90)

                    stripe.Transfer.create(
                        amount=amount_transfer,
                        currency='eur',
                        destination=trabajo.montador.stripe_account_id,
                        source_transaction=payment_intent.get('id'), # Transferir desde este pago
                        metadata={'trabajo_id': trabajo_id}
                    )
                    print(f"💸 Transferidos {amount_transfer/100}€ al montador.")
                except Exception as ex: # pylint: disable=broad-exception-caught
                    print(f"⚠️ Error transfiriendo al montador (El trabajo sí se cerró): {ex}")

            return True

    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"❌ Error procesando pago trabajo {trabajo_id}: {e}")
        db.session.rollback()
        return False

    return True


@webhooks_bp.route('/webhook', methods=['POST'])
def stripe_webhook():
    """
    Endpoint receptor de eventos de Stripe.
    """
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, ENDPOINT_SECRET
        )
    except ValueError:
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({'error': 'Invalid signature'}), 400

    event_type = event['type']
    event_object = event['data']['object']

    if event_type == 'checkout.session.completed':
        if event_object.get('payment_status') == 'paid':
            print(f"🛒 Checkout completado: {event_object.get('id')}")
            handle_checkout_completed(event_object)

    elif event_type == 'payment_intent.succeeded':
        print(f"💰 PaymentIntent exitoso: {event_object.get('id')}")
        handle_payment_intent_succeeded(event_object)

    elif event_type == 'payment_intent.payment_failed':
        print(f"❌ Pago fallido: {event_object.get('id')}")

    return jsonify({'status': 'success', 'event': event_type}), 200