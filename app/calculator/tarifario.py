"""Tarifario de muebles y constantes de precios."""

PRECIO_MINIMO = 30.0
COSTE_ANCLAJE = 15.0

TARIFARIO = {
    "armario": {
        "keywords": ["armario", "ropero", "placard", "clóset", "pax", "wardrobe", "closet"],
        "precio_base": 90,
        "necesita_anclaje": True,
        "display_name": {"es": "Armario"},
        "reglas_precio": {
            "puerta_extra": 30,
            "suplemento_corredera": 20,
        },
    },
    "canape": {
        "keywords": ["canape", "canapé", "arcón", "cama abatible"],
        "precio_base": 50,
        "necesita_anclaje": False,
        "display_name": {"es": "Canapé Abatible"},
        "reglas_precio": {
            "pequeno": -10,
            "grande": 20,
        },
    },
    "cama": {
        "precio_base": 50,
        "necesita_anclaje": False,
        "keywords": ["cama", "somier", "bed frame", "bed"],
        "display_name": {"es": "Cama"},
        "reglas_precio": {
            "pequeno": -10,
            "grande": 20,
        },
    },
    "comoda": {
        "precio_base": 50,
        "necesita_anclaje": True,
        "keywords": ["cómoda", "cajonera", "dresser", "chest of drawers"],
        "display_name": {"es": "Cómoda"},
    },
    "mesita_noche": {
        "precio_base": 30,
        "necesita_anclaje": False,
        "keywords": ["mesita", "mesilla", "nightstand", "bedside table"],
        "display_name": {"es": "Mesita de Noche"},
    },
    "sofa": {
        "precio_base": 65,
        "necesita_anclaje": False,
        "keywords": ["sofa", "sofá", "sillon", "couch"],
        "display_name": {"es": "Sofá"},
    },
    "mueble_tv": {
        "precio_base": 50,
        "necesita_anclaje": True,
        "keywords": ["mueble tv", "mesa tv", "entertainment center", "tv stand"],
        "display_name": {"es": "Mueble TV"},
    },
    "escritorio": {
        "precio_base": 45,
        "necesita_anclaje": False,
        "keywords": ["escritorio", "mesa estudio", "desk"],
        "display_name": {"es": "Escritorio"},
    },
    "silla": {
        "precio_base": 15,
        "necesita_anclaje": False,
        "keywords": ["silla", "taburete", "chair"],
        "display_name": {"es": "Silla"},
    },
    "vitrina": {
        "precio_base": 99,
        "necesita_anclaje": True,
        "keywords": ["vitrina", "aparador", "display cabinet", "cabinet"],
        "display_name": {"es": "Vitrina"},
    },
    "mesa_comedor": {
        "precio_base": 49,
        "necesita_anclaje": False,
        "keywords": [
            "mesa comedor",
            "mesa de comedor",
            "dining table",
            "mesas",
            "mesa",
            "table",
        ],
        "display_name": {"es": "Mesa"},
    },
}
