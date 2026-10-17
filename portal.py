"""
Personas y tareas del portal de Río Claro.

POR QUÉ EXISTE ESTE ARCHIVO
===========================
El enunciado insiste en que la app la va a usar gente que no tiene formación
técnica:

    «Sin personal técnico: la solución debe poder usarla gente de bodega y
     ventas, algunos solo desde el celular o por voz.»

La primera versión del portal estaba organizada por TECNOLOGÍA: pestañas
llamadas «Asistente», «Facturas», «Voz y visión», «IA responsable». Eso es útil
para demostrar el examen, pero un jefe de bodega no piensa en «cargas de
trabajo de Azure»: piensa «necesito saber cuánto cloro queda».

Aquí se define el portal en el idioma del usuario:
  * quiénes son las personas del caso (los cinco del enunciado),
  * qué necesita cada una,
  * qué tarea resuelve su problema,
  * cómo se llama esa tarea en palabras normales.

Las claves técnicas de cada tarea viven en TAREAS, no en la interfaz, así que
la app puede nombrar las cosas en lenguaje llano sin perder trazabilidad con
las aptitudes del examen.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Persona:
    """Una persona del caso, tal como la describe el enunciado."""

    clave: str
    nombre: str
    puesto: str
    emoji: str
    # Lo que le preocupa, en sus palabras.
    preocupacion: str
    # Cómo se ve el éxito para esta persona (literal del enunciado).
    exito: str
    # Qué tareas del portal le sirven.
    tareas: tuple[str, ...]
    # Nota de uso: aclara cómo trabaja esta persona.
    contexto: str = ""


@dataclass(frozen=True)
class Tarea:
    """Una tarea concreta que el usuario puede hacer en el portal."""

    clave: str
    titulo: str
    # Descripción para el usuario, en lenguaje llano. Sin nombres de servicios.
    para_que: str
    emoji: str
    # Aptitud del examen que se practica con ella (trazabilidad, no interfaz).
    aptitud: str
    # Pasos que sigue el usuario, para la guía visual.
    pasos: tuple[str, ...] = ()
    # Verbo de acción para el botón principal.
    accion: str = "Abrir"


# =============================================================================
# Personas del caso (sección 5 del enunciado)
# =============================================================================

PERSONAS: tuple[Persona, ...] = (
    Persona(
        clave="ernesto",
        nombre="Don Ernesto",
        puesto="Director general",
        emoji="👔",
        preocupacion="Perder clientes grandes y no saber cuánto vende cada sucursal.",
        exito="Un reporte de ventas en el que las 5 sucursales coincidan "
              "y un piloto que cueste lo previsto.",
        tareas=("reporte", "costos"),
        contexto="Necesita cifras que cuadren entre sucursales, no más hojas de cálculo.",
    ),
    Persona(
        clave="laura",
        nombre="Laura",
        puesto="Cuentas por pagar",
        emoji="🧾",
        preocupacion="Que la IA se equivoque con dinero o que la reemplace.",
        exito="Pasar de ~12 horas semanales de captura a menos de 2, revisando "
              "solo los casos dudosos, y cero pagos duplicados.",
        tareas=("facturas",),
        contexto="Hoy captura facturas a mano 12 horas por semana y se equivoca "
                 "en 1 de cada 20.",
    ),
    Persona(
        clave="mariana",
        nombre="Mariana",
        puesto="Gerente de sucursal León",
        emoji="📢",
        preocupacion="Clientes molestos que llaman y nadie les da seguimiento.",
        exito="Responder a cualquier cliente en menos de 15 minutos, sin importar "
              "de qué sucursal salió el pedido.",
        tareas=("quejas",),
        contexto="Recibe llamadas de clientes de cualquier sucursal.",
    ),
    Persona(
        clave="tono",
        nombre="Toño",
        puesto="Jefe de bodega",
        emoji="🎙️",
        preocupacion="No usa computadora; todo lo resuelve por teléfono.",
        exito="Preguntar por voz desde el celular «¿cuánto cloro de litro nos "
              "queda?» y obtener una respuesta correcta.",
        tareas=("asistente", "voz"),
        contexto="Trabaja desde el celular, con las manos ocupadas. La voz no es "
                 "un extra: es su única forma de consultar.",
    ),
    Persona(
        clave="carlos",
        nombre="Carlos",
        puesto="Soporte y sistemas",
        emoji="🛡️",
        preocupacion="Ser el único responsable de algo que no conoce.",
        exito="Accesos por persona (no contraseñas compartidas), secretos "
              "guardados y un sistema que pueda apagar si algo falla.",
        tareas=("seguridad", "responsable"),
        contexto="Necesita ver el estado del sistema y poder apagarlo.",
    ),
)


# =============================================================================
# Tareas del portal
#
# El TÍTULO no menciona servicios de Azure: el usuario no debería tener que
# saber que existe «Content Understanding» para subir una factura. La aptitud
# del examen queda anotada aparte, en `aptitud`.
# =============================================================================

TAREAS: tuple[Tarea, ...] = (
    Tarea(
        clave="asistente",
        titulo="Preguntar algo",
        para_que="Consultar inventario, pedidos o políticas y recibir una "
                 "respuesta con la fuente de donde salió.",
        emoji="💬",
        aptitud="IA generativa · Agentes · Análisis de texto",
        pasos=(
            "Escribe la pregunta (o dictala con el micrófono).",
            "La IA busca en los documentos oficiales de Río Claro.",
            "Recibes la respuesta y de qué archivo salió.",
        ),
        accion="Preguntar",
    ),
    Tarea(
        clave="voz",
        titulo="Hablar por voz",
        para_que="Preguntar en español hablando, y escuchar la respuesta. "
                 "Pensado para trabajar desde el celular.",
        emoji="🎙️",
        aptitud="Voz (Speech a texto y texto a voz) · Inclusión",
        pasos=(
            "Pulsa el micrófono y habla.",
            "Tu pregunta se convierte en texto.",
            "La respuesta se lee en voz alta en español de México.",
        ),
        accion="Hablar",
    ),
    Tarea(
        clave="facturas",
        titulo="Revisar facturas",
        para_que="Subir una factura en PDF o foto, ver qué datos se extrajeron "
                 "y decidir si se paga. El sistema detecta cobros duplicados.",
        emoji="📄",
        aptitud="Extracción de información (Content Understanding) · Visión · "
                "Confiabilidad · Rendición de cuentas",
        pasos=(
            "Sube la factura (PDF o foto del celular).",
            "El sistema lee proveedor, folio, fecha e importe.",
            "Si algo no es legible, lo manda a revisión y no inventa cifras.",
            "Tú apruebas o rechazas el pago.",
        ),
        accion="Revisar facturas",
    ),
    Tarea(
        clave="quejas",
        titulo="Atender quejas",
        para_que="Registrar la queja de un cliente y ver el historial completo, "
                 "sin importar de qué sucursal haya salido.",
        emoji="📢",
        aptitud="Análisis de texto (Language) · Equidad · SLA",
        pasos=(
            "Registra lo que dijo el cliente.",
            "El sistema mide el sentimiento y detecta el tema.",
            "Ves el historial del cliente y el plazo de respuesta.",
        ),
        accion="Ver quejas",
    ),
    Tarea(
        clave="reporte",
        titulo="Ver el reporte de ventas",
        para_que="Las ventas de las 5 sucursales con cifras que coinciden, "
                 "por producto y por sucursal.",
        emoji="📈",
        aptitud="Equidad · Fuente única de verdad",
        pasos=(
            "Elige el periodo y la sucursal.",
            "Compara las cifras de las 5 sucursales.",
            "Descarga el reporte para la dirección.",
        ),
        accion="Ver reporte",
    ),
    Tarea(
        clave="costos",
        titulo="Entender el costo",
        para_que="Cuánto cuesta el piloto al mes y cómo se apaga cuando no se "
                 "usa, para no gastar de más.",
        emoji="💰",
        aptitud="Justificación del piloto (restricción del enunciado)",
    ),
    Tarea(
        clave="seguridad",
        titulo="Comprobar el sistema",
        para_que="Ver si la conexión con Azure funciona, si los secretos están "
                 "protegidos y quién tiene acceso.",
        emoji="🛡️",
        aptitud="Privacidad y seguridad (Entra ID, Key Vault, identidad "
                "administrada)",
        accion="Comprobar",
    ),
    Tarea(
        clave="responsable",
        titulo="Cómo usamos la IA",
        para_que="Los seis compromisos de IA responsable del proyecto, cada uno "
                 "con la parte de la app que lo demuestra.",
        emoji="✅",
        aptitud="IA responsable (sección 4 del enunciado)",
    ),
)

TAREAS_POR_CLAVE = {t.clave: t for t in TAREAS}
PERSONAS_POR_CLAVE = {p.clave: p for p in PERSONAS}


# =============================================================================
# Frases para la portada
# =============================================================================

# Las tres preguntas más frecuentes, con la tarea que las resuelve. Sirven para
# que quien entra por primera vez sepa de inmediato por dónde empezar.
ACCESOS_RAPIDOS: tuple[tuple[str, str, str], ...] = (
    ("¿Cuánto cloro de litro nos queda?", "asistente",
     "Inventario y pedidos de las 5 sucursales"),
    ("¿Me pagaron dos veces esta factura?", "facturas",
     "Detecta cobros duplicados antes de pagar"),
    ("¿Qué pasó con el pedido PED-501?", "asistente",
     "Estado del pedido y sucursal que lo atiende"),
)


# =============================================================================
# Métricas de impacto
#
# Los números salen del enunciado, no de una invención: Laura tarda 12 horas
# semanales y se equivoca en 1 de cada 20 facturas; el objetivo es bajar de
# 2 horas. La app mide lo que de verdad pasó en la sesión y lo compara con la
# línea base para que el usuario vea el ahorro, no una promesa.
# =============================================================================

LINEA_BASE = {
    # Sección 2 del enunciado: «le toma unas 12 horas a la semana».
    "horas_semana_captura": 12.0,
    # «se equivoca en cerca de 1 de cada 20».
    "tasa_error_captura": 1 / 20,
    # Sección 5: Mariana quiere responder en menos de 15 minutos.
    "sla_minutos": 15,
}

# Minutos que se estiman por factura revisada con la app. La cuenta es
# conservadora: se compara contra la captura manual completa (proveedor, fecha,
# total) que el enunciado sitúa en unas 12 horas para el volumen semanal.
MINUTOS_AHORRADOS_POR_FACTURA = 6.0


def tareas_de(persona_clave: str) -> list[Tarea]:
    """Tareas que le sirven a una persona, en el orden en que las necesita."""
    persona = PERSONAS_POR_CLAVE.get(persona_clave)
    if persona is None:
        return []
    return [TAREAS_POR_CLAVE[c] for c in persona.tareas if c in TAREAS_POR_CLAVE]
