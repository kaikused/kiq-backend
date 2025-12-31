"""
Rutas de autenticación, registro y GESTIÓN DE PERFIL.
Incluye envío de códigos, login universal, perfil de usuario, fotos y bonos.
"""
import stripe
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, create_access_token, get_jwt_identity, get_jwt
from sqlalchemy.exc import SQLAlchemyError

# Imports absolutos desde 'app'
from app.models import Cliente, Montador, VerificationCode, Trabajo, GemTransaction
from app.extensions import db
from app.gems_service import obtener_o_crear_wallet, asignar_bono_bienvenida
from app.email_service import enviar_codigo_verificacion, enviar_resumen_presupuesto
from app.storage import upload_image_to_gcs

# Definimos el Blueprint
auth_bp = Blueprint('auth', __name__)

# --- RUTAS DE AUTENTICACIÓN ---

@auth_bp.route('/auth/send-code', methods=['POST'])
def send_verification_code():
    """Genera y envía un código OTP al email."""
    email = request.json.get('email')
    if not email:
        return jsonify({"error": "Email requerido"}), 400

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
        old_codes = VerificationCode.query.filter_by(email=email).all()
        for c in old_codes:
            db.session.delete(c)

        code = VerificationCode.generate_code()
        new_verification = VerificationCode(email=email, code=code)
        db.session.add(new_verification)
        db.session.commit()

        if enviar_codigo_verificacion(email, code):
            return jsonify({"status": "enviado", "message": "Código enviado"})

        print("⚠️ Fallo al enviar email. Revirtiendo creación de código.")
        db.session.rollback()
        return jsonify({"error": "No se pudo enviar el email."}), 500

    except SQLAlchemyError as e:
        db.session.rollback()
        print(f"Error de BD: {e}")
        return jsonify({"error": "Error interno de base de datos."}), 500
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Error general: {e}")
        return jsonify({"error": "Error interno del servidor."}), 500


@auth_bp.route('/check-email', methods=['POST'])
def check_email():
    """Verifica si el email existe en alguna tabla."""
    data = request.json
    email = data.get('email')
    if not email:
        return jsonify({"error": "Email no proporcionado"}), 400

    if (Cliente.query.filter_by(email=email).first() or
            Montador.query.filter_by(email=email).first()):
        return jsonify({"status": "existente"})
    return jsonify({"status": "nuevo"})


@auth_bp.route('/login-universal', methods=['POST'])
def login_universal():
    """Login unificado para ambos tipos de usuario."""
    data = request.json
    email = data.get('email')
    password = data.get('password')

    if not all([email, password]):
        return jsonify({"error": "Datos incompletos"}), 400

    cliente = Cliente.query.filter_by(email=email).first()
    if cliente and cliente.check_password(password):
        token = create_access_token(
            identity=str(cliente.id),
            additional_claims={"tipo": "cliente"}
        )
        return jsonify({
            "success": True,
            "tipo_usuario": "cliente",
            "access_token": token
        })

    montador = Montador.query.filter_by(email=email).first()
    if montador and montador.check_password(password):
        token = create_access_token(
            identity=str(montador.id),
            additional_claims={"tipo": "montador"}
        )
        return jsonify({
            "success": True,
            "tipo_usuario": "montador",
            "access_token": token
        })

    return jsonify({"error": "Credenciales incorrectas"}), 401


@auth_bp.route('/montador/registro', methods=['POST'])
def registro_montador():
    """Registra un nuevo montador con Stripe."""
    data = request.json
    email = data.get('email')

    codigo_verificacion = data.get('codigo')
    verification = VerificationCode.query.filter_by(
        email=email, code=codigo_verificacion
    ).first()
    if not verification or not verification.is_valid():
        return jsonify({"error": "Código inválido o expirado"}), 400
    db.session.delete(verification)

    if Montador.query.filter_by(email=data.get('email')).first():
        return jsonify({"error": "Email registrado"}), 400

    try:
        account = stripe.Account.create(
            type="standard",
            email=data.get('email'),
            capabilities={"card_payments": {"requested": True}, "transfers": {"requested": True}},
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

        obtener_o_crear_wallet(nuevo.id, 'montador')
        asignar_bono_bienvenida(nuevo.id, 'montador')

        token = create_access_token(
            identity=str(nuevo.id),
            additional_claims={"tipo": "montador"}
        )
        return jsonify({"success": True, "access_token": token}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# 👇 NUEVO ENDPOINT: REGISTRO SIMPLE (PARA EL OUTLET) 👇
# Este es el único bloque nuevo. Permite registrarse solo con datos básicos.
@auth_bp.route('/registro-cliente-simple', methods=['POST'])
def registro_cliente_simple():
    """
    Registra un cliente SOLO con datos básicos (Nombre, Email, Pass, Código).
    Se usa cuando el usuario viene del Outlet y no quiere pedir un montaje aún.
    """
    data = request.json
    nombre = data.get('nombre')
    email = data.get('email')
    password = data.get('password')
    codigo = data.get('codigo')

    # 1. Validación
    if not all([nombre, email, password, codigo]):
        return jsonify({"error": "Faltan datos obligatorios"}), 400

    # 2. Verificar Código
    verification = VerificationCode.query.filter_by(email=email, code=codigo).first()
    if not verification or not verification.is_valid():
        return jsonify({"error": "Código inválido o expirado"}), 400
    db.session.delete(verification)

    # 3. Verificar Existencia
    if Cliente.query.filter_by(email=email).first():
        return jsonify({"error": "Email ya registrado"}), 400

    try:
        # 4. Crear Cliente (Sin trabajo asociado)
        nuevo_cliente = Cliente(nombre=nombre, email=email)
        nuevo_cliente.set_password(password)
        
        db.session.add(nuevo_cliente)
        db.session.commit()

        # 5. Inicializar Wallet y Bono
        obtener_o_crear_wallet(nuevo_cliente.id, 'cliente')
        asignar_bono_bienvenida(nuevo_cliente.id, 'cliente')

        # 6. Generar Token
        token = create_access_token(
            identity=str(nuevo_cliente.id),
            additional_claims={"tipo": "cliente"}
        )

        return jsonify({
            "success": True,
            "message": "¡Bienvenido a Kiq!",
            "access_token": token,
            "user": {
                "id": nuevo_cliente.id,
                "nombre": nuevo_cliente.nombre,
                "tipo": "cliente"
            }
        }), 201

    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error en registro simple: {e}")
        return jsonify({"error": "Error interno al registrar"}), 500
# ---------------------------------------------------------


# 👇 RUTA ORIGINAL INTACTA (PROTEGIDA) 👇
@auth_bp.route('/publicar-y-registrar', methods=['POST'])
def publicar_y_registrar():
    """Registra cliente y crea trabajo en un paso."""
    data = request.json
    nombre = data.get('nombre')
    email = data.get('email')
    password = data.get('password')

    try:
        if float(data.get('precio_calculado')) < 30:
            return jsonify({"error": "Presupuesto bajo"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "Precio inválido"}), 400

    # Verificación código
    verification = VerificationCode.query.filter_by(
        email=email, code=data.get('codigo')
    ).first()

    if not verification or not verification.is_valid():
        return jsonify({"error": "Código inválido"}), 400
    db.session.delete(verification)

    if Cliente.query.filter_by(email=email).first():
        return jsonify({"error": "Email registrado"}), 400

    try:
        nuevo_cliente = Cliente(nombre=nombre, email=email)
        nuevo_cliente.set_password(password)

        nuevo_trabajo = Trabajo(
            descripcion=data.get('descripcion'),
            direccion=data.get('direccion'),
            precio_calculado=data.get('precio_calculado'),
            estado='cotizacion',
            imagenes_urls=data.get('imagenes', []),
            etiquetas=data.get('etiquetas', []),
            desglose=data.get('desglose')
        )
        nuevo_trabajo.cliente = nuevo_cliente

        db.session.add(nuevo_cliente)
        db.session.add(nuevo_trabajo)
        db.session.commit()

        obtener_o_crear_wallet(nuevo_cliente.id, 'cliente')
        asignar_bono_bienvenida(nuevo_cliente.id, 'cliente')

        try:
            enviar_resumen_presupuesto(
                nuevo_cliente.email,
                nuevo_cliente.nombre,
                nuevo_trabajo.precio_calculado,
                []
            )
        except Exception: # pylint: disable=broad-exception-caught
            pass

        token = create_access_token(
            identity=str(nuevo_cliente.id),
            additional_claims={"tipo": "cliente"}
        )
        return jsonify({"success": True, "access_token": token}), 201
    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@auth_bp.route('/login-y-publicar', methods=['POST'])
def login_y_publicar():
    """Login y publicación de trabajo simultáneo."""
    data = request.json
    email = data.get('email')
    password = data.get('password')

    cliente = Cliente.query.filter_by(email=email).first()
    if not cliente or not cliente.check_password(password):
        return jsonify({"error": "Credenciales incorrectas"}), 401

    token = create_access_token(
        identity=str(cliente.id),
        additional_claims={"tipo": "cliente"}
    )

    try:
        nuevo_trabajo = Trabajo(
            descripcion=data.get('descripcion'),
            direccion=data.get('direccion'),
            precio_calculado=data.get('precio_calculado'),
            cliente_id=cliente.id,
            estado='cotizacion',
            imagenes_urls=data.get('imagenes', []),
            etiquetas=data.get('etiquetas', []),
            desglose=data.get('desglose')
        )
        db.session.add(nuevo_trabajo)
        db.session.commit()
        return jsonify({"success": True, "access_token": token}), 201
    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ==========================================
# 👤 RUTAS DE PERFIL
# ==========================================

@auth_bp.route('/perfil', methods=['GET', 'PUT'])
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
            
            # Verificar bono bienvenida
            bono_existe = GemTransaction.query.filter_by(
                wallet_id=u.wallet.id, tipo='BONO_REGISTRO'
            ).first() is not None

            stripe_completado = False
            if u.stripe_account_id:
                try:
                    account = stripe.Account.retrieve(u.stripe_account_id)
                    stripe_completado = account.details_submitted
                except Exception as e: # pylint: disable=broad-exception-caught
                    print(f"Error verificando Stripe: {e}")

            saldo = u.wallet.saldo if u.wallet else 0
            return jsonify({
                "id": u.id, "nombre": u.nombre, "email": u.email,
                "telefono": u.telefono, "zona_servicio": u.zona_servicio,
                "tipo": "montador", "stripe_account_id": u.stripe_account_id,
                "stripe_boarding_completado": stripe_completado, 
                "gemas": saldo, "foto_url": u.foto_url,
                "bono_entregado": bono_existe,
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
        except Exception: # pylint: disable=broad-exception-caught
            db.session.rollback()
            return jsonify({"error": "Error al actualizar"}), 500
    return jsonify({"error": "Método no permitido"}), 405


@auth_bp.route('/perfil/foto', methods=['POST'])
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
        # 1. Subir a la nube
        url_publica = upload_image_to_gcs(file, folder="perfiles")
        
        if not url_publica:
            return jsonify({"error": "Error al guardar la imagen en la nube"}), 500

        # 2. Actualizar base de datos
        usuario = (
            Cliente.query.get(user_id) if tipo == 'cliente'
            else Montador.query.get(user_id)
        )

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
    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error general en subir_foto_perfil: {e}")
        return jsonify({"error": str(e)}), 500


@auth_bp.route('/perfil/dismiss-bono', methods=['POST'])
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
    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error en dismiss_bono: {e}")
        return jsonify({"error": str(e)}), 500