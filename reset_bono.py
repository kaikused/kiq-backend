from app import create_app
from app.extensions import db
from app.models import Montador
from sqlalchemy import text

app = create_app()

with app.app_context():
    email = input("Introduce el email del montador a resetear: ")
    montador = Montador.query.filter_by(email=email).first()
    
    if montador:
        montador.bono_visto = False
        db.session.commit()
        print(f"✅ ¡Listo! El bono se ha reseteado para {montador.nombre}.")
        print("   Ahora volverá a ver el modal al entrar.")
    else:
        print("❌ Usuario no encontrado.")