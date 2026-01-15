"""
Rutas de autenticación completas para Kiq Montajes.
Maneja:
1. Login Universal (Cliente/Montador)
2. Registro Montadores (Modal)
3. Registro Clientes (Chat)
4. Registro Genérico (Legacy)
5. Gestión de Perfil (Ver/Editar)
6. Recuperación de Contraseña
7. Panel Admin
8. Verificación de Códigos
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
# 1. SISTEMA DE CÓDIGOS (Send/Verify)
# ==========================================

@auth_bp.route('/auth/send-code', methods=['POST'])
def send_verification_code():
    """Genera y envía un código de verificación."""
    data = request.json
    email = data.get('email')

    if not email:
        return jsonify({"error": "Email requerido"}), 400

    # Verificamos si ya existe para avisar al usuario (útil para el registro)
    if (Cliente.query.filter_by(email=email).first() or
            Montador.query.filter_by(email=email).first()):
        # No bloqueamos el envío por si es para recuperar contraseña,
        # pero el frontend puede usar este status.
        return jsonify({
            "status": "registrado",
            "message": "Este email ya está registrado."
        }), 200

    code = str(random.randint(100000, 999999))
    verification_codes[email] = {
        "code": code,
        "expires_at": datetime.utcnow() + timedelta(minutes=10)
    }

    content = f"""
    <h2>Tu código de verificación KIQ</h2>
    <p>Usa este código para verificar tu operación:</p>
    <h1 style="color: #4F46E5; letter-spacing: 5px;">{code}</h1>
    <p>Este código expira en 10 minutos.</p>
    """

    if send_email(email, "Código de Verificación - KIQ", content):
        return jsonify({"status": "enviado", "message": "Código enviado"}), 200

    print(f"⚠️ MODO DEV: El código para {email} es {code}")
    return jsonify({"status": "enviado", "message": "Código enviado (Simulado)"}), 200


@auth_bp.route('/auth/verify-code', methods=['POST'])
def verify_code():
    """Verifica si el código es correcto."""
    data = request.json
    email = data.get('email')
    code = data.get('code')

    if not email or not code:
        return jsonify({"error": "Faltan datos"}), 400

    record = verification_codes.get(email)
    if not record or record['code'] != code:
        return jsonify({"error": "Código incorrecto o expirado"}), 400

    return jsonify({"message": "Código correcto"}), 200


# ==========================================
# 2. LOGIN (Universal y Standard)
# ==========================================

@auth_bp.route('/login-universal', methods=['POST'])
def login_universal():
    """Login que busca en ambas tablas (Cliente y Montador)."""
    data = request.json
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'message': 'Faltan datos'}), 400

    email = data['email']
    password = data['password']

    # 1. Intentar CLIENTE
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
                'telefono': cliente.telefono,
                'foto_url': cliente.foto_url
            },
            'role': 'cliente',
            'redirect': '/panel-cliente'
        }), 200

    # 2. Intentar MONTADOR
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
                'telefono': montador.telefono,
                'foto_url': montador.foto_url,
                'zona': montador.zona_servicio
            },
            'role': 'montador',
            'redirect': '/panel-montador'
        }), 200

    return jsonify({'message': 'Credenciales incorrectas'}), 401


@auth_bp.route('/auth/login', methods=['POST'])
def login_standard():
    """Alias para login universal."""
    return login_universal()


# ==========================================
# 3. REGISTROS (Genérico, Montador y Cliente-Chat)
# ==========================================

# A) REGISTRO ESPECÍFICO MONTADOR (Desde el Modal)
@auth_bp.route('/montador/registro', methods=['POST'])
def register_montador():
    """Recibe datos del Modal, verifica código y crea Montador."""
    data = request.json

    nombre = data.get('nombre')
    email = data.get('email')
    password = data.get('password')
    telefono = data.get('telefono')
    zona = data.get('zona_servicio')
    codigo_usuario = data.get('codigo')

    if not all([nombre, email, password, codigo_usuario]):
        return jsonify({'error': 'Faltan datos obligatorios'}), 400

    # Verificar Código
    record = verification_codes.get(email)
    if not record or record['code'] != codigo_usuario:
        return jsonify({'error': 'Código de verificación incorrecto'}), 400

    # Verificar existencia
    if (Cliente.query.filter_by(email=email).first() or
            Montador.query.filter_by(email=email).first()):
        return jsonify({'error': 'El usuario ya existe'}), 400

    try:
        nuevo_montador = Montador(
            email=email,
            nombre=nombre,
            telefono=telefono,
            zona_servicio=zona,
            password_hash=generate_password_hash(password)
        )

        db.session.add(nuevo_montador)
        db.session.commit()

        token = create_access_token(
            identity=str(nuevo_montador.id),
            additional_claims={"rol": "montador"}
        )
        del verification_codes[email]

        return jsonify({
            'message': 'Montador registrado con éxito',
            'access_token': token,
            'user': {
                'id': nuevo_montador.id,
                'nombre': nuevo_montador.nombre,
                'email': nuevo_montador.email,
                'tipo': 'montador',
                'zona': nuevo_montador.zona_servicio
            }
        }), 201

    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error Registro Montador: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500


# B) REGISTRO GENÉRICO (Legacy / Backup)
@auth_bp.route('/auth/register', methods=['POST'])
def register():
    """Registro estándar sin código obligatorio (para compatibilidad)."""
    data = request.json
    email = data.get('email')
    password = data.get('password')
    nombre = data.get('nombre')
    telefono = data.get('telefono', '')
    tipo = data.get('tipo', 'cliente')

    if not email or not password or not nombre:
        return jsonify({'message': 'Faltan datos obligatorios'}), 400

    if (Cliente.query.filter_by(email=email).first() or
            Montador.query.filter_by(email=email).first()):
        return jsonify({'message': 'El email ya está registrado'}), 400

    hashed_pw = generate_password_hash(password)

    try:
        nuevo_usuario = None
        if tipo == 'montador':
            nuevo_usuario = Montador(
                email=email, nombre=nombre, telefono=telefono, password_hash=hashed_pw,
                zona_servicio=data.get('zona', '')
            )
        else:
            nuevo_usuario = Cliente(
                email=email, nombre=nombre, telefono=telefono, password_hash=hashed_pw
            )

        db.session.add(nuevo_usuario)
        db.session.commit()

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
        print(f"Error genérico registro: {e}")
        return jsonify({'message': 'Error interno al registrar'}), 500


# C) REGISTRO CLIENTE DESDE CHAT
@auth_bp.route('/publicar-y-registrar', methods=['POST'])
def publicar_y_registrar():
    """Registra CLIENTE nuevo + Crea TRABAJO."""
    data = request.json
    try:
        email = data.get('email')
        password = data.get('password')
        nombre = data.get('nombre', 'Cliente')
        telefono = data.get('telefono', '')

        if not email or not password:
            return jsonify({"error": "Faltan credenciales"}), 400

        if (Cliente.query.filter_by(email=email).first() or
                Montador.query.filter_by(email=email).first()):
            return jsonify({"error": "El usuario ya existe"}), 400

        nuevo_cliente = Cliente(
            email=email,
            nombre=nombre,
            telefono=telefono,
            password_hash=generate_password_hash(password)
        )
        db.session.add(nuevo_cliente)
        db.session.flush()

        nuevo_trabajo = Trabajo(
            cliente_id=nuevo_cliente.id,
            descripcion=data.get('descripcion', "Nuevo Montaje"),
            direccion=data.get('direccion', "Pendiente"),
            precio_calculado=data.get('precio_calculado', 0.0),
            estado='cotizacion',
            imagenes_urls=data.get('imagenes', []),
            etiquetas=data.get('etiquetas', []),
            desglose=data.get('desglose', {})
        )
        db.session.add(nuevo_trabajo)
        db.session.commit()

        token = create_access_token(
            identity=str(nuevo_cliente.id),
            additional_claims={"rol": "cliente"}
        )

        send_email(
            email,
            "Bienvenido a KIQ",
            f"<h1>Hola {nombre}</h1><p>Presupuesto creado.</p>"
        )

        return jsonify({
            "message": "Cuenta creada",
            "access_token": token,
            "usuario": {"nombre": nombre, "tipo": "cliente", "telefono": telefono}
        }), 201

    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"❌ Error publicar-y-registrar: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500


@auth_bp.route('/login-y-publicar', methods=['POST'])
def login_y_publicar():
    """Cliente existente publica trabajo."""
    data = request.json
    email = data.get('email')
    password = data.get('password')

    cliente = Cliente.query.filter_by(email=email).first()
    if not cliente or not check_password_hash(cliente.password_hash, password):
        return jsonify({"error": "Credenciales inválidas"}), 401

    try:
        nuevo_trabajo = Trabajo(
            cliente_id=cliente.id,
            descripcion=data.get('descripcion'),
            direccion=data.get('direccion'),
            precio_calculado=data.get('precio_calculado'),
            estado='cotizacion',
            imagenes_urls=data.get('imagenes', []),
            etiquetas=data.get('etiquetas', []),
            desglose=data.get('desglose', {})
        )
        db.session.add(nuevo_trabajo)
        db.session.commit()

        token = create_access_token(
            identity=str(cliente.id),
            additional_claims={"rol": "cliente"}
        )
        return jsonify({"message": "Trabajo guardado", "access_token": token}), 200

    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ==========================================
# 4. GESTIÓN DE PERFIL (GET y PUT)
# ==========================================

@auth_bp.route('/perfil', methods=['GET'])
@jwt_required()
def get_perfil():
    """Devuelve datos del perfil del usuario."""
    current_user_id = get_jwt_identity()
    claims = get_jwt()
    rol = claims.get("rol", "cliente")

    usuario = (Montador.query.get(int(current_user_id)) if rol == 'montador'
               else Cliente.query.get(int(current_user_id)))

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


@auth_bp.route('/perfil', methods=['PUT'])
@jwt_required()
def update_perfil():
    """Actualizar perfil del usuario."""
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

    # Pylint: sentencias separadas
    if 'nombre' in data:
        usuario.nombre = data['nombre']
    if 'telefono' in data:
        usuario.telefono = data['telefono']
    if 'password' in data and data['password']:
        usuario.password_hash = generate_password_hash(data['password'])

    if rol == 'montador' and 'zona_servicio' in data:
        usuario.zona_servicio = data['zona_servicio']

    try:
        db.session.commit()
        return jsonify({'message': 'Perfil actualizado correctamente'}), 200
    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        return jsonify({'message': f'Error al actualizar: {str(e)}'}), 500


# ==========================================
# 5. RECUPERACIÓN DE CONTRASEÑA
# ==========================================

@auth_bp.route('/auth/reset-password-request', methods=['POST'])
def reset_password_request():
    """Pide código para resetear password."""
    data = request.json
    email = data.get('email')

    usuario = (Cliente.query.filter_by(email=email).first() or
               Montador.query.filter_by(email=email).first())

    if usuario:
        code = str(random.randint(100000, 999999))
        verification_codes[email] = {
            "code": code,
            "expires_at": datetime.utcnow() + timedelta(minutes=15),
            "type": "reset_password"
        }
        content = f"<h2>Recuperación KIQ</h2><p>Código:</p><h1>{code}</h1>"
        send_email(email, "Recuperar Contraseña", content)
        # Devolvemos éxito siempre por seguridad (para no revelar emails)

    return jsonify({'message': 'Si el email existe, se ha enviado un código.'}), 200


@auth_bp.route('/auth/reset-password', methods=['POST'])
def reset_password():
    """Cambia la contraseña usando el código."""
    data = request.json
    email = data.get('email')
    code = data.get('code')
    new_password = data.get('new_password')

    if not email or not code or not new_password:
        return jsonify({'error': 'Faltan datos'}), 400

    record = verification_codes.get(email)
    if not record or record['code'] != code:
        return jsonify({'error': 'Código inválido o expirado'}), 400

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


# ==========================================
# 6. UTILIDADES Y ADMIN
# ==========================================

@auth_bp.route('/check-email', methods=['POST'])
def check_email():
    """Verifica si el email existe."""
    email = request.json.get('email')
    if (Cliente.query.filter_by(email=email).first() or
            Montador.query.filter_by(email=email).first()):
        return jsonify({"status": "existente"}), 200
    return jsonify({"status": "nuevo"}), 200


@auth_bp.route('/admin/todos-los-trabajos', methods=['GET'])
def admin_get_todos_los_trabajos():
    """Panel Admin Seguro."""
    if request.headers.get('x-admin-secret') != 'kiq2025master':
        return jsonify({'error': 'Acceso denegado.'}), 401

    trabajos = Trabajo.query.order_by(Trabajo.fecha_creacion.desc()).all()
    lista_final = []

    for t in trabajos:
        cliente = Cliente.query.get(t.cliente_id)
        montador_nombre = "Sin asignar"
        if t.montador_id:
            m = Montador.query.get(t.montador_id)
            if m:
                montador_nombre = m.nombre

        lista_final.append({
            "id": t.id,
            "fecha": t.fecha_creacion.strftime('%Y-%m-%d %H:%M'),
            "cliente": cliente.nombre if cliente else "Desconocido",
            "email_cliente": cliente.email if cliente else "",
            "telefono_cliente": cliente.telefono if cliente else "",
            "descripcion": t.descripcion,
            "precio": (
                t.precio_estimado if t.precio_estimado else t.precio_calculado
            ),
            "montador": montador_nombre,
            "estado": t.estado
        })

    return jsonify(lista_final), 200