"""
Rutas de autenticación completas para Kiq Montajes.
Maneja login universal (Cliente/Montador), registro, recuperación y lógica de calculadora.
Cumple con estándares Pylint (PEP 8).
"""
import random
import os
from datetime import datetime, timedelta
# pylint: disable=no-name-in-module
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from werkzeug.security import generate_password_hash, check_password_hash
import resend
from app import db
# Importamos tus modelos REALES
from app.models import Cliente, Montador, Trabajo

auth_bp = Blueprint('auth', __name__)

# --- CONFIGURACIÓN EMAIL (RESEND) ---
RESEND_API_KEY = os.getenv('RESEND_API_KEY')
SENDER_EMAIL = os.getenv('SENDER_EMAIL', 'onboarding@resend.dev')

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

# --- ALMACÉN TEMPORAL DE CÓDIGOS ---
verification_codes = {}


def send_email(to_email, subject, content):
    """Envía un correo electrónico usando RESEND."""
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
        resend.Emails.send(params)
        return True
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"❌ Error enviando email: {e}")
        return False


# ==========================================
# RUTAS CRÍTICAS DE LOGIN Y REGISTRO
# ==========================================

@auth_bp.route('/api/login-universal', methods=['POST'])
def login_universal():
    """
    Ruta que busca tu Frontend. Intenta loguear en tabla Cliente O Montador.
    """
    data = request.json
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'message': 'Faltan datos (email o password)'}), 400

    email = data['email']
    password = data['password']

    # 1. Buscar en CLIENTES
    cliente = Cliente.query.filter_by(email=email).first()
    if cliente and check_password_hash(cliente.password_hash, password):
        token = create_access_token(
            identity=str(cliente.id),
            additional_claims={"rol": "cliente"}
        )
        return jsonify({
            'token': token,
            'user': {
                'id': cliente.id,
                'nombre': cliente.nombre,
                'email': cliente.email,
                'tipo': 'cliente',
                'foto_url': cliente.foto_url
            },
            'role': 'cliente',
            'redirect': '/panel-cliente'
        }), 200

    # 2. Buscar en MONTADORES
    montador = Montador.query.filter_by(email=email).first()
    if montador and check_password_hash(montador.password_hash, password):
        token = create_access_token(
            identity=str(montador.id),
            additional_claims={"rol": "montador"}
        )
        return jsonify({
            'token': token,
            'user': {
                'id': montador.id,
                'nombre': montador.nombre,
                'email': montador.email,
                'tipo': 'montador',
                'foto_url': montador.foto_url,
                'zona': montador.zona_servicio
            },
            'role': 'montador',
            'redirect': '/panel-montador'
        }), 200

    return jsonify({'message': 'Credenciales incorrectas o usuario no encontrado'}), 401


@auth_bp.route('/api/auth/login', methods=['POST'])
def login_standard():
    """Endpoint alternativo de login (por compatibilidad)."""
    return login_universal()


@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    """
    Registro manual (desde la página de registro, no desde el chat).
    Soporta 'cliente' o 'montador'.
    """
    data = request.json
    email = data.get('email')
    password = data.get('password')
    nombre = data.get('nombre')
    telefono = data.get('telefono', '')
    tipo = data.get('tipo', 'cliente')  # Por defecto cliente

    if not email or not password or not nombre:
        return jsonify({'message': 'Faltan datos obligatorios'}), 400

    # Verificar si existe en CUALQUIERA de las dos tablas
    if (Cliente.query.filter_by(email=email).first() or
            Montador.query.filter_by(email=email).first()):
        return jsonify({'message': 'El email ya está registrado'}), 400

    hashed_pw = generate_password_hash(password)

    try:
        nuevo_usuario = None
        if tipo == 'montador':
            nuevo_usuario = Montador(
                email=email,
                nombre=nombre,
                telefono=telefono,
                password_hash=hashed_pw,
                zona_servicio=data.get('zona', '')  # Extra para montadores
            )
        else:
            nuevo_usuario = Cliente(
                email=email,
                nombre=nombre,
                telefono=telefono,
                password_hash=hashed_pw
            )

        db.session.add(nuevo_usuario)
        db.session.commit()

        # Token
        token = create_access_token(
            identity=str(nuevo_usuario.id),
            additional_claims={"rol": tipo}
        )

        return jsonify({
            'message': 'Usuario creado exitosamente',
            'token': token,
            'user': {
                'id': nuevo_usuario.id,
                'nombre': nombre,
                'email': email,
                'tipo': tipo
            }
        }), 201

    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error Registro: {e}")
        return jsonify({'message': 'Error interno al registrar'}), 500


@auth_bp.route('/api/perfil', methods=['GET'])
@jwt_required()
def get_perfil():
    """
    Devuelve el perfil según el rol guardado en el token.
    """
    current_user_id = get_jwt_identity()
    claims = get_jwt()
    rol = claims.get("rol", "cliente")  # Fallback a cliente si es token viejo

    usuario = None
    if rol == 'montador':
        usuario = Montador.query.get(int(current_user_id))
    else:
        usuario = Cliente.query.get(int(current_user_id))

    if not usuario:
        return jsonify({'message': 'Usuario no encontrado'}), 404

    data = {
        'id': usuario.id,
        'nombre': usuario.nombre,
        'email': usuario.email,
        'telefono': usuario.telefono,
        'foto_url': usuario.foto_url,
        'tipo': rol,
        'fecha_registro': (
            usuario.fecha_registro.isoformat() if usuario.fecha_registro else None
        )
    }

    if rol == 'montador':
        data['zona_servicio'] = usuario.zona_servicio
        data['stripe_connected'] = bool(usuario.stripe_account_id)

    return jsonify(data), 200


@auth_bp.route('/api/perfil', methods=['PUT'])
@jwt_required()
def update_perfil():
    """Actualizar perfil del Cliente o Montador."""
    current_user_id = get_jwt_identity()
    claims = get_jwt()
    rol = claims.get("rol", "cliente")

    usuario = None
    if rol == 'montador':
        usuario = Montador.query.get(int(current_user_id))
    else:
        usuario = Cliente.query.get(int(current_user_id))

    if not usuario:
        return jsonify({'message': 'Usuario no encontrado'}), 404

    data = request.json

    # Corrección Pylint: sentencias en líneas separadas
    if 'nombre' in data:
        usuario.nombre = data['nombre']
    if 'telefono' in data:
        usuario.telefono = data['telefono']

    # Actualización específica para montadores
    if rol == 'montador' and 'zona_servicio' in data:
        usuario.zona_servicio = data['zona_servicio']

    if 'password' in data and data['password']:
        usuario.password_hash = generate_password_hash(data['password'])

    try:
        db.session.commit()
        return jsonify({'message': 'Perfil actualizado correctamente'}), 200
    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        return jsonify({'message': f'Error al actualizar: {str(e)}'}), 500


# ==========================================
# RUTAS DE LA CALCULADORA (CHAT)
# ==========================================

@auth_bp.route('/api/publicar-y-registrar', methods=['POST'])
def publicar_y_registrar():
    """
    Registra CLIENTE nuevo + Crea TRABAJO desde el Chat.
    """
    data = request.json
    try:
        email = data.get('email')
        password = data.get('password')
        nombre = data.get('nombre', 'Cliente')
        telefono = data.get('telefono', '')  # Capturamos móvil

        # Datos Trabajo
        descripcion = data.get('descripcion')
        direccion = data.get('direccion')
        precio = data.get('precio_calculado')
        imagenes = data.get('imagenes', [])
        etiquetas = data.get('etiquetas', [])
        desglose = data.get('desglose', {})

        if not email or not password:
            return jsonify({"error": "Faltan credenciales"}), 400

        # Verificación doble
        if (Cliente.query.filter_by(email=email).first() or
                Montador.query.filter_by(email=email).first()):
            return jsonify({"error": "El usuario ya existe"}), 400

        # 1. Crear Cliente
        nuevo_cliente = Cliente(
            email=email,
            nombre=nombre,
            telefono=telefono,
            password_hash=generate_password_hash(password)
        )
        db.session.add(nuevo_cliente)
        db.session.flush()

        # 2. Crear Trabajo
        nuevo_trabajo = Trabajo(
            cliente_id=nuevo_cliente.id,
            descripcion=descripcion if descripcion else "Nuevo Montaje",
            direccion=direccion or "Pendiente",
            precio_calculado=precio if precio else 0.0,
            estado='cotizacion',  # Estado inicial
            imagenes_urls=imagenes,
            etiquetas=etiquetas,
            desglose=desglose
        )
        db.session.add(nuevo_trabajo)
        db.session.commit()

        # 3. Token y Email
        token = create_access_token(
            identity=str(nuevo_cliente.id),
            additional_claims={"rol": "cliente"}
        )

        send_email(
            email,
            "¡Bienvenido a KIQ Montajes!",
            f"<h1>Hola {nombre}</h1><p>Tu cuenta ha sido creada y tu presupuesto guardado.</p>"
        )

        return jsonify({
            "message": "Cuenta creada y trabajo guardado",
            "access_token": token,
            "usuario": {"nombre": nombre, "tipo": "cliente"}
        }), 201

    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"❌ Error publicar-y-registrar: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500


@auth_bp.route('/api/login-y-publicar', methods=['POST'])
def login_y_publicar():
    """
    Loguea CLIENTE existente + Crea TRABAJO desde el Chat.
    """
    data = request.json
    try:
        email = data.get('email')
        password = data.get('password')

        # Datos Trabajo
        descripcion = data.get('descripcion')
        direccion = data.get('direccion')
        precio = data.get('precio_calculado')
        imagenes = data.get('imagenes', [])
        etiquetas = data.get('etiquetas', [])
        desglose = data.get('desglose', {})

        # Solo buscamos en Clientes (los montadores no piden presupuestos así)
        cliente = Cliente.query.filter_by(email=email).first()

        if not cliente or not check_password_hash(cliente.password_hash, password):
            return jsonify({"error": "Credenciales inválidas"}), 401

        nuevo_trabajo = Trabajo(
            cliente_id=cliente.id,
            descripcion=descripcion if descripcion else "Nuevo Montaje",
            direccion=direccion or "Pendiente",
            precio_calculado=precio if precio else 0.0,
            estado='cotizacion',
            imagenes_urls=imagenes,
            etiquetas=etiquetas,
            desglose=desglose
        )
        db.session.add(nuevo_trabajo)
        db.session.commit()

        token = create_access_token(
            identity=str(cliente.id),
            additional_claims={"rol": "cliente"}
        )

        return jsonify({
            "message": "Trabajo guardado exitosamente",
            "access_token": token
        }), 200

    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"❌ Error login-y-publicar: {e}")
        return jsonify({"error": "Error interno"}), 500


@auth_bp.route('/api/check-email', methods=['POST'])
def check_email():
    """Verifica si el email existe en CUALQUIER tabla."""
    data = request.json
    email = data.get('email')

    exists = (
        Cliente.query.filter_by(email=email).first() or
        Montador.query.filter_by(email=email).first()
    )

    if exists:
        return jsonify({"status": "existente", "mensaje": "Registrado"}), 200
    return jsonify({"status": "nuevo", "mensaje": "Disponible"}), 200


# ==========================================
# RECUPERACIÓN DE CONTRASEÑA
# ==========================================

@auth_bp.route('/api/auth/reset-password-request', methods=['POST'])
def reset_password_request():
    """Solicita el reseteo de contraseña."""
    data = request.json
    email = data.get('email')

    # Buscamos en ambos
    usuario = (
        Cliente.query.filter_by(email=email).first() or
        Montador.query.filter_by(email=email).first()
    )

    if usuario:
        code = str(random.randint(100000, 999999))
        verification_codes[email] = {
            "code": code,
            "expires_at": datetime.utcnow() + timedelta(minutes=15),
            "type": "reset_password"
        }
        content = f"<h2>Recuperación KIQ</h2><p>Tu código es:</p><h1>{code}</h1>"

        if send_email(email, "Recuperar Contraseña", content):
            return jsonify({'message': 'Código enviado'}), 200

        print(f"⚠️ MODO DEV: Código {code}")

    return jsonify({'message': 'Si el email existe, se ha enviado un código.'}), 200


@auth_bp.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    """Resetea la contraseña."""
    data = request.json
    email = data.get('email')
    code = data.get('code')
    new_password = data.get('new_password')

    if not email or not code or not new_password:
        return jsonify({'error': 'Faltan datos'}), 400

    record = verification_codes.get(email)
    if not record or record['code'] != code:
        return jsonify({'error': 'Código inválido o expirado'}), 400

    # Buscamos quién es para actualizar su pass
    cliente = Cliente.query.filter_by(email=email).first()
    montador = Montador.query.filter_by(email=email).first()

    if cliente:
        cliente.password_hash = generate_password_hash(new_password)
    elif montador:
        montador.password_hash = generate_password_hash(new_password)
    else:
        return jsonify({'error': 'Usuario no encontrado'}), 404

    db.session.commit()
    del verification_codes[email]
    return jsonify({'message': 'Contraseña actualizada con éxito'}), 200