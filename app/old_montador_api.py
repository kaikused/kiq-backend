"""
API Blueprint para todas las rutas relacionadas con Montadores.
Contiene la lógica de seguridad, onboarding, y actualización de estado (sin cobro directo).
"""
from flask import Blueprint, request, jsonify
import stripe
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from sqlalchemy.exc import SQLAlchemyError

from .models import Montador, Trabajo
from .extensions import db
# 1. Importar el servicio de Gemas y las constantes
from . import gems_service

montador_bp = Blueprint('montador_api', __name__, url_prefix='/api/montador')

# --- CONFIGURACIÓN DE LA ECONOMÍA (Comisión de Kiq: 10%) ---
# La comisión se aplica solo a trabajos pagados en efectivo (efectivo_gemas)
COMISION_KIQ_PORCENTAJE = 0.10


# --- REGISTRO Y LOGIN ---

@montador_bp.route('/registro', methods=['POST'])
def registro_montador():
    """Registra un nuevo montador en la base de datos."""
    data = request.json
    nombre = data.get('nombre')
    email = data.get('email')
    password = data.get('password')
    zona_servicio = data.get('zona_servicio')

    if not all([nombre, email, password]):
        return jsonify({"error": "Nombre, email y contraseña son obligatorios"}), 400

    if Montador.query.filter_by(email=email).first():
        return jsonify({"error": "El email ya está registrado"}), 400

    try:
        nuevo_montador = Montador(
            nombre=nombre,
            email=email,
            zona_servicio=zona_servicio
        )
        nuevo_montador.set_password(password)
        db.session.add(nuevo_montador)
               
        # 2. Asignar la wallet y el bono (commit interno en gems_service)
        wallet = gems_service.obtener_o_crear_wallet(nuevo_montador.id, 'montador')
        if wallet:
             # Este commit se ejecuta aquí y es independiente          
            gems_service.asignar_bono_bienvenida(nuevo_montador.id, 'montador')
        
        db.session.commit()

        identity = str(nuevo_montador.id)
        additional_claims = {"tipo": "montador"}
        access_token = create_access_token(
            identity=identity, 
            additional_claims=additional_claims
        )

        return jsonify({
            "success": True,
            "message": "Montador registrado con éxito",
            "access_token": access_token
        }), 201

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error de base de datos en /api/montador/registro: {e}")
        return jsonify({"error": "Error interno al registrar montador"}), 500


@montador_bp.route('/login', methods=['POST'])
def login_montador():
    """Inicia sesión para un montador existente."""
    data = request.json
    email = data.get('email')
    password = data.get('password')

    if not all([email, password]):
        return jsonify({"error": "Email y contraseña son obligatorios"}), 400

    montador = Montador.query.filter_by(email=email).first()

    if not montador or not montador.check_password(password):
        return jsonify({"error": "Credenciales incorrectas"}), 401

    identity = str(montador.id)
    additional_claims = {"tipo": "montador"}
    access_token = create_access_token(
        identity=identity, 
        additional_claims=additional_claims
    )

    return jsonify({
        "success": True,
        "message": "Login correcto",
        "access_token": access_token
    })

# --- RUTA DE TRABAJOS DISPONIBLES ---

@montador_bp.route('/trabajos/disponibles', methods=['GET'])
@jwt_required()
def get_trabajos_disponibles():
    """Devuelve trabajos 'pendiente'."""
    claims = get_jwt()
    if claims.get("tipo") != "montador":
        return jsonify({"error": "Acceso no autorizado"}), 403

    montador_id = int(get_jwt_identity())
    montador = Montador.query.get(montador_id)
    # Se usa 'revision_cliente' en lugar de 'finalizado' para reflejar models.py
    is_verified = bool(montador and montador.stripe_account_id)

    try:
        trabajos_pendientes = Trabajo.query.filter_by(estado='pendiente') \
                                             .order_by(Trabajo.fecha_creacion.desc()) \
                                             .all()
        
        resultado = []
        for trabajo in trabajos_pendientes:
            if not is_verified:
                # Ofuscar dirección si el montador no ha completado el Onboarding de Stripe
                direccion_segura = trabajo.direccion.split(', ')[-1]
            else:
                direccion_segura = trabajo.direccion

            resultado.append({
                "trabajo_id": trabajo.id,
                "descripcion": trabajo.descripcion,
                "direccion": direccion_segura,
                "precio_calculado": trabajo.precio_calculado,
                "fecha_creacion": trabajo.fecha_creacion.isoformat(),
                "cliente_nombre": trabajo.cliente.nombre
            })
            
        return jsonify(resultado), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error de base de datos en /api/montador/trabajos/disponibles: {e}")
        return jsonify({"error": "Error interno al obtener trabajos"}), 500


# --- RUTA DE TRABAJOS ASIGNADOS ---

@montador_bp.route('/mis-trabajos', methods=['GET'])
@jwt_required()
def get_mis_trabajos_asignados():
    """Devuelve la lista de trabajos asignados, en revisión o completados."""
    claims = get_jwt()
    if claims.get("tipo") != "montador":
        return jsonify({"error": "Acceso no autorizado"}), 403
    
    montador_id = int(get_jwt_identity())

    try:
        # Buscamos aceptados, en_progreso, revision_cliente, aprobado_cliente_stripe, completado y cancelados
        trabajos_asignados = Trabajo.query.filter(
            (Trabajo.montador_id == montador_id)
        ).filter(
            Trabajo.estado.in_([
                'aceptado', 'en_progreso', 'revision_cliente', 
                'aprobado_cliente_stripe', 'completado', 'cancelado', 'cancelado_incidencia'
            ])
        ).order_by(Trabajo.fecha_creacion.desc()).all()
        
        resultado = []
        for trabajo in trabajos_asignados:
            resultado.append({
                "trabajo_id": trabajo.id,
                "descripcion": trabajo.descripcion,
                "direccion": trabajo.direccion,
                "precio_calculado": trabajo.precio_calculado,
                "estado": trabajo.estado,
                "fecha_creacion": trabajo.fecha_creacion.isoformat(),
                "cliente_nombre": trabajo.cliente.nombre,
            })
            
        return jsonify(resultado), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error de base de datos en /api/montador/mis-trabajos: {e}")
        return jsonify({"error": "Error interno al obtener trabajos asignados"}), 500


# --- RUTA CRÍTICA: ACEPTAR UN TRABAJO (CORRECCIÓN ATÓMICA Y CERO COMISIÓN) ---

@montador_bp.route('/trabajo/<int:trabajo_id>/aceptar', methods=['POST'])
@jwt_required()
def aceptar_trabajo(trabajo_id):
    """
    Permite a un montador logueado aceptar un trabajo pendiente.
    Implementa el débito atómico de Gemas para trabajos en efectivo.
    """
    claims = get_jwt()
    if claims.get("tipo") != "montador":
        return jsonify({"error": "Acceso no autorizado"}), 403
    
    montador_id = int(get_jwt_identity())
    montador = Montador.query.get(montador_id)

    if not montador:
        return jsonify({"error": "Montador no encontrado"}), 404

    try:
        trabajo = Trabajo.query.filter_by(id=trabajo_id, estado='pendiente').first()

        if not trabajo:
            return jsonify({
                "error": "Este trabajo ya no está disponible o ha sido aceptado por otro montador"
            }), 404
        
        # 1. Lógica CRÍTICA: Cobro de Gemas (Solo si el pago es en efectivo)
        if trabajo.metodo_pago == 'efectivo_gemas':
            
            # --- RESTAURAR LÓGICA DE CERO COMISIÓN ---
            # Contamos cuántos trabajos ha aceptado y finalizado este montador
            # Contar solo trabajos finalizados o completados es más seguro.
            trabajos_finalizados_count = Trabajo.query.filter(
                (Trabajo.montador_id == montador_id) &
                (Trabajo.estado.in_(['completado', 'cancelado_incidencia']))
            ).count()

            es_primer_trabajo = (trabajos_finalizados_count == 0)
            
            # Comisión = 10% del precio calculado (convertido a Gemas: 1€ = 10 Gemas)
            coste_gemas_comision = int(trabajo.precio_calculado * COMISION_KIQ_PORCENTAJE * 10)
            
            # Si es el primer trabajo exitoso, el coste es 0.
            coste_a_cobrar = 0 if es_primer_trabajo else coste_gemas_comision
            
            wallet = montador.wallet
            if not wallet:
                return jsonify({"error": "Wallet no inicializada. Contacte soporte"}), 500

            # Intentamos registrar el débito en la sesión (NO hace commit)
            if coste_a_cobrar > 0:
                transaccion_exitosa = gems_service.pagar_comision_servicio(
                    wallet.id, 
                    coste_a_cobrar, 
                    trabajo_id
                )
            
                if not transaccion_exitosa:
                    # FALLO CRÍTICO 402: Montador sin saldo para pagar la comisión
                    db.session.rollback()
                    return jsonify({
                        "error": "Saldo insuficiente de Gemas.",
                        "code": "402_PAYMENT_REQUIRED",
                        "required": coste_a_cobrar,
                        "available": wallet.saldo
                    }), 402
            # --- FIN TAREA 1 ---
        
        # 2. Asignación del Trabajo (Se añade a la misma sesión)
        trabajo.estado = 'aceptado'
        trabajo.montador_id = montador_id
        
        # 3. Commit ATÓMICO: Si el débito fue añadido y la asignación fue añadida,
        # ambas operaciones se guardan juntas. Si el commit falla, ambas se revierten.
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "¡Trabajo aceptado con éxito!",
            "trabajo_id": trabajo.id,
            "estado": "aceptado"
        }), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error de base de datos en /api/montador/trabajo/aceptar: {e}")
        return jsonify({"error": "Error interno al aceptar el trabajo"}), 500


# --- RUTA DE STRIPE ONBOARDING (MANEJO DE EXCEPCIONES MEJORADO) ---

@montador_bp.route('/stripe-onboarding', methods=['POST'])
@jwt_required()
def stripe_onboarding():
    """Crea cuenta Connect y devuelve link de onboarding."""
    claims = get_jwt()
    if claims.get("tipo") != "montador":
        return jsonify({"error": "Acceso no autorizado"}), 403

    montador_id = int(get_jwt_identity())
    montador = Montador.query.get(montador_id)

    if not montador:
        return jsonify({"error": "Montador no encontrado"}), 404
        
    try:
        if not montador.stripe_account_id:
            account = stripe.Account.create(
                type="standard",
                email=montador.email,
                metadata={'montador_id': montador.id, 'nombre': montador.nombre}
            )
            montador.stripe_account_id = account.id
            db.session.commit()
        
        refresh_url = 'http://localhost:3000/panel-montador'
        return_url = 'http://localhost:3000/panel-montador'

        # Línea corregida (anteriormente superaba 100 caracteres)
        account_link = stripe.AccountLink.create(
            account=montador.stripe_account_id,
            refresh_url=refresh_url,
            return_url=return_url,
            type="account_onboarding",
            api_version="2020-08-27"
        )
        
        return jsonify({'url': account_link.url}), 200
        
    except stripe.StripeError as err:
        db.session.rollback()
        msg = getattr(err, 'user_message', str(err))
        print(f"Error de Stripe en /api/montador/stripe-onboarding: {err}")
        return jsonify({"error": f"Error de Stripe: {msg}"}), 500
    except SQLAlchemyError as e:
        db.session.rollback()
        # Aseguramos el uso de 'e'
        print(f"Error de base de datos al registrar la cuenta de Stripe: {e}")
        return jsonify({"error": "Error interno al registrar la cuenta de Stripe"}), 500


# --- RUTA MODIFICADA: SOLO CAMBIO DE ESTADO (CORREGIDA LA INCLUSIÓN DE ESTADOS) ---

@montador_bp.route('/trabajo/<int:trabajo_id>/marcar-finalizado', methods=['POST'])
@jwt_required()
def marcar_trabajo_finalizado(trabajo_id):
    """
    El montador indica que ha terminado. NO mueve dinero.
    El estado pasa a 'revision_cliente' para que el cliente confirme.
    """
    claims = get_jwt()
    if claims.get("tipo") != "montador":
        return jsonify({"error": "Acceso no autorizado"}), 403
    
    montador_id = int(get_jwt_identity())

    try:
        # 1. Buscar el trabajo (debe estar en estado 'aceptado' o 'en_progreso')
        trabajo = Trabajo.query.filter_by(
            id=trabajo_id,
            montador_id=montador_id,
        ).filter(
            Trabajo.estado.in_(['aceptado', 'en_progreso']) # Permite pasar de aceptado o en_progreso
        ).first()

        if not trabajo:
            return jsonify({
                "error": "Trabajo no encontrado o no está en estado de ejecución (aceptado/en_progreso)"
            }), 404

        # 2. Solo cambiamos el estado (según la convención de models.py)
        trabajo.estado = 'revision_cliente' 
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Trabajo marcado como finalizado. Esperando confirmación del cliente.",
            "estado": "revision_cliente"
        }), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error de base de datos al finalizar el trabajo: {e}")
        return jsonify({"error": "Error interno al actualizar el estado"}), 500