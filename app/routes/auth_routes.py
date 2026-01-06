"""
Rutas de autenticación y registro para la aplicación.
Maneja login, registro, envío de códigos y recuperación de contraseña.
Usa RESEND para el envío de correos.
Adaptado al modelo de datos real (Cliente, Trabajo).
"""
import random
import os
from datetime import datetime, timedelta
# pylint: disable=no-name-in-module
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
import resend
from app import db
# IMPORTAMOS TUS MODELOS REALES
from app.models import Cliente, Trabajo

auth_bp = Blueprint('auth', __name__)

# --- CONFIGURACIÓN EMAIL (RESEND) ---
RESEND_API_KEY = os.getenv('RESEND_API_KEY')
SENDER_EMAIL = os.getenv('SENDER_EMAIL', 'onboarding@resend.dev')

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

# --- ALMACÉN TEMPORAL DE CÓDIGOS ---
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
    """Genera y envía un código de verificación."""
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

    print(f"⚠️ MODO DEV: El código para {email} es {code}")
    return jsonify({"message": "Código enviado (Simulado)"}), 200


@auth_bp.route('/api/check-email', methods=['POST'])
def check_email():
    """Verifica si un email ya existe (Solo Clientes por ahora)."""
    data = request.json
    email = data.get('email')

    if not email:
        return jsonify({"error": "Email requerido"}), 400

    cliente = Cliente.query.filter_by(email=email).first()

    if cliente:
        return jsonify({"status": "existente", "mensaje": "Email ya registrado"}), 200

    return jsonify({"status": "nuevo", "mensaje": "Email disponible"}), 200


@auth_bp.route('/api/publicar-y-registrar', methods=['POST'])
def publicar_y_registrar():
    """
    Registra un CLIENTE nuevo Y guarda su primer TRABAJO (cotización).
    """
    data = request.json
    try:
        # 1. Datos del Cliente
        email = data.get('email')
        password = data.get('password')
        nombre = data.get('nombre', 'Cliente')
        telefono = data.get('telefono', '')

        # 2. Datos del Trabajo (Presupuesto)
        descripcion = data.get('descripcion')
        direccion = data.get('direccion')
        precio = data.get('precio_calculado')
        imagenes = data.get('imagenes', [])
        etiquetas = data.get('etiquetas', [])
        desglose = data.get('desglose', {})

        if not email or not password:
            return jsonify({"error": "Email y contraseña requeridos"}), 400

        if Cliente.query.filter_by(email=email).first():
            return jsonify({"error": "El usuario ya existe"}), 400

        # Crear Cliente
        nuevo_cliente = Cliente(
            email=email,
            nombre=nombre,
            telefono=telefono,
            # Usamos set_password si tu modelo lo tiene, o hash directo
            password_hash=generate_password_hash(password)
        )
        db.session.add(nuevo_cliente)
        db.session.flush()  # Para obtener el ID

        # Crear Trabajo
        nuevo_trabajo = Trabajo(
            cliente_id=nuevo_cliente.id,
            descripcion=descripcion if descripcion else "Nuevo Montaje",
            direccion=direccion or "Dirección pendiente",
            precio_calculado=precio if precio else 0.0,
            estado='cotizacion',  # Usamos un estado inicial válido
            imagenes_urls=imagenes,
            etiquetas=etiquetas,
            desglose=desglose
        )
        db.session.add(nuevo_trabajo)
        db.session.commit()

        # Generar Token (Usamos ID numérico o email como identidad según tu JWT setup)
        # Asumimos que usas el ID numérico convertido a string
        access_token = create_access_token(identity=str(nuevo_cliente.id))

        # Enviar email
        send_email(
            email,
            "¡Bienvenido a KIQ Montajes!",
            f"<h1>Hola {nombre}</h1><p>Tu cuenta ha sido creada y tu presupuesto guardado.</p>"
        )

        return jsonify({
            "message": "Cliente y trabajo creados",
            "access_token": access_token,
            "usuario": {
                "nombre": nombre,
                "email": email,
                "telefono": telefono,
                "id": nuevo_cliente.id
            }
        }), 201

    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"❌ Error en publicar-y-registrar: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500


@auth_bp.route('/api/login-y-publicar', methods=['POST'])
def login_y_publicar():
    """
    Loguea a un cliente existente Y guarda un nuevo Trabajo.
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

        if not email or not password:
            return jsonify({"error": "Faltan credenciales"}), 400

        cliente = Cliente.query.filter_by(email=email).first()

        if not cliente or not check_password_hash(cliente.password_hash, password):
            return jsonify({"error": "Credenciales inválidas"}), 401

        # Crear Trabajo vinculado
        nuevo_trabajo = Trabajo(
            cliente_id=cliente.id,
            descripcion=descripcion if descripcion else "Nuevo Montaje",
            direccion=direccion or "Dirección pendiente",
            precio_calculado=precio if precio else 0.0,
            estado='cotizacion',
            imagenes_urls=imagenes,
            etiquetas=etiquetas,
            desglose=desglose
        )
        db.session.add(nuevo_trabajo)
        db.session.commit()

        access_token = create_access_token(identity=str(cliente.id))

        return jsonify({
            "message": "Sesión iniciada y trabajo guardado",
            "access_token": access_token
        }), 200

    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"❌ Error en login-y-publicar: {e}")
        return jsonify({"error": "Error interno"}), 500


@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    """Login estándar."""
    data = request.json
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'message': 'Faltan datos'}), 400

    cliente = Cliente.query.filter_by(email=data['email']).first()

    if not cliente:
        return jsonify({'message': 'Usuario no encontrado'}), 401

    if check_password_hash(cliente.password_hash, data['password']):
        token = create_access_token(identity=str(cliente.id))
        return jsonify({
            'token': token,
            'user': {
                'nombre': cliente.nombre,
                'email': cliente.email,
                'tipo': 'cliente'
            }
        })

    return jsonify({'message': 'Contraseña incorrecta'}), 401


@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    """Registro estándar de Cliente."""
    data = request.json
    email = data.get('email')
    password = data.get('password')
    nombre = data.get('nombre')
    telefono = data.get('telefono', '')

    if not email or not password or not nombre:
        return jsonify({'message': 'Faltan datos'}), 400

    if Cliente.query.filter_by(email=email).first():
        return jsonify({'message': 'El usuario ya existe'}), 400

    nuevo_cliente = Cliente(
        email=email,
        nombre=nombre,
        telefono=telefono,
        password_hash=generate_password_hash(password)
    )

    db.session.add(nuevo_cliente)
    db.session.commit()

    token = create_access_token(identity=str(nuevo_cliente.id))

    return jsonify({
        'message': 'Usuario creado exitosamente',
        'token': token,
        'user': {
            'nombre': nombre,
            'email': email,
            'tipo': 'cliente',
            'telefono': telefono
        }
    }), 201


@auth_bp.route('/api/perfil', methods=['GET'])
@jwt_required()
def get_perfil():
    """Perfil del Cliente."""
    current_user_id = get_jwt_identity()
    cliente = Cliente.query.get(int(current_user_id))

    if not cliente:
        return jsonify({'message': 'Usuario no encontrado'}), 404

    return jsonify({
        'nombre': cliente.nombre,
        'email': cliente.email,
        'telefono': cliente.telefono,
        'tipo': 'cliente',
        'fecha_registro': cliente.fecha_registro.isoformat()
    }), 200


@auth_bp.route('/api/perfil', methods=['PUT'])
@jwt_required()
def update_perfil():
    """Actualizar perfil del Cliente."""
    current_user_id = get_jwt_identity()
    cliente = Cliente.query.get(int(current_user_id))

    if not cliente:
        return jsonify({'message': 'Usuario no encontrado'}), 404

    data = request.json
    if 'nombre' in data: cliente.nombre = data['nombre']
    if 'telefono' in data: cliente.telefono = data['telefono']

    if 'password' in data and data['password']:
        cliente.password_hash = generate_password_hash(data['password'])

    try:
        db.session.commit()
        return jsonify({'message': 'Perfil actualizado correctamente'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Error al actualizar: {str(e)}'}), 500


@auth_bp.route('/api/auth/reset-password-request', methods=['POST'])
def reset_password_request():
    """Solicita reseteo de contraseña."""
    data = request.json
    email = data.get('email')

    cliente = Cliente.query.filter_by(email=email).first()
    # No revelamos si existe o no por seguridad, pero si existe enviamos código
    if cliente:
        code = str(random.randint(100000, 999999))
        verification_codes[email] = {
            "code": code,
            "expires_at": datetime.utcnow() + timedelta(minutes=15),
            "type": "reset_password"
        }
        content = f"<h2>Recuperación KIQ</h2><h1>{code}</h1>"
        
        if send_email(email, "Recuperar Contraseña", content):
            return jsonify({'message': 'Código enviado'}), 200
        
        # Modo Dev fallback
        print(f"⚠️ MODO DEV: Código {code}")

    return jsonify({'message': 'Si el email existe, se ha enviado un código.'}), 200


@auth_bp.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    """Cambia la contraseña."""
    data = request.json
    email = data.get('email')
    code = data.get('code')
    new_password = data.get('new_password')

    if not email or not code or not new_password:
        return jsonify({'error': 'Faltan datos'}), 400

    record = verification_codes.get(email)
    if not record or record['code'] != code:
        return jsonify({'error': 'Código inválido o expirado'}), 400

    if datetime.utcnow() > record['expires_at']:
        return jsonify({'error': 'El código ha expirado'}), 400

    cliente = Cliente.query.filter_by(email=email).first()
    if cliente:
        cliente.password_hash = generate_password_hash(new_password)
        db.session.commit()
        del verification_codes[email]
        return jsonify({'message': 'Contraseña actualizada con éxito'}), 200

    return jsonify({'error': 'Usuario no encontrado'}), 404