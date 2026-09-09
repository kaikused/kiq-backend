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
9. Subida de Foto de Perfil
"""
import random
import os   # ✅ NECESARIO para leer variables de entorno
import re
import secrets
from datetime import datetime, timedelta
# pylint: disable=no-name-in-module
from flask import Blueprint, request, jsonify
from flask_cors import cross_origin
import cloudinary           # ✅ NECESARIO para configurar
import cloudinary.uploader

from flask_jwt_extended import (
    create_access_token, decode_token, jwt_required, get_jwt_identity, get_jwt
)
from werkzeug.security import generate_password_hash, check_password_hash

from app import db
# Importamos tus modelos REALES (Agregado Wallet aquí para evitar C0415)
from app.models import Cliente, Montador, Trabajo, Code, Wallet
# IMPORTAMOS LOS SERVICIOS ROBUSTOS
from app.email_service import enviar_codigo_verificacion, enviar_email_generico
from app.gems_service import asignar_bono_bienvenida

# ==========================================
# 0. CONFIGURACIÓN CLOUDINARY (Integrada)
# ==========================================
cloudinary.config(
  cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
  api_key=os.getenv('CLOUDINARY_API_KEY'),
  api_secret=os.getenv('CLOUDINARY_API_SECRET'),
  secure=True
)

auth_bp = Blueprint('auth', __name__)


def _validar_identidad(nombre, email, telefono):
    """Nombre y apellidos, email y teléfono obligatorios."""
    if not (nombre or "").strip() or not (email or "").strip():
        return "Faltan nombre o correo"
    if len((nombre or "").split()) < 2:
        return "Escribe nombre y apellidos"
    digits = re.sub(r"\D", "", telefono or "")
    if len(digits) < 9:
        return "El teléfono es obligatorio (mínimo 9 dígitos)"
    return None

# ==========================================
# 1. SISTEMA DE CÓDIGOS (Send/Verify) - DB
# ==========================================

@auth_bp.route('/auth/send-code', methods=['POST'])
def send_verification_code():
    """Genera y envía un código de verificación (Guardado en DB)."""
    data = request.json
    email = data.get('email')

    if not email:
        return jsonify({"error": "Email requerido"}), 400

    # Verificamos si ya existe para avisar al usuario
    if (Cliente.query.filter_by(email=email).first() or
            Montador.query.filter_by(email=email).first()):
        return jsonify({
            "status": "registrado",
            "message": "Este email ya está registrado."
        }), 200

    # Limpiar códigos anteriores
    try:
        Code.query.filter_by(email=email).delete()
        db.session.commit()
    except Exception: # pylint: disable=broad-exception-caught
        db.session.rollback()

    code_str = str(random.randint(100000, 999999))
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    # Guardar en DB
    new_code = Code(email=email, code=code_str, expires_at=expires_at)
    db.session.add(new_code)
    db.session.commit()

    # USAMOS EL SERVICIO CENTRALIZADO 📧
    if enviar_codigo_verificacion(email, code_str):
        return jsonify({"status": "enviado", "message": "Código enviado"}), 200

    return jsonify({"status": "error", "message": "No se pudo enviar el email"}), 500


@auth_bp.route('/auth/verify-code', methods=['POST'])
def verify_code():
    """Verifica si el código es correcto contra la DB."""
    data = request.json
    email = data.get('email')
    code_input = data.get('code')

    if not email or not code_input:
        return jsonify({"error": "Faltan datos"}), 400

    record = Code.query.filter_by(email=email).first()

    if not record:
        return jsonify({"error": "Código no encontrado o expirado"}), 400

    if record.code != code_input:
        return jsonify({"error": "Código incorrecto"}), 400

    if datetime.utcnow() > record.expires_at:
        return jsonify({"error": "El código ha caducado"}), 400

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

    ident = _validar_identidad(nombre, email, telefono)
    if ident:
        return jsonify({'error': ident}), 400

    # Verificar Código en DB
    record = Code.query.filter_by(email=email).first()
    if not record or record.code != codigo_usuario:
        return jsonify({'error': 'Código de verificación incorrecto'}), 400

    # Verificar existencia
    if (Cliente.query.filter_by(email=email).first() or
            Montador.query.filter_by(email=email).first()):
        return jsonify({'error': 'El usuario ya existe'}), 400

    try:
        # 1. Crear el Montador
        nuevo_montador = Montador(
            email=email,
            nombre=nombre,
            telefono=telefono,
            zona_servicio=zona,
            password_hash=generate_password_hash(password),
            bono_entregado=True  # 🎁 Marcamos que ha recibido el bono
        )

        db.session.add(nuevo_montador)
        # Hacemos commit AQUÍ para asegurar que tenemos el ID
        db.session.commit()

        # 2. ASIGNAR BONO DE FORMA ROBUSTA (Delegado al servicio)
        # Esto crea la wallet si no existe y asigna las gemas con seguridad
        asignar_bono_bienvenida(nuevo_montador.id, 'montador')

        # 3. Limpiar código usado
        db.session.delete(record)
        db.session.commit()

        token = create_access_token(
            identity=str(nuevo_montador.id),
            additional_claims={"rol": "montador"}
        )

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


@auth_bp.route('/cliente/registro', methods=['POST'])
def register_cliente():
    """Registro de cliente: nombre, apellidos, teléfono, email y código."""
    data = request.json or {}
    nombre = data.get('nombre')
    email = data.get('email')
    password = data.get('password')
    telefono = data.get('telefono')
    codigo_usuario = data.get('codigo')

    if not all([nombre, email, password, codigo_usuario]):
        return jsonify({'error': 'Faltan datos obligatorios'}), 400

    ident = _validar_identidad(nombre, email, telefono)
    if ident:
        return jsonify({'error': ident}), 400

    record = Code.query.filter_by(email=email).first()
    if not record or record.code != codigo_usuario:
        return jsonify({'error': 'Código de verificación incorrecto'}), 400

    if (Cliente.query.filter_by(email=email).first() or
            Montador.query.filter_by(email=email).first()):
        return jsonify({'error': 'El usuario ya existe'}), 400

    try:
        nuevo = Cliente(
            email=email,
            nombre=nombre.strip(),
            telefono=telefono,
            password_hash=generate_password_hash(password),
        )
        db.session.add(nuevo)
        db.session.delete(record)
        db.session.commit()
        token = create_access_token(
            identity=str(nuevo.id),
            additional_claims={"rol": "cliente"},
        )
        return jsonify({
            'message': 'Cliente registrado',
            'access_token': token,
            'user': {
                'id': nuevo.id,
                'nombre': nuevo.nombre,
                'email': nuevo.email,
                'tipo': 'cliente',
            },
        }), 201
    except Exception as e:  # pylint: disable=broad-exception-caught
        db.session.rollback()
        print(f"Error Registro Cliente: {e}")
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

    ident = _validar_identidad(nombre, email, telefono)
    if ident:
        return jsonify({'message': ident}), 400

    if (Cliente.query.filter_by(email=email).first() or
            Montador.query.filter_by(email=email).first()):
        return jsonify({'message': 'El email ya está registrado'}), 400

    hashed_pw = generate_password_hash(password)

    try:
        nuevo_usuario = None
        if tipo == 'montador':
            nuevo_usuario = Montador(
                email=email, nombre=nombre, telefono=telefono, password_hash=hashed_pw,
                zona_servicio=data.get('zona', ''),
                bono_entregado=True # 🎁
            )
            db.session.add(nuevo_usuario)
            db.session.commit() # Commit para tener ID

            # ASIGNAR BONO ROBUSTO
            asignar_bono_bienvenida(nuevo_usuario.id, 'montador')

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

        ident = _validar_identidad(nombre, email, telefono)
        if ident:
            return jsonify({"error": ident}), 400

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

        # USAMOS EMAIL GENÉRICO 📧
        enviar_email_generico(
            email,
            "Bienvenido a KIQ",
            f"<h1>Hola {nombre}</h1><p>Tu cuenta y tu presupuesto han sido creados correctamente.</p>"
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
    """Devuelve los datos del usuario logueado."""
    user_id = get_jwt_identity()
    claims = get_jwt()
    role = claims.get("rol", "cliente")

    user = None
    datos_extra = {}

    if role == 'cliente':
        user = Cliente.query.get(int(user_id))
    elif role == 'montador':
        user = Montador.query.get(int(user_id))
        if user:
            # Si la wallet no existe (usuarios antiguos), se crea al vuelo
            # NOTA: Aunque el registro ahora es robusto, mantenemos esto para usuarios legacy.
            saldo = 0
            if user.wallet:
                saldo = user.wallet.saldo
            else:
                # Fallback seguridad usuarios legacy (No damos bono, solo creamos wallet vacía)
                w = Wallet(saldo=0, montador_id=user.id)
                db.session.add(w)
                db.session.commit()
                saldo = 0

            datos_extra = {
                "saldo_gemas": saldo,
                "stripe_account_id": user.stripe_account_id,
                "stripe_boarding_completado": bool(user.stripe_account_id),
                "bono_entregado": user.bono_entregado,
                "bono_visto": user.bono_visto
            }

    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404

    return jsonify({
        "id": user.id,
        "nombre": user.nombre,
        "email": user.email,
        "tipo": role,
        "telefono": getattr(user, 'telefono', ''),
        "foto_url": getattr(user, 'foto_url', None),
        **datos_extra
    }), 200


@auth_bp.route('/perfil', methods=['PUT'])
@jwt_required()
def update_perfil():
    """Actualizar perfil del usuario."""
    current_user_id = get_jwt_identity()
    claims = get_jwt()
    role = claims.get("rol", "cliente")

    usuario = None
    if role == 'montador':
        usuario = Montador.query.get(int(current_user_id))
    else:
        usuario = Cliente.query.get(int(current_user_id))

    if not usuario:
        return jsonify({'message': 'Usuario no encontrado'}), 404

    data = request.json

    if 'nombre' in data:
        usuario.nombre = data['nombre']
    if 'telefono' in data:
        usuario.telefono = data['telefono']
    if 'password' in data and data['password']:
        usuario.password_hash = generate_password_hash(data['password'])

    if role == 'montador' and 'zona_servicio' in data:
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
        # Limpiar códigos previos
        try:
            Code.query.filter_by(email=email).delete()
            db.session.commit()
        except Exception: # pylint: disable=broad-exception-caught
            db.session.rollback()

        code_str = str(random.randint(100000, 999999))
        expires_at = datetime.utcnow() + timedelta(minutes=15)

        new_code = Code(email=email, code=code_str, expires_at=expires_at)
        db.session.add(new_code)
        db.session.commit()

        content = f"""
        <h2>Recuperación KIQ</h2>
        <p>Has solicitado restablecer tu contraseña.</p>
        <p>Tu código de seguridad es:</p>
        <h1 style="color: #6d28d9; letter-spacing: 5px;">{code_str}</h1>
        """
        # USAMOS EMAIL GENÉRICO 📧
        enviar_email_generico(email, "Recuperar Contraseña - KIQ", content)

    # Respondemos siempre 200 por seguridad (para no revelar qué emails existen)
    return jsonify({'message': 'Si el email existe, se ha enviado un código.'}), 200


@auth_bp.route('/auth/reset-password', methods=['POST'])
def reset_password():
    """Cambia la contraseña usando el código."""
    data = request.json
    email = data.get('email')
    code_input = data.get('code')
    new_password = data.get('new_password')

    if not email or not code_input or not new_password:
        return jsonify({'error': 'Faltan datos'}), 400

    # Verificación DB
    record = Code.query.filter_by(email=email).first()
    if not record or record.code != code_input:
        return jsonify({'error': 'Código inválido o expirado'}), 400

    cliente = Cliente.query.filter_by(email=email).first()
    montador = Montador.query.filter_by(email=email).first()

    if cliente:
        cliente.password_hash = generate_password_hash(new_password)
    elif montador:
        montador.password_hash = generate_password_hash(new_password)
    else:
        return jsonify({'error': 'Usuario no encontrado'}), 404

    db.session.delete(record)
    db.session.commit()

    return jsonify({'message': 'Contraseña actualizada con éxito'}), 200


# ==========================================
# 6. UTILIDADES Y ADMIN (ACTUALIZADO: STANDARD AUTH)
# ==========================================

@auth_bp.route('/check-email', methods=['POST'])
def check_email():
    """Verifica si el email existe."""
    email = request.json.get('email')
    if (Cliente.query.filter_by(email=email).first() or
            Montador.query.filter_by(email=email).first()):
        return jsonify({"status": "existente"}), 200
    return jsonify({"status": "nuevo"}), 200

def _admin_secret():
    """Clave del panel. En producción debe vivir en ADMIN_TOKEN (Render)."""
    return os.getenv('ADMIN_TOKEN', 'kiq2025master')


def _validar_admin_token():
    """Acepta JWT de /api/admin/login o el secreto ADMIN_TOKEN."""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
    token = auth_header.split(" ", 1)[1]
    secret = _admin_secret()
    if token and secrets.compare_digest(token, secret):
        return True
    try:
        decoded = decode_token(token)
        return decoded.get('rol') == 'admin'
    except Exception:  # pylint: disable=broad-exception-caught
        return False


@auth_bp.route('/admin/login', methods=['POST'])
def admin_login():
    """El front no lleva la clave: se valida aquí y se devuelve un JWT corto."""
    data = request.get_json(silent=True) or {}
    password = (data.get('password') or '').strip()
    secret = _admin_secret()
    if not password or not secrets.compare_digest(password, secret):
        return jsonify({'error': 'Acceso denegado'}), 401
    token = create_access_token(
        identity='admin',
        additional_claims={'rol': 'admin'},
        expires_delta=timedelta(hours=12),
    )
    return jsonify({'token': token}), 200


@auth_bp.route('/admin/reset-password', methods=['POST'])
def admin_reset_password():
    """El admin define una contraseña nueva para cliente o montador."""
    if not _validar_admin_token():
        return jsonify({'error': 'Acceso denegado. Token inválido.'}), 401

    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    tipo = (data.get('tipo') or '').strip().lower()
    new_password = data.get('new_password') or ''

    if not user_id or tipo not in ('cliente', 'montador'):
        return jsonify({'error': 'Faltan datos'}), 400
    if len(new_password) < 8:
        return jsonify({'error': 'La contraseña debe tener al menos 8 caracteres'}), 400

    user = (
        Montador.query.get(int(user_id)) if tipo == 'montador'
        else Cliente.query.get(int(user_id))
    )
    if not user:
        return jsonify({'error': 'Usuario no encontrado'}), 404

    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    return jsonify({
        'message': 'Contraseña actualizada',
        'email': user.email,
    }), 200

@auth_bp.route('/admin/todos-los-trabajos', methods=['GET'])
def admin_get_todos_los_trabajos():
    """Panel Admin Seguro."""
    # Validación Estándar Bearer Token
    if not _validar_admin_token():
        return jsonify({'error': 'Acceso denegado. Token inválido.'}), 401

    trabajos = Trabajo.query.order_by(Trabajo.fecha_creacion.desc()).all()
    lista_final = []

    for t in trabajos:
        cliente = Cliente.query.get(t.cliente_id)
        montador_nombre = "Sin asignar"
        if t.montador_id:
            m = Montador.query.get(t.montador_id)
            if m:
                montador_nombre = m.nombre

        precio_final = getattr(t, 'precio_calculado', 0)
        if hasattr(t, 'precio_estimado') and t.precio_estimado:
            precio_final = t.precio_estimado

        lista_final.append({
            "id": t.id,
            "fecha": t.fecha_creacion.strftime('%Y-%m-%d %H:%M'),
            "cliente": cliente.nombre if cliente else "Desconocido",
            "email_cliente": cliente.email if cliente else "",
            "telefono_cliente": cliente.telefono if cliente else "",
            "descripcion": t.descripcion,
            "precio": precio_final,
            "montador": montador_nombre,
            "estado": t.estado
        })

    return jsonify(lista_final), 200

@auth_bp.route('/admin/usuarios', methods=['GET'])
def admin_get_usuarios():
    """Obtiene lista combinada de Clientes y Montadores para el Admin."""
    if not _validar_admin_token():
        return jsonify({'error': 'Acceso denegado. Token inválido.'}), 401

    lista_usuarios = []

    # 1. Obtener Montadores y sus Gemas
    montadores = Montador.query.all()
    for m in montadores:
        # Calcular saldo seguro
        saldo_actual = 0
        if m.wallet:
            saldo_actual = m.wallet.saldo
            
        lista_usuarios.append({
            "id": m.id,
            "tipo": "montador",
            "nombre": m.nombre,
            "email": m.email,
            "telefono": m.telefono,
            "zona": m.zona_servicio,
            "saldo": saldo_actual,  # <--- ¡AQUÍ ESTÁ LA CLAVE!
            "fecha": m.fecha_registro.strftime('%Y-%m-%d') if m.fecha_registro else "N/A"
        })

    # 2. Obtener Clientes
    clientes = Cliente.query.all()
    for c in clientes:
        lista_usuarios.append({
            "id": c.id,
            "tipo": "cliente",
            "nombre": c.nombre,
            "email": c.email,
            "telefono": c.telefono,
            "zona": "N/A",
            "saldo": 0, # Clientes no tienen gemas
            "fecha": c.fecha_registro.strftime('%Y-%m-%d') if c.fecha_registro else "N/A"
        })

    return jsonify(lista_usuarios), 200

# ==========================================
# 7. SUBIDA DE FOTO DE PERFIL (NUEVO)
# ==========================================

@auth_bp.route('/perfil/foto', methods=['POST', 'OPTIONS'])
@cross_origin() # Soluciona el error de CORS bloqueado
@jwt_required()
def subir_foto_perfil():
    """Endpoint para actualizar la foto de perfil en Cloudinary."""
    # 1. Responder OK al navegador si pregunta por permisos (OPTIONS)
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    # 2. Validar que llega un archivo
    if 'imagen' not in request.files:
        return jsonify({'error': 'No se envió ninguna imagen'}), 400

    file = request.files['imagen']
    if file.filename == '':
        return jsonify({'error': 'Nombre de archivo vacío'}), 400

    try:
        # 3. Identificar al usuario
        user_id = get_jwt_identity()
        claims = get_jwt()
        role = claims.get("rol", "cliente")

        # 4. Subir a Cloudinary (Tu almacenamiento de imágenes)
        upload_result = cloudinary.uploader.upload(file)
        url_imagen = upload_result['secure_url']

        # 5. Guardar URL en la Base de Datos
        user = None
        if role == 'montador':
            user = Montador.query.get(int(user_id))
        else:
            user = Cliente.query.get(int(user_id))

        if user:
            user.foto_url = url_imagen
            db.session.commit()
            return jsonify({'message': 'Foto actualizada', 'foto_url': url_imagen}), 200

        return jsonify({'error': 'Usuario no encontrado'}), 404

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"❌ Error subida foto: {e}")
        return jsonify({'error': 'Falló la subida de la imagen'}), 500

# ==========================================
# 8. ZONA GOD MODE (SUPER PODERES ADMIN) ⚡
# ==========================================

@auth_bp.route('/admin/asignar-gemas', methods=['POST'])
def admin_god_mode_gems():
    """GOD MODE: Inyectar o quitar gemas a cualquier montador."""
    if not _validar_admin_token():
        return jsonify({'error': 'Acceso denegado.'}), 401

    data = request.json
    montador_id = data.get('montador_id')
    cantidad = data.get('cantidad') # Puede ser positivo (dar) o negativo (quitar)

    try:
        # Nota: Wallet ya está importado arriba para evitar import-outside-toplevel

        montador = Montador.query.get(montador_id)
        if not montador:
            return jsonify({'error': 'Montador no encontrado'}), 404

        if not montador.wallet:
            # Si no tiene wallet, se la creamos
            new_wallet = Wallet(montador_id=montador.id, saldo=0)
            db.session.add(new_wallet)
            db.session.commit()

        # Modificar saldo
        montador.wallet.saldo += int(cantidad)
        db.session.commit()

        return jsonify({
            'message': 'Saldo actualizado',
            'nuevo_saldo': montador.wallet.saldo,
            'montador': montador.nombre
        }), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/admin/borrar-trabajo/<int:job_id>', methods=['DELETE'])
def admin_god_mode_delete_job(job_id):
    """GOD MODE: Borrar un trabajo de la existencia (Historial, Cotización, etc)."""
    if not _validar_admin_token():
        return jsonify({'error': 'Acceso denegado.'}), 401

    try:
        trabajo = Trabajo.query.get(job_id)
        if not trabajo:
            return jsonify({'error': 'Trabajo no existe'}), 404

        # Eliminación dura (HARD DELETE).
        db.session.delete(trabajo)
        db.session.commit()

        return jsonify({
            'message': f'Trabajo {job_id} eliminado del sistema para siempre.'
        }), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/admin/borrar-usuario/<int:target_user_id>/<tipo>', methods=['DELETE'])
def admin_god_mode_delete_user(target_user_id, tipo):
    """GOD MODE: Eliminar un usuario (Cliente o Montador) y sus datos."""
    if not _validar_admin_token():
        return jsonify({'error': 'Acceso denegado.'}), 401

    try:
        user = None
        if tipo == 'montador':
            user = Montador.query.get(target_user_id)
        else:
            user = Cliente.query.get(target_user_id)

        if not user:
            return jsonify({'error': 'Usuario no encontrado'}), 404

        # Al borrar el usuario, se borrarán sus trabajos asociados si hay cascade
        db.session.delete(user)
        db.session.commit()

        return jsonify({'message': f'Usuario {tipo} {target_user_id} eliminado.'}), 200

    except Exception as e: # pylint: disable=broad-exception-caught
        db.session.rollback()
        return jsonify({
            'error': f'No se puede borrar (tiene datos vinculados): {str(e)}'
        }), 500