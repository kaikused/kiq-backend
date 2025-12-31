"""
Motor de procesamiento de lenguaje natural (NLP) para Kiq Montajes.
Gestiona la carga eficiente del modelo spaCy mediante patrón Singleton.
"""
import logging
import spacy

# Configuración de logs
logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

# Usamos un diccionario mutable para mantener la instancia en memoria
# y evitar el uso de 'global' (W0603).
_NLP_CACHE = {}

def get_nlp_model():
    """
    Patrón Singleton: Carga el modelo spaCy solo si no existe ya en memoria.
    Devuelve la instancia del modelo 'es_core_news_sm'.
    """
    # Si ya existe en caché, lo devolvemos inmediatamente
    if "model" in _NLP_CACHE:
        return _NLP_CACHE["model"]

    LOGGER.info("⏳ Cargando modelo de spaCy en memoria RAM... (Primera ejecución)")
    try:
        # Carga optimizada: deshabilitamos componentes que no usamos (parser, ner)
        # para que sea más rápido y consuma menos memoria.
        model = spacy.load("es_core_news_sm", disable=["parser", "ner"])
        _NLP_CACHE["model"] = model
        LOGGER.info("✅ Modelo spaCy cargado y listo.")
        return model

    except OSError:
        LOGGER.error("❌ Error CRÍTICO: No se encontró el modelo 'es_core_news_sm'.")
        LOGGER.error(
            "Ejecuta en tu terminal: python -m spacy download es_core_news_sm"
        )
        return None
    