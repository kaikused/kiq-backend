"""
Servicio de gestión de Gemas (Kiq Gems).
Maneja la creación de wallets, transacciones, recompensas y pagos.
La lógica de commit es intencionalmente omitida, para ser manejada de forma
atómica por los Blueprints (Unidad de Trabajo).
"""
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from .extensions import db
# Se elimina 'Trabajo' de los imports para resolver W0611 (Unused import)
from .models import Wallet, GemTransaction

# Configuración de la economía
BONO_BIENVENIDA = 500  # Gemas gratis al registrarse


def obtener_o_crear_wallet(usuario_id, tipo_usuario):
    """
    Busca la wallet del usuario. Si no existe, la crea y la añade a la sesión.
    IMPORTANTE: Esta función mantiene el commit para la creación inicial de la Wallet.
    """
    filtro = (
        {'cliente_id': usuario_id}
        if tipo_usuario == 'cliente'
        else {'montador_id': usuario_id}
    )

    wallet = Wallet.query.filter_by(**filtro).first()

    if not wallet:
        try:
            wallet = Wallet(**filtro, saldo=0)
            db.session.add(wallet)
            # Solo hacemos commit aquí para la creación inicial de la Wallet.
            # Esto es seguro, ya que no afecta a otras transacciones.
            db.session.commit()
        except SQLAlchemyError as e:
            # En caso de error, hacemos rollback y registramos.
            db.session.rollback()
            print(f"❌ Error al crear la wallet para {tipo_usuario} {usuario_id}: {e}")
            return None

    return wallet


def asignar_bono_bienvenida(usuario_id, tipo_usuario):
    """
    Otorga las gemas iniciales al registrarse.
    Utiliza el manejo de errores de SQLAlchemy y el UniqueConstraint de models.py.
    """
    try:
        wallet = obtener_o_crear_wallet(usuario_id, tipo_usuario)
        if not wallet:
            return False

        # Intentamos registrar la transacción. El UniqueConstraint en models.py
        # impedirá un doble bono si ya existe uno.
        tx = GemTransaction(
            wallet_id=wallet.id,
            cantidad=BONO_BIENVENIDA,
            tipo='BONO_REGISTRO',
            descripcion='¡Bienvenido a Kiq! Aquí tienes tus gemas iniciales.'
        )

        wallet.saldo += BONO_BIENVENIDA
        db.session.add(tx)
        
        # Hacemos commit del bono. Si falla por IntegrityError (doble bono),
        # el saldo de la wallet se mantendrá intacto gracias al rollback.
        db.session.commit()
        return True

    except IntegrityError:
        # Esto captura el error si el UniqueConstraint falla (doble bono)
        db.session.rollback()
        print(f"⚠️ El bono de registro ya fue asignado a la wallet {wallet.id}")
        return False

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"❌ Error al asignar bono de bienvenida: {e}")
        return False


def actualizar_gemas(wallet_id, cantidad, tipo_transaccion, descripcion, trabajo_id=None):
    """
    Función ÚNICA para gestionar cualquier movimiento de Gemas (débito/crédito).
    Añade la acción a la sesión, pero NO hace commit.

    :param cantidad: Positivo para crédito, Negativo para débito.
    :return: True si la operación fue añadida a la sesión, False si el saldo es insuficiente.
    """
    wallet = Wallet.query.get(wallet_id)
    if not wallet:
        raise ValueError(f"Wallet con ID {wallet_id} no encontrada.")

    # 1. Validación de saldo para débitos
    if cantidad < 0 and wallet.saldo < abs(cantidad):
        # Esta es la validación CRÍTICA (Fallo 402)
        return False  # Saldo insuficiente

    # 2. Actualizar saldo y registrar transacción en la sesión
    wallet.saldo += cantidad

    tx = GemTransaction(
        wallet_id=wallet.id,
        cantidad=cantidad,
        tipo=tipo_transaccion,
        descripcion=descripcion,
        trabajo_id=trabajo_id
    )

    db.session.add(tx)
    db.session.add(wallet)  # Aseguramos que la wallet actualizada esté en la sesión
    
    # IMPORTANTE: NO HAY db.session.commit() aquí. El Blueprint lo hará.
    return True


# --- Funciones de utilidad que usan actualizar_gemas ---

def pagar_comision_servicio(wallet_id, coste_gemas, trabajo_id):
    """Alias para débitos (uso principal en aceptar_trabajo)."""
    descripcion = f'Comisión por servicio (Trabajo #{trabajo_id})'
    
    # Nota: coste_gemas debe ser positivo, pero lo convertimos a negativo (débito)
    return actualizar_gemas(
        wallet_id,
        cantidad=-coste_gemas,
        tipo_transaccion='PAGO_SERVICIO',
        descripcion=descripcion,
        trabajo_id=trabajo_id
    )

def recargar_gemas(wallet_id, cantidad_recarga, descripcion):
    """Alias para créditos (uso principal en webhooks de Stripe)."""
    return actualizar_gemas(
        wallet_id,
        cantidad=cantidad_recarga,
        tipo_transaccion='RECARGA',
        descripcion=descripcion
    )