"""
API Blueprint para las rutas de Clientes, Login Universal y públicas.
MODELO DE NEGOCIO: El Montador paga la comisión (Gemas) por aceptar trabajos en efectivo.
"""
import os
import json
from flask import Blueprint, request, jsonify, redirect, abort
import stripe
from flask_jwt_extended import (
    create_access_token, jwt_required, get_jwt_identity, get_jwt
)
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

# Imports locales
from .models import Cliente, Trabajo, Link, Montador, GemTransaction, VerificationCode, Product
from .extensions import db
from .storage import upload_image_to_gcs
from .gems_service import (
    asignar_bono_bienvenida, recargar_gemas, obtener_o_crear_wallet
)
# Imports para Emails
from .email_service import enviar_resumen_presupuesto, enviar_codigo_verificacion

# Cargar variables de entorno
load_dotenv()
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
ADMIN_SECRET_KEY = os.getenv('ADMIN_SECRET_KEY') # Nueva variable de entorno

api_bp = Blueprint('api', __name__, url_prefix='/api')

# ECONOMÍA
RATIO_GEMAS_EURO = 10  # 1€ = 10 Gemas
PORCENTAJE_COMISION = 0.10  # 10% Comisión Kiq


# --- RUTAS DE AUTENTICACIÓN (SEGURIDAD) ---

@api_bp.route('/auth/send-code', methods=['POST'])
def send_verification_code():
    """Genera y envía un código OTP al email."""
    email = request.json.get('email')
    if not email:
        return jsonify({"error": "Email requerido"}), 400

    # Verificar si ya existe cuenta
    if Cliente.query.filter_by(email=email).first():
        return jsonify({
            "status": "registrado",
            "message": "Este email ya tiene cuenta de Cliente."
        })
    
    if Montador.query.filter_by(email=email).first():
        return jsonify({
            "status": "registrado",
            "message": "Este email ya tiene cuenta de Montador."
        })

    try:
        # Limpiar códigos viejos de este email
        old_codes = VerificationCode.query.filter_by(email=email).all()
        for c in old_codes:
            db.session.delete(c)

        # Crear nuevo código
        code = VerificationCode.generate_code()
        new_verification = VerificationCode(email=email, code=code)
        db.session.add(new_verification)
        db.session.commit()

        # Enviar email con verificación de éxito
        if enviar_codigo_verificacion(email, code):
            return jsonify({"status": "enviado", "message": "Código enviado"})
        
        print("⚠️ Fallo al enviar email. Revirtiendo creación de código.")
        db.session.rollback() # Rollback si el email falla
        return jsonify({
            "error": "No se pudo enviar el email. Verifica tu dominio o intenta más tarde."
        }), 500

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error de BD en send_verification_code: {e}")
        return jsonify({"error": "Error interno de base de datos."}), 500
    # Deshabilita W0718: Captura necesaria para fallos de red/email
    except Exception as e: # pylint: disable=W0718 
        print(f"Error general en send_verification_code: {e}")
        return jsonify({"error": "Error interno del servidor."}), 500


@api_bp.route('/publicar-y-registrar', methods=['POST'])
def publicar_y_registrar():
    """Registra un nuevo Cliente y su primer Trabajo (REQUIERE CÓDIGO)."""
    data = request.json
    nombre = data.get('nombre')
    email = data.get('email')
    password = data.get('password')
    descripcion = data.get('descripcion')
    direccion = data.get('direccion')
    precio_calculado = data.get('precio_calculado')

    # --- 🛡️ VALIDACIÓN DE PRECIO MÍNIMO (SUELO 30€) ---
    try:
        if float(precio_calculado) < 30:
            return jsonify({"error": "El presupuesto mínimo para solicitar un servicio es de 30€."}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "Formato de precio inválido."}), 400
    # --------------------------------------------------

    # --- CÓDIGO DE VERIFICACIÓN ---
    codigo_verificacion = data.get('codigo')
    verification = VerificationCode.query.filter_by(
        email=email, code=codigo_verificacion
    ).first()
    if not verification or not verification.is_valid():
        return jsonify({"error": "Código de verificación inválido o expirado"}), 400
    db.session.delete(verification)
    # ------------------------------

    imagenes = data.get('imagenes', [])
    etiquetas = data.get('etiquetas', [])
    desglose_data = data.get('desglose')

    if Cliente.query.filter_by(email=email).first():
        return jsonify({"error": "El email ya está registrado"}), 400

    required_fields = [
        nombre, email, password, descripcion, direccion, precio_calculado
    ]
    if not all(required_fields):
        return jsonify({"error": "Faltan datos obligatorios"}), 400

    try:
        nuevo_cliente = Cliente(nombre=nombre, email=email)
        nuevo_cliente.set_password(password)

        nuevo_trabajo = Trabajo(
            descripcion=descripcion,
            direccion=direccion,
            precio_calculado=precio_calculado,
            estado='cotizacion',
            imagenes_urls=imagenes,
            etiquetas=etiquetas,
            desglose=desglose_data
        )
        nuevo_trabajo.cliente = nuevo_cliente

        db.session.add(nuevo_cliente)
        db.session.add(nuevo_trabajo)
        db.session.commit() # Commit de registro y trabajo

        # Asignar la wallet y el bono
        obtener_o_crear_wallet(nuevo_cliente.id, 'cliente')
        asignar_bono_bienvenida(nuevo_cliente.id, 'cliente')

        # --- ENVÍO DE EMAIL (Bloque no crítico) ---
        try:
            muebles_lista = []
            if desglose_data and isinstance(desglose_data, dict):
                muebles_lista = desglose_data.get('muebles_cotizados', [])

            enviar_resumen_presupuesto(
                email_cliente=nuevo_cliente.email,
                nombre_cliente=nuevo_cliente.nombre,
                precio=nuevo_trabajo.precio_calculado,
                items_resumen=muebles_lista
            )
        # Deshabilita W0718: Bloque no crítico, se mantiene la captura general para fallos de email
        except Exception as e: # pylint: disable=W0718 
            print(f"⚠️ Error enviando email (no crítico): {e}")

        identity = str(nuevo_cliente.id)
        additional_claims = {"tipo": "cliente"}
        access_token = create_access_token(
            identity=identity,
            additional_claims=additional_claims
        )

        return jsonify({
            "success": True,
            "message": "¡Cuenta verificada y creada! (+500 Gemas)",
            "access_token": access_token
        }), 201

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error de BD en /publicar-y-registrar: {e}")
        return jsonify({"error": "Error interno de base de datos."}), 500
    # Deshabilita W0718: Captura de último recurso para errores inesperados
    except Exception as e: # pylint: disable=W0718 
        db.session.rollback()
        print(f"Error general en /publicar-y-registrar: {e}")
        return jsonify({"error": "Error interno al crear la cuenta"}), 500


@api_bp.route('/check-email', methods=['POST'])
def check_email():
    """Verifica si un email ya existe en la base de datos."""
    data = request.json
    email = data.get('email')
    if not email:
        return jsonify({"error": "Email no proporcionado"}), 400
    if Cliente.query.filter_by(email=email).first() or Montador.query.filter_by(email=email).first():
        return jsonify({"status": "existente"})
    return jsonify({"status": "nuevo"})


@api_bp.route('/login-y-publicar', methods=['POST'])
def login_y_publicar():
    """Loguea a un usuario existente y publica un trabajo."""
    data = request.json
    email = data.get('email')
    password = data.get('password')
    descripcion = data.get('descripcion')
    direccion = data.get('direccion')
    precio_calculado = data.get('precio_calculado')
    
    # --- 🛡️ VALIDACIÓN DE PRECIO MÍNIMO (SUELO 30€) ---
    try:
        if float(precio_calculado) < 30:
            return jsonify({"error": "El presupuesto mínimo para solicitar un servicio es de 30€."}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "Formato de precio inválido."}), 400
    # --------------------------------------------------

    imagenes = data.get('imagenes', [])
    etiquetas = data.get('etiquetas', [])
    desglose_data = data.get('desglose')

    cliente = Cliente.query.filter_by(email=email).first()
    if not cliente or not cliente.check_password(password):
        return jsonify({"error": "Credenciales incorrectas"}), 401

    identity = str(cliente.id)
    additional_claims = {"tipo": "cliente"}
    access_token = create_access_token(
        identity=identity, additional_claims=additional_claims
    )

    try:
        nuevo_trabajo = Trabajo(
            descripcion=descripcion,
            direccion=direccion,
            precio_calculado=precio_calculado,
            cliente_id=cliente.id,
            estado='cotizacion',
            imagenes_urls=imagenes,
            etiquetas=etiquetas,
            desglose=desglose_data
        )
        db.session.add(nuevo_trabajo)
        db.session.commit()

        # --- ENVÍO DE EMAIL (Bloque no crítico) ---
        try:
            muebles_lista = []
            if desglose_data and isinstance(desglose_data, dict):
                muebles_lista = desglose_data.get('muebles_cotizados', [])

            enviar_resumen_presupuesto(
                email_cliente=cliente.email,
                nombre_cliente=cliente.nombre,
                precio=nuevo_trabajo.precio_calculado,
                items_resumen=muebles_lista
            )
        # Deshabilita W0718: Bloque no crítico, se mantiene la captura general para fallos de email
        except Exception as e: # pylint: disable=W0718 
            print(f"⚠️ Error enviando email (no crítico): {e}")

        return jsonify({
            "success": True,
            "message": "¡Cotización guardada con éxito!",
            "access_token": access_token
        }), 201

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error de BD en /login-y-publicar: {e}")
        return jsonify({"error": "Error interno de base de datos."}), 500
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718 
        db.session.rollback()
        print(f"Error general en /login-y-publicar: {e}")
        return jsonify({"error": "Error interno al publicar"}), 500


@api_bp.route('/cliente/publicar-trabajo', methods=['POST'])
@jwt_required()
def publicar_trabajo_logueado():
    """Publica un trabajo para un usuario ya autenticado."""
    claims = get_jwt()
    if claims.get('tipo') != 'cliente':
        return jsonify({"error": "Acceso no autorizado"}), 403

    cliente_id = get_jwt_identity()
    data = request.json
    descripcion = data.get('descripcion')
    direccion = data.get('direccion')
    precio_calculado = data.get('precio_calculado')
    
    # --- 🛡️ VALIDACIÓN DE PRECIO MÍNIMO (SUELO 30€) ---
    try:
        if float(precio_calculado) < 30:
            return jsonify({"error": "El presupuesto mínimo para solicitar un servicio es de 30€."}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "Formato de precio inválido."}), 400
    # --------------------------------------------------

    imagenes = data.get('imagenes', [])
    etiquetas = data.get('etiquetas', [])
    desglose_data = data.get('desglose')

    if not all([descripcion, direccion, precio_calculado]):
        return jsonify({"error": "Faltan datos del trabajo"}), 400

    try:
        nuevo_trabajo = Trabajo(
            descripcion=descripcion,
            direccion=direccion,
            precio_calculado=precio_calculado,
            cliente_id=int(cliente_id),
            estado='cotizacion',
            imagenes_urls=imagenes,
            etiquetas=etiquetas,
            desglose=desglose_data
        )
        db.session.add(nuevo_trabajo)
        db.session.commit()

        cliente = Cliente.query.get(int(cliente_id))
        if cliente:
            # --- ENVÍO DE EMAIL (Bloque no crítico) ---
            try:
                muebles_lista = []
                if desglose_data and isinstance(desglose_data, dict):
                    muebles_lista = desglose_data.get('muebles_cotizados', [])

                enviar_resumen_presupuesto(
                    email_cliente=cliente.email,
                    nombre_cliente=cliente.nombre,
                    precio=nuevo_trabajo.precio_calculado,
                    items_resumen=muebles_lista
                )
            # Deshabilita W0718: Bloque no crítico, se mantiene la captura general para fallos de email
            except Exception as e: # pylint: disable=W0718 
                print(f"⚠️ Error enviando email (no crítico): {e}")

        return jsonify({
            "success": True,
            "message": "¡Nueva cotización guardada!",
            "trabajo_id": nuevo_trabajo.id,
            "estado": "cotizacion"
        }), 201

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error de BD en /api/cliente/publicar-trabajo: {e}")
        return jsonify({"error": "Error interno de base de datos."}), 500
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718 
        db.session.rollback()
        print(f"Error general en /api/cliente/publicar-trabajo: {e}")
        return jsonify({"error": "Error interno al publicar"}), 500


@api_bp.route('/login-universal', methods=['POST'])
def login_universal():
    """Login unificado para clientes y montadores."""
    data = request.json
    email = data.get('email')
    password = data.get('password')

    if not all([email, password]):
        return jsonify({"error": "Email y contraseña son obligatorios"}), 400

    cliente = Cliente.query.filter_by(email=email).first()
    if cliente and cliente.check_password(password):
        identity = str(cliente.id)
        additional_claims = {"tipo": "cliente"}
        access_token = create_access_token(
            identity=identity, additional_claims=additional_claims
        )
        return jsonify({
            "success": True,
            "tipo_usuario": "cliente",
            "access_token": access_token
        })

    montador = Montador.query.filter_by(email=email).first()
    if montador and montador.check_password(password):
        identity = str(montador.id)
        additional_claims = {"tipo": "montador"}
        access_token = create_access_token(
            identity=identity, additional_claims=additional_claims
        )
        return jsonify({
            "success": True,
            "tipo_usuario": "montador",
            "access_token": access_token
        })

    return jsonify({"error": "Credenciales incorrectas"}), 401


@api_bp.route('/perfil', methods=['GET', 'PUT'])
@jwt_required()
def perfil():
    """Obtiene o actualiza el perfil del usuario."""
    user_id = get_jwt_identity()
    claims = get_jwt()
    user_tipo = claims.get("tipo")

    if request.method == 'GET':
        if user_tipo == 'cliente':
            u = Cliente.query.get(user_id)
            if not u:
                return jsonify({"error": "Usuario no encontrado"}), 404
            saldo = u.wallet.saldo if u.wallet else 0
            return jsonify({
                "id": u.id, "nombre": u.nombre, "email": u.email,
                "tipo": "cliente", "gemas": saldo, "foto_url": u.foto_url
            }), 200

        if user_tipo == 'montador':
            u = Montador.query.get(user_id)
            if not u:
                return jsonify({"error": "Usuario no encontrado"}), 404
            
            # --- TAREA 1: LÓGICA DE BONO DE BIENVENIDA ---
            # Verificamos si ya existe una transacción de BONO_REGISTRO en la Wallet
            bono_existe = GemTransaction.query.filter_by(
                wallet_id=u.wallet.id, tipo='BONO_REGISTRO'
            ).first() is not None
            # ---------------------------------------------

            stripe_completado = False
            if u.stripe_account_id:
                try:
                    account = stripe.Account.retrieve(u.stripe_account_id)
                    stripe_completado = account.details_submitted
                # Deshabilita W0718: Captura necesaria para Stripe API
                except Exception as e: # pylint: disable=W0718 
                    print(f"Error verificando Stripe: {e}")
            saldo = u.wallet.saldo if u.wallet else 0
            return jsonify({
                "id": u.id, "nombre": u.nombre, "email": u.email,
                "telefono": u.telefono, "zona_servicio": u.zona_servicio,
                "tipo": "montador", "stripe_account_id": u.stripe_account_id,
                "stripe_boarding_completado": stripe_completado, 
                "gemas": saldo, "foto_url": u.foto_url,
                "bono_entregado": bono_existe,
                # 👇 AQUÍ ES DONDE DEVOLVEMOS EL ESTADO DEL BONO VISTO
                "bono_visto": u.bono_visto 
            }), 200
        return jsonify({"error": "Usuario no encontrado"}), 404

    if request.method == 'PUT':
        data = request.json
        u = (
            Cliente.query.get(user_id) if user_tipo == 'cliente'
            else Montador.query.get(user_id)
        )
        if not u:
            return jsonify({"error": "Usuario no encontrado"}), 404
        try:
            if 'nombre' in data:
                u.nombre = data['nombre']
            if user_tipo == 'montador':
                if 'telefono' in data:
                    u.telefono = data['telefono']
                if 'zona_servicio' in data:
                    u.zona_servicio = data['zona_servicio']
            db.session.commit()
            return jsonify({"success": True, "message": "Perfil actualizado"}), 200
        except SQLAlchemyError: 
            db.session.rollback()
            return jsonify({"error": "Error al actualizar"}), 500
        # Deshabilita W0718: Captura de último recurso
        except Exception: # pylint: disable=W0718 
            db.session.rollback()
            return jsonify({"error": "Error al actualizar"}), 500
    return jsonify({"error": "Método no permitido"}), 405

# --- NUEVA RUTA: SUBIDA DE FOTO DE PERFIL ---
@api_bp.route('/perfil/foto', methods=['POST'])
@jwt_required()
def subir_foto_perfil():
    """Sube una foto de perfil a GCS y actualiza la BD."""
    user_id = get_jwt_identity()
    claims = get_jwt()
    tipo = claims.get("tipo")

    if 'imagen' not in request.files:
        return jsonify({"error": "No se envió ninguna imagen"}), 400
    
    file = request.files['imagen']
    if file.filename == '':
        return jsonify({"error": "Archivo vacío"}), 400

    try:
        # 1. Subir a la nube (Usamos tu función existente)
        url_publica = upload_image_to_gcs(file, folder="perfiles")
        
        if not url_publica:
            return jsonify({"error": "Error al guardar la imagen en la nube"}), 500

        # 2. Actualizar base de datos
        usuario = Cliente.query.get(user_id) if tipo == 'cliente' else Montador.query.get(user_id)

        if not usuario:
            return jsonify({"error": "Usuario no encontrado"}), 404

        usuario.foto_url = url_publica 
        
        db.session.commit()

        return jsonify({
            "success": True, 
            "message": "Foto actualizada correctamente", 
            "foto_url": url_publica
        }), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error de BD en subir_foto_perfil: {e}")
        return jsonify({"error": "Error interno de base de datos."}), 500
    # Deshabilita W0718: Captura de último recurso (fallos de I/O de archivos)
    except Exception as e: # pylint: disable=W0718
        db.session.rollback()
        print(f"Error general en subir_foto_perfil: {e}")
        return jsonify({"error": str(e)}), 500


# 👇 NUEVO ENDPOINT: MARCAR BONO COMO VISTO 👇
@api_bp.route('/perfil/dismiss-bono', methods=['POST'])
@jwt_required()
def dismiss_bono():
    """Marca el bono de bienvenida como VISTO para siempre."""
    user_id = get_jwt_identity()
    claims = get_jwt()
    
    if claims.get('tipo') != 'montador':
        return jsonify({"error": "Solo montadores"}), 403

    try:
        montador = Montador.query.get(user_id)
        if montador:
            montador.bono_visto = True
            db.session.commit()
            return jsonify({"success": True}), 200
        return jsonify({"error": "Usuario no encontrado"}), 404
    except Exception as e:
        db.session.rollback()
        print(f"Error en dismiss_bono: {e}")
        return jsonify({"error": str(e)}), 500
# ---------------------------------------------------


@api_bp.route('/cliente/mis-trabajos', methods=['GET'])
@jwt_required()
def get_mis_trabajos():
    """Obtiene los trabajos del cliente."""
    claims = get_jwt()
    if claims.get('tipo') != 'cliente':
        return jsonify({"error": "Acceso no autorizado"}), 403
    try:
        user_id = get_jwt_identity()
        trabajos = Trabajo.query.filter_by(cliente_id=user_id).order_by(
            Trabajo.fecha_creacion.desc()
        ).all()
        res = []
        for t in trabajos:
            # Manejo de desglose (JSON en DB)
            desglose_data = t.desglose
            if isinstance(desglose_data, str):
                try:
                    desglose_data = json.loads(desglose_data)
                except json.JSONDecodeError:
                    desglose_data = None
                    
            # Obtenemos la información esencial del montador (si está asignado)
            montador_info = None
            if t.montador_id:
                m = Montador.query.get(t.montador_id)
                if m:
                    montador_info = {
                        "nombre": m.nombre, 
                        "telefono": m.telefono,
                        "foto_url": m.foto_url # <--- ¡FOTO INCLUIDA!
                    }

            res.append({
                "trabajo_id": t.id,
                "descripcion": t.descripcion,
                "direccion": t.direccion,
                "precio_calculado": t.precio_calculado,
                "estado": t.estado,
                "fecha_creacion": t.fecha_creacion.isoformat(),
                "montador_info": montador_info, 
                "imagenes_urls": t.imagenes_urls,
                "etiquetas": t.etiquetas,
                "foto_finalizacion": t.foto_finalizacion,
                "desglose": desglose_data,
                "metodo_pago": t.metodo_pago,
                "payment_intent_id": t.payment_intent_id 
            })
        return jsonify(res), 200
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        print(f"Error en get_mis_trabajos: {e}")
        return jsonify({"error": "Error al obtener trabajos"}), 500


@api_bp.route('/cliente/trabajo/<int:trabajo_id>/cancelar', methods=['POST'])
@jwt_required()
def cancelar_trabajo(trabajo_id):
    """Cancela un trabajo pendiente o en cotización."""
    cliente_id = int(get_jwt_identity())
    try:
        t = Trabajo.query.filter_by(id=trabajo_id, cliente_id=cliente_id).first()
        if not t or t.estado not in ['pendiente', 'cotizacion']:
            return jsonify({"error": "No se puede cancelar"}), 400
        
        # LÓGICA DE REEMBOLSO: Si había PI asociado, deberíamos cancelarlo/liberar la retención
        if t.payment_intent_id and t.metodo_pago == 'stripe':
             # Aquí se podría añadir la lógica para cancelar el PaymentIntent en Stripe
             # stripe.PaymentIntent.cancel(t.payment_intent_id)
            print(f"⚠️ Nota: Se debe implementar la cancelación de PaymentIntent {t.payment_intent_id}") # Indentación corregida (W0311)

        t.estado = 'cancelado'
        db.session.commit()
        return jsonify({
            "success": True, "message": "Trabajo cancelado", "estado": "cancelado"
        }), 200
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        db.session.rollback()
        print(f"Error en cancelar_trabajo: {e}")
        return jsonify({"error": str(e)}), 500


# --- API DE PAGOS (CLIENTE) ---

@api_bp.route('/cliente/crear-payment-intent', methods=['POST'])
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
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        print(f"Error general en crear_payment_intent: {e}")
        return jsonify({"error": "Error interno: Error creando PI"}), 500


@api_bp.route('/cliente/trabajo/<int:trabajo_id>/activar', methods=['POST'])
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

        # Validación del estado de retención (requires_capture)
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        if intent.status != 'requires_capture':
            return jsonify({
                "error": f"El pago no está retenido (Estado: {intent.status})"
            }), 400

        trabajo.payment_intent_id = payment_intent_id
        trabajo.estado = 'pendiente'
        trabajo.metodo_pago = 'stripe'
        
        # Añadir metadata al PaymentIntent para que el Webhook lo use después
        stripe.PaymentIntent.modify(
            payment_intent_id,
            metadata={'trabajo_id': str(trabajo_id), 'cliente_id': str(cliente_id)}
        )
        
        db.session.commit()

        return jsonify({
            "success": True, "message": "Trabajo activo", "estado": "pendiente"
        }), 200
    except stripe.error.StripeError as e:
        db.session.rollback()
        return jsonify({"error": f"Error de Stripe: {e.user_message}"}), 500
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        db.session.rollback()
        print(f"Error general en activar_trabajo: {e}")
        return jsonify({"error": str(e)}), 500


# --- NUEVA LÓGICA: PAGO EN EFECTIVO (USO DE GEMAS POR MONTADOR) 💎 ---
@api_bp.route('/cliente/trabajo/<int:trabajo_id>/pagar-con-gemas', methods=['POST'])
@jwt_required()
def activar_con_efectivo(trabajo_id):
    """
    El cliente elige 'Pago en Efectivo'.
    Solo actualiza el método de pago a 'efectivo_gemas' y el estado a 'pendiente'.
    La comisión se cobrará al montador al aceptar.
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
            "message": "Pago en efectivo seleccionado. Visible para montadores.",
            "estado": "pendiente"
        }), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error de BD en activar_con_efectivo: {e}")
        return jsonify({"error": "Error interno de base de datos."}), 500
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        db.session.rollback()
        print(f"Error general en activar_con_efectivo: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route('/cliente/trabajo/<int:trabajo_id>/confirmar-pago', methods=['POST'])
@jwt_required()
def confirmar_pago_cliente(trabajo_id):
    """
    CONFIRMA el trabajo. Ya NO ejecuta Stripe (Split Payment) de forma síncrona.
    Solo marca el trabajo como FINALIZADO/COMPLETADO en la DB.
    """
    cliente_id = int(get_jwt_identity())

    try:
        trabajo = Trabajo.query.filter_by(
            id=trabajo_id, cliente_id=cliente_id
        ).first()
        if not trabajo:
            return jsonify({"error": "Trabajo no encontrado"}), 404
        
        if trabajo.estado != 'revision_cliente':
            return jsonify({"error": "El trabajo debe estar en revisión para ser confirmado."}), 400

        # --- LÓGICA DIFERENCIADA SEGÚN MÉTODO DE PAGO ---

        # A) PAGO EN EFECTIVO (GEMAS)
        if trabajo.metodo_pago == 'efectivo_gemas':
            # Solo actualizamos estado. El montador ya pagó la comisión.
            trabajo.estado = 'completado'
            db.session.commit()
            return jsonify({
                "success": True,
                "message": "Servicio finalizado (Pago en efectivo).",
                "estado": "completado"
            }), 200

        # B) PAGO CON STRIPE (Flujo Asíncrono)
        # El cliente solo confirma la aprobación.
        trabajo.estado = 'aprobado_cliente_stripe' # Nuevo estado para indicar aprobación
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Aprobación recibida. Procesando pago al montador...",
            "estado": "aprobado_cliente_stripe"
        }), 200
        
    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error de BD en confirmar_pago_cliente: {e}")
        return jsonify({"error": "Error interno de base de datos."}), 500
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        db.session.rollback()
        print(f"Error general en confirmar_pago_cliente: {e}")
        return jsonify({"error": str(e)}), 500


# --- RUTAS DE MONTADOR (CON CÓDIGO) ---

@api_bp.route('/montador/registro', methods=['POST'])
def registro_montador():
    """Registra un nuevo montador (REQUIERE CÓDIGO)."""
    data = request.json
    email = data.get('email')
    
    # --- CÓDIGO DE VERIFICACIÓN ---
    codigo_verificacion = data.get('codigo')
    verification = VerificationCode.query.filter_by(
        email=email, code=codigo_verificacion
    ).first()
    if not verification or not verification.is_valid():
        return jsonify({"error": "Código de verificación inválido o expirado"}), 400
    db.session.delete(verification)
    # -------------------------------------

    if Montador.query.filter_by(email=data.get('email')).first():
        return jsonify({"error": "Email registrado"}), 400
    
    try:
        # Crear cuenta Stripe Connect
        account = stripe.Account.create(
            type="standard", 
            email=data.get('email'),
            capabilities={
                "card_payments": {"requested": True},
                "transfers": {"requested": True}
            },
            business_type='individual',
            country='ES'
        )
        
        nuevo = Montador(
            nombre=data.get('nombre'), email=data.get('email'),
            telefono=data.get('telefono'), zona_servicio=data.get('zona_servicio'),
            stripe_account_id=account.id
        )
        nuevo.set_password(data.get('password'))
        db.session.add(nuevo)
        db.session.commit()

        # Asignar la wallet y el bono
        obtener_o_crear_wallet(nuevo.id, 'montador')
        asignar_bono_bienvenida(nuevo.id, 'montador')

        token = create_access_token(
            identity=str(nuevo.id), additional_claims={"tipo": "montador"}
        )
        return jsonify({"success": True, "access_token": token}), 201
    except stripe.error.StripeError as e:
        db.session.rollback()
        print(f"Error de Stripe en registro_montador: {e}")
        return jsonify({"error": f"Error de Stripe: {e.user_message}"}), 500
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        db.session.rollback()
        print(f"Error general en registro_montador: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route('/montador/stripe-onboarding', methods=['POST'])
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
        print(f"Error de Stripe en montador_stripe_onboarding: {e}")
        return jsonify({"error": f"Error de Stripe: {e.user_message}"}), 500
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        print(f"Error general en montador_stripe_onboarding: {e}")
        return jsonify({"error": str(e)}), 500

# --- NUEVA RUTA: COMPRA DE GEMAS (STRIPE CHECKOUT) ---
@api_bp.route('/pagos/crear-sesion-gemas', methods=['POST'])
@jwt_required()
def crear_sesion_gemas():
    """Crea una sesión de pago en Stripe para comprar packs de gemas."""
    user_id = get_jwt_identity()
    claims = get_jwt()
    
    data = request.json
    pack_id = data.get('packId')
    
    # C0103 Corregido: Se renombra PACKS a PACKS_CONFIG para convención
    PACKS_CONFIG = {
        'pack_small': {'amount': 500, 'gems': 50, 'name': 'Puñado de Gemas'},  # 5.00€
        'pack_medium': {'amount': 1000, 'gems': 120, 'name': 'Bolsa de Gemas'}, # 10.00€
        'pack_large': {'amount': 2000, 'gems': 300, 'name': 'Cofre de Gemas'}  # 20.00€
    }
    
    pack = PACKS_CONFIG.get(pack_id)
    if not pack:
        return jsonify({'error': 'Pack no válido'}), 400

    try:
        # URL base para redirección (en producción usa tu dominio real)
        base_url = os.getenv('FRONTEND_URL', 'http://localhost:3000') # Usar ENV
        
        # Crear sesión de Checkout de Stripe
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
            # URLs de retorno
            success_url=f'{base_url}/panel-montador?compra_gemas=exito',
            cancel_url=f'{base_url}/panel-montador?compra_gemas=cancelado',
            # Metadatos para que el Webhook sepa qué hacer luego
            metadata={
                'montador_id': user_id, # Asumimos que solo los montadores recargan
                'tipo_usuario': claims.get('tipo'),
                'cantidad_gemas': pack['gems'],
                'transaction_type': 'RECARGA'
            }
        )
        return jsonify({'url': session.url}), 200

    except stripe.error.StripeError as e:
        return jsonify({"error": f"Error de Stripe: {e.user_message}"}), 500
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        print(f"Error general en crear_sesion_gemas: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/montador/trabajos/disponibles', methods=['GET'])
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
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        print(f"Error en get_trabajos_disponibles: {e}")
        return jsonify({"error": "Error al obtener trabajos"}), 500


@api_bp.route('/montador/mis-trabajos', methods=['GET'])
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
            
            # 👇 Lógica actualizada: Enviar también objeto con foto
            cliente_info = None
            if c:
                cliente_info = {
                    "nombre": c.nombre,
                    "foto_url": c.foto_url # <--- ¡FOTO INCLUIDA!
                }

            res.append({
                "trabajo_id": t.id,
                "descripcion": t.descripcion,
                "direccion": t.direccion,
                "precio_calculado": t.precio_calculado,
                "estado": t.estado,
                "cliente_nombre": c.nombre if c else "Cliente",
                "cliente_info": cliente_info, # Usar esto en el frontend
                "imagenes_urls": t.imagenes_urls,
                "desglose": desglose_data,
                "metodo_pago": t.metodo_pago
            })
        return jsonify(res), 200
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        print(f"Error en get_mis_trabajos_montador: {e}")
        return jsonify({"error": str(e)}), 500


# --- LÓGICA DE COBRO AL MONTADOR (OBSOLETA, SE MUEVE A montador_api.py) ---
# Se recomienda usar la versión de montador_api.py


@api_bp.route(
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
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        db.session.rollback()
        print(f"Error en finalizar_con_evidencia: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route('/montador/trabajo/<int:trabajo_id>/reportar-fallido', methods=['POST'])
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
            # Usamos el alias de recarga, pero con tipo 'REEMBOLSO'
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

    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        db.session.rollback()
        print(f"Error en reportar_trabajo_fallido: {e}")
        return jsonify({"error": str(e)}), 500

# --- RUTA DE SUPER ADMIN (PANEL DE CONTROL - SEGURIDAD CORREGIDA) ---
@api_bp.route('/admin/todos-los-trabajos', methods=['GET'])
def admin_get_trabajos():
    """
    Obtiene TODOS los trabajos del sistema.
    Protegido por un Header secreto (x-admin-secret) desde ENV.
    """
    admin_secret = request.headers.get('x-admin-secret')
    
    # CORRECCIÓN DE SEGURIDAD: Uso de variable de entorno
    if admin_secret != ADMIN_SECRET_KEY:
        return jsonify({"error": "Acceso denegado"}), 403

    try:
        trabajos = Trabajo.query.order_by(Trabajo.fecha_creacion.desc()).all()
        res = []
        for t in trabajos:
            c = Cliente.query.get(t.cliente_id)
            m = Montador.query.get(t.montador_id) if t.montador_id else None
            
            res.append({
                "id": t.id,
                "fecha": t.fecha_creacion.strftime("%Y-%m-%d %H:%M"),
                "estado": t.estado,
                "cliente": c.nombre if c else "Desconocido",
                "email_cliente": c.email if c else "-",
                "montador": m.nombre if m else "Sin asignar",
                "precio": t.precio_calculado,
                "metodo_pago": t.metodo_pago,
                "descripcion": t.descripcion,
                "direccion": t.direccion
            })
        return jsonify(res), 200
    # Deshabilita W0718: Captura de último recurso
    except Exception as e: # pylint: disable=W0718
        print(f"Error en admin_get_trabajos: {e}")
        return jsonify({"error": str(e)}), 500

# ==========================================
# 🛒 MÓDULO KIQ OUTLET (LOGÍSTICA INVERSA)
# ==========================================

@api_bp.route('/outlet/publicar', methods=['POST'])
@jwt_required()
def publicar_producto_outlet():
    """
    Permite a un Montador (o Cliente) publicar un mueble recuperado.
    """
    user_id = get_jwt_identity()
    claims = get_jwt()
    tipo_usuario = claims.get('tipo')

    # 1. Validar datos
    titulo = request.form.get('titulo')
    precio = request.form.get('precio')
    
    if not titulo or not precio:
        return jsonify({"error": "Título y precio son obligatorios"}), 400
    
    # 2. Validar Imagen (Obligatoria para vender)
    if 'imagen' not in request.files:
        return jsonify({"error": "Falta la foto del producto"}), 400
    
    file = request.files['imagen']
    if file.filename == '':
        return jsonify({"error": "Archivo vacío"}), 400

    try:
        # 3. Subir foto a la nube
        url_publica = upload_image_to_gcs(file, folder="outlet")
        if not url_publica:
            return jsonify({"error": "Error al subir imagen"}), 500

        # 4. Crear Producto en BD
        nuevo_prod = Product(
            titulo=titulo,
            descripcion=request.form.get('descripcion', ''),
            precio=float(precio),
            estado='disponible',
            imagenes_urls=[url_publica], # Guardamos como array por si en el futuro hay más
            ubicacion=request.form.get('ubicacion', 'Málaga') # Default por ahora
        )

        # Asignar dueño
        if tipo_usuario == 'montador':
            nuevo_prod.montador_id = int(user_id)
        else:
            nuevo_prod.cliente_id = int(user_id)

        db.session.add(nuevo_prod)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "¡Producto publicado en el Outlet!",
            "product_id": nuevo_prod.id,
            "foto_url": url_publica
        }), 201

    except Exception as e:
        db.session.rollback()
        print(f"Error en publicar_producto_outlet: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route('/outlet/feed', methods=['GET'])
def get_outlet_feed():
    """
    Devuelve el muro de productos disponibles.
    Público (no requiere login estricto, pero idealmente sí).
    """
    try:
        # Traer solo los disponibles, los más recientes primero
        productos = Product.query.filter_by(estado='disponible').order_by(
            Product.fecha_creacion.desc()
        ).limit(50).all()

        res = []
        for p in productos:
            # Averiguar quién vende
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
            
        return jsonify(res), 200

    except Exception as e:
        print(f"Error en get_outlet_feed: {e}")
        return jsonify({"error": "Error cargando el feed"}), 500

# --- Rutas Públicas ---
@api_bp.route('/r/<short_code>')
def redirect_to_url(short_code):
    """Redirige a la URL original de un short code."""
    link = Link.query.filter_by(short_code=short_code).first()
    return redirect(link.original_url) if link else abort(404)


@api_bp.route('/get-reviews')
def get_google_reviews():
    """Obtiene reseñas."""
    return jsonify([])