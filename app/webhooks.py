"""
Módulo de Webhooks para Stripe.
Maneja las notificaciones asíncronas de pagos y cambios de estado.
"""
import os
import stripe
from flask import Blueprint, request, jsonify
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError

# Importaciones locales necesarias
from .extensions import db
from .models import Montador, Trabajo
from . import gems_service

# Cargar variables de entorno
load_dotenv()

# Configurar Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
# Asegúrate de que esta variable de entorno esté configurada
ENDPOINT_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

webhooks_bp = Blueprint('webhooks', __name__)

# --- LÓGICA DEL MANEJADOR DE EVENTOS ---

def handle_checkout_completed(session):
    """Maneja el evento checkout.session.completed (Recarga de Gemas)."""
    
    # 1. Recuperar datos del montador y cantidad de gemas
    montador_id = session.metadata.get('montador_id')
    cantidad_gemas = int(session.metadata.get('cantidad_gemas'))

    if not montador_id or not cantidad_gemas:
        print("⚠️ Metadatos faltantes en checkout.session.completed.")
        return False
    
    montador = Montador.query.get(montador_id)
    if not montador or not montador.wallet:
        print(f"⚠️ Montador o Wallet no encontrada para ID {montador_id}.")
        return False

    try:
        # 2. Registrar el crédito de Gemas de forma atómica
        # Aquí usamos db.session.commit() porque es un flujo asíncrono e independiente.
        transaccion_exitosa = gems_service.recargar_gemas(
            montador.wallet.id,
            cantidad_gemas,
            f"Recarga de Gemas vía Stripe Checkout (Session: {session.id})"
        )
        # Si recargar_gemas fue exitoso, hace commit internamente en gems_service.py
        if transaccion_exitosa:
            db.session.commit()
            print(f"✅ Recarga exitosa: {cantidad_gemas} gemas añadidas a montador {montador_id}")
            return True
        
        # Si falla (p.ej. wallet no encontrada), el rollback se realiza dentro de gems_service.py
        return False

    except SQLAlchemyError as e:
        # Esto captura errores que podrían ocurrir después del add (como un deadlock)
        db.session.rollback()
        print(f"❌ Error de BD al procesar recarga de gemas: {e}")
        return False


def handle_payment_intent_succeeded(payment_intent):
    """
    Maneja el evento payment_intent.succeeded (Transferencia de fondos al montador).
    Este es el Split Payment para trabajos pagados con tarjeta.
    """
    
    trabajo_id = payment_intent.metadata.get('trabajo_id')
    monto_total_cents = payment_intent['amount']
    monto_comision_cents = int(payment_intent.metadata.get('commission_fee'))

    if not trabajo_id:
        print("⚠️ Metadatos 'trabajo_id' faltantes en payment_intent.succeeded.")
        return False

    trabajo = Trabajo.query.get(trabajo_id)
    if not trabajo or trabajo.estado != 'revision_cliente':
        # La transferencia solo debe ocurrir si el cliente ya aprobó el trabajo.
        # En Kiq, el cliente confirma el trabajo y eso genera el cobro final.
        print(f"⚠️ Trabajo {trabajo_id} no encontrado o estado no es 'revision_cliente'.")
        return False

    montador = trabajo.montador
    if not montador or not montador.stripe_account_id:
        print(f"⚠️ Montador o Stripe Account ID no encontrado para trabajo {trabajo_id}.")
        return False

    try:
        # 1. Crear la transferencia al Montador (Monto Total - Comisión)
        monto_a_transferir = monto_total_cents - monto_comision_cents
        
        transfer = stripe.Transfer.create(
            amount=monto_a_transferir,
            currency='eur',
            destination=montador.stripe_account_id,
            source_transaction=payment_intent['id'],
            metadata={'trabajo_id': trabajo_id}
        )
        print(f"✅ Transferencia creada ({transfer.id}) de {monto_a_transferir} centavos al montador {montador.id}.")

        # 2. Marcar el Trabajo como completado en la BD
        trabajo.estado = 'completado'
        db.session.add(trabajo)
        db.session.commit()
        
        return True

    except stripe.error.StripeError as e:
        print(f"❌ Error de Stripe al transferir fondos para el trabajo {trabajo_id}: {e}")
        db.session.rollback()
        # Aquí se necesita un mecanismo de reintento o alerta (fuera del scope actual)
        return False
    except SQLAlchemyError as e:
        print(f"❌ Error de BD al marcar trabajo {trabajo_id} como completado: {e}")
        db.session.rollback()
        return False


@webhooks_bp.route('/webhook', methods=['POST'])
def stripe_webhook():
    """
    Endpoint receptor de eventos de Stripe.
    Verifica la firma criptográfica y procesa el estado del pago.
    """
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    event = None

    try:
        # 1. Verificar que la petición viene REALMENTE de Stripe
        event = stripe.Webhook.construct_event(
            payload, sig_header, ENDPOINT_SECRET
        )
    except ValueError:
        # Payload inválido
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError:
        # Firma inválida
        return jsonify({'error': 'Invalid signature'}), 400

    # 2. Manejar los eventos importantes
    event_type = event['type']
    event_object = event['data']['object']

    if event_type == 'checkout.session.completed':
        # Flujo de Recarga de Gemas (montador compra gemas)
        # Solo procesamos si el pago fue exitoso
        if event_object.get('payment_status') == 'paid':
            print(f"🛒 Checkout Session completada: {event_object['id']}")
            handle_checkout_completed(event_object)
    
    elif event_type == 'payment_intent.succeeded':
        # Flujo de Split Payment (transferir fondos al montador por un servicio)
        print(f"✅ Pago exitoso y capturado: {event_object['id']}")
        handle_payment_intent_succeeded(event_object)
        
    elif event_type == 'payment_intent.payment_failed':
        # Solo registro por ahora
        print(f"❌ Pago fallido: {event_object['id']}")

    # Importante: Stripe espera un 200 OK para confirmar que el webhook fue recibido.
    return jsonify({'status': 'success', 'event': event_type}), 200