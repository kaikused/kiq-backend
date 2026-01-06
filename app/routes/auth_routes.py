"""
Rutas de autenticación y registro para la aplicación.
Maneja login, registro, envío de códigos y recuperación de contraseña.
Usa RESEND para el envío de correos.
"""
import random
import uuid
import os
from datetime import datetime, timedelta
# pylint: disable=no-name-in-module
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
import resend  # Usamos Resend en lugar de SendGrid
from app import db
from app.models import Usuario, Presupuesto

auth_bp = Blueprint('auth', __name__)

# --- CONFIGURACIÓN EMAIL (RESEND) ---
RESEND_API_KEY = os.getenv('RESEND_API_KEY')
# Si no tienes un sender verificado, Resend usa 'onboarding@resend.dev' para pruebas
SENDER_EMAIL = os.getenv('SENDER_EMAIL', 'onboarding@resend.dev')

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

# --- ALMACÉN TEMPORAL DE CÓDIGOS (En producción usar Redis) ---
verification_codes = {}


def send_email(to_email, subject, content):
    """
    Envía un correo electrónico usando RESEND.
    """
    if not RESEND_API_KEY:
        print("⚠️ Resend API Key no configurada.")
        return False

    try:
        params = {
            "from": SENDER_EMAIL,
            "to": [to_email],
            "subject": subject,
            "html": content,
        }
        email = resend.Emails.send(params)
        print(f"📧 Email enviado a {to_email}: ID {email.get('id')}")
        return True
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"❌ Error enviando email con Resend: {e}")
        return False


@auth_bp.route('/api/auth/send-code', methods=['POST'])
def send_verification_code():
    """
    Genera y envía un código de verificación de 6 dígitos al email.
    """
    data = request.json
    email = data.get('email')

    if not email:
        return jsonify({"error": "Email requerido"}), 400

    code = str(random.randint(100000, 999999))
    verification_codes[email] = {
        "code": code,
        "expires_at": datetime.utcnow() + timedelta(minutes=10)
    }

    content = f"""
    <h2>Tu código de verificación KIQ</h2>
    <p>Usa este código para verificar tu cuenta:</p>
    <h1 style="color: #4F46E5; letter-spacing: 5px;">{code}</h1>
    <p>Este código expira en 10 minutos.</p>
    """

    if send_email(email, "Código de Verificación - KIQ", content):
        return jsonify({"message": "Código enviado"}), 200

    # Fallback para desarrollo si falla el envío
    print(f"⚠️ MODO DEV: El código para {email} es {code}")
    return jsonify({"message": "Código enviado (Simulado en logs)"}), 200


@auth_bp.route('/api/check-email', methods=['POST'])
def check_email():
    """
    Verifica si un email ya existe en la base de datos.
    """
    data = request.json
    email = data.get('email')

    if not email:
        return jsonify({"error": "Email requerido"}), 400

    usuario = Usuario.query.filter_by(email=email).first()

    if usuario:
        return jsonify({"status": "existente", "mensaje": "Email ya registrado"}), 200

    return jsonify({"status": "nuevo", "mensaje": "Email disponible"}), 200


@auth_bp.route('/api/publicar-y-registrar', methods=['POST'])
def publicar_y_registrar():
    """
    Registra un usuario nuevo Y guarda su primer presupuesto en un solo paso.
    Incluye campo teléfono/móvil.
    """
    data = request.json
    try:
        # 1. Datos del Usuario
        email = data.get('email')
        password = data.get('password')
        nombre = data.get('nombre', 'Cliente')
        telefono = data.get('telefono', '')  # <--- AQUI CAPTURAMOS EL MÓVIL

        # 2. Datos del Presupuesto
        descripcion = data.get('descripcion')
        direccion = data.get('direccion')
        precio = data.get('precio_calculado')
        imagenes = data.get('imagenes', [])
        etiquetas = data.get('etiquetas', [])
        desglose = data.get('desglose', {})

        if not email or not password:
            return jsonify({"error": "Email y contraseña requeridos"}), 400

        # Verificar si ya existe
        if Usuario.query.filter_by(email=email).first():
            return jsonify({"error": "El usuario ya existe"}), 400

        # Crear Usuario
        nuevo_usuario = Usuario(
            public_id=str(uuid.uuid4()),
            email=email,
            nombre=nombre,
            password_hash=generate_password_hash(password),
            tipo='cliente',
            telefono=telefono,  # Guardamos el móvil
            direccion=direccion or ''
        )
        db.session.add(nuevo_usuario)
        db.session.flush()  # Para obtener el ID

        # Crear Presupuesto
        nuevo_presupuesto = Presupuesto(
            usuario_id=nuevo_usuario.id,
            titulo=f"Montaje: {descripcion[:30]}..." if descripcion else "Nuevo Montaje",
            descripcion=descripcion,
            precio_estimado=precio,
            estado='pendiente_revision',
            ubicacion=direccion,
            imagenes=imagenes,
            etiquetas=etiquetas,
            desglose_json=desglose
        )
        db.session.add(nuevo_presupuesto)
        db.session.commit()

        # Generar Token
        access_token = create_access_token(identity=nuevo_usuario.public_id)

        # Enviar email de bienvenida
        send_email(
            email,
            "¡Bienvenido a KIQ Montajes!",
            f"<h1>Hola {nombre}</h1><p>Tu cuenta ha sido creada y tu presupuesto guardado.</p>"
        )

        return jsonify({
            "message": "Usuario y presupuesto creados",
            "access_token": access_token,
            "usuario": {
                "nombre": nombre,
                "email": email,
                "telefono": telefono,
                "public_id": nuevo_usuario.public_id
            }
        }), 201

    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"❌ Error en publicar-y-registrar: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500


@auth_bp.route('/api/login-y-publicar', methods=['POST'])
def login_y_publicar():
    """
    Loguea a un usuario existente Y guarda un nuevo presupuesto.
    """
    data = request.json
    try:
        email = data.get('email')
        password = data.get('password')

        # Datos presupuesto
        descripcion = data.get('descripcion')
        direccion = data.get('direccion')
        precio = data.get('precio_calculado')
        imagenes = data.get('imagenes', [])
        etiquetas = data.get('etiquetas', [])
        desglose = data.get('desglose', {})

        if not email or not password:
            return jsonify({"error": "Faltan credenciales"}), 400

        usuario = Usuario.query.filter_by(email=email).first()

        if not usuario or not check_password_hash(usuario.password_hash, password):
            return jsonify({"error": "Credenciales inválidas"}), 401

        # Crear Presupuesto vinculado
        nuevo_presupuesto = Presupuesto(
            usuario_id=usuario.id,
            titulo=f"Montaje: {descripcion[:30]}..." if descripcion else "Nuevo Montaje",
            descripcion=descripcion,
            precio_estimado=precio,
            estado='pendiente_revision',
            ubicacion=direccion,
            imagenes=imagenes,
            etiquetas=etiquetas,
            desglose_json=desglose
        )
        db.session.add(nuevo_presupuesto)
        db.session.commit()

        access_token = create_access_token(identity=usuario.public_id)

        return jsonify({
            "message": "Sesión iniciada y presupuesto guardado",
            "access_token": access_token
        }), 200

    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"❌ Error en login-y-publicar: {e}")
        return jsonify({"error": "Error interno"}), 500


@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    """
    Endpoint estándar de login.
    """
    data = request.json
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'message': 'Faltan datos'}), 400

    usuario = Usuario.query.filter_by(email=data['email']).first()

    if not usuario:
        return jsonify({'message': 'Usuario no encontrado'}), 401

    if check_password_hash(usuario.password_hash, data['password']):
        token = create_access_token(identity=usuario.public_id)
        return jsonify({
            'token': token,
            'user': {
                'nombre': usuario.nombre,
                'email': usuario.email,
                'tipo': usuario.tipo
            }
        })

    return jsonify({'message': 'Contraseña incorrecta'}), 401


@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    """
    Endpoint estándar de registro (sin presupuesto).
    """
    data = request.json
    email = data.get('email')
    password = data.get('password')
    nombre = data.get('nombre')
    telefono = data.get('telefono', '')  # <--- AQUI CAPTURAMOS EL MÓVIL
    tipo = data.get('tipo', 'cliente')

    if not email or not password or not nombre:
        return jsonify({'message': 'Faltan datos'}), 400

    if Usuario.query.filter_by(email=email).first():
        return jsonify({'message': 'El usuario ya existe'}), 400

    hashed_password = generate_password_hash(password, method='scrypt')

    nuevo_usuario = Usuario(
        public_id=str(uuid.uuid4()),
        email=email,
        nombre=nombre,
        telefono=telefono,  # Guardamos el móvil
        password_hash=hashed_password,
        tipo=tipo
    )

    db.session.add(nuevo_usuario)
    db.session.commit()

    token = create_access_token(identity=nuevo_usuario.public_id)

    return jsonify({
        'message': 'Usuario creado exitosamente',
        'token': token,
        'user': {
            'nombre': nombre,
            'email': email,
            'tipo': tipo,
            'telefono': telefono
        }
    }), 201


@auth_bp.route('/api/perfil', methods=['GET'])
@jwt_required()
def get_perfil():
    """
    Obtiene los datos del perfil del usuario logueado.
    """
    current_user_id = get_jwt_identity()
    usuario = Usuario.query.filter_by(public_id=current_user_id).first()

    if not usuario:
        return jsonify({'message': 'Usuario no encontrado'}), 404

    return jsonify({
        'nombre': usuario.nombre,
        'email': usuario.email,
        'telefono': usuario.telefono,
        'direccion': usuario.direccion,
        'tipo': usuario.tipo,
        'fecha_registro': usuario.fecha_registro.isoformat()
    }), 200


@auth_bp.route('/api/perfil', methods=['PUT'])
@jwt_required()
def update_perfil():
    """
    Actualiza los datos del perfil.
    """
    current_user_id = get_jwt_identity()
    usuario = Usuario.query.filter_by(public_id=current_user_id).first()

    if not usuario:
        return jsonify({'message': 'Usuario no encontrado'}), 404

    data = request.json
    if 'nombre' in data:
        usuario.nombre = data['nombre']
    if 'telefono' in data:
        usuario.telefono = data['telefono']
    if 'direccion' in data:
        usuario.direccion = data['direccion']

    # Cambio de contraseña opcional
    if 'password' in data and data['password']:
        usuario.password_hash = generate_password_hash(data['password'])

    try:
        db.session.commit()
        return jsonify({'message': 'Perfil actualizado correctamente'}), 200
    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        return jsonify({'message': f'Error al actualizar: {str(e)}'}), 500


@auth_bp.route('/api/auth/reset-password-request', methods=['POST'])
def reset_password_request():
    """
    Solicita un reseteo de contraseña enviando un código al email.
    """
    data = request.json
    email = data.get('email')

    usuario = Usuario.query.filter_by(email=email).first()
    if not usuario:
        # Por seguridad, no decimos si el email existe o no
        return jsonify({'message': 'Si el email existe, se ha enviado un código.'}), 200

    # Generar código de recuperación
    code = str(random.randint(100000, 999999))
    verification_codes[email] = {
        "code": code,
        "expires_at": datetime.utcnow() + timedelta(minutes=15),
        "type": "reset_password"
    }

    content = f"""
    <h2>Recuperación de Contraseña - KIQ</h2>
    <p>Has solicitado restablecer tu contraseña. Usa este código:</p>
    <h1 style="color: #DC2626; letter-spacing: 5px;">{code}</h1>
    <p>Si no fuiste tú, ignora este mensaje.</p>
    """

    if send_email(email, "Recuperar Contraseña", content):
        return jsonify({'message': 'Código enviado'}), 200

    print(f"⚠️ MODO DEV (Recuperar): Código para {email}: {code}")
    return jsonify({'message': 'Código enviado (Simulado)'}), 200


@auth_bp.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    """
    Cambia la contraseña usando el código de verificación.
    """
    data = request.json
    email = data.get('email')
    code = data.get('code')
    new_password = data.get('new_password')

    if not email or not code or not new_password:
        return jsonify({'error': 'Faltan datos'}), 400

    # Verificar código
    record = verification_codes.get(email)
    if not record or record['code'] != code:
        return jsonify({'error': 'Código inválido o expirado'}), 400

    if datetime.utcnow() > record['expires_at']:
        return jsonify({'error': 'El código ha expirado'}), 400

    if record.get('type') != 'reset_password':
        return jsonify({'error': 'Código inválido para esta operación'}), 400

    # Cambiar contraseña
    usuario = Usuario.query.filter_by(email=email).first()
    if usuario:
        usuario.password_hash = generate_password_hash(new_password)
        db.session.commit()
        # Eliminar código usado
        del verification_codes[email]
        return jsonify({'message': 'Contraseña actualizada con éxito'}), 200

    return jsonify({'error': 'Usuario no encontrado'}), 404