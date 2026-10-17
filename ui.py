"""
Piezas de interfaz reutilizables del portal.

Aquí están las funciones que pintan las cosas comunes: la barra lateral, la
portada, las tarjetas de tarea y la guía de pasos. Están aparte de app.py para
que el archivo principal se centre en el flujo y no en el CSS.

DECISIONES DE DISEÑO, Y POR QUÉ
===============================
1. **Sin jerga en la superficie.** El usuario ve «Revisar facturas», no
   «Extracción de información con Content Understanding». El nombre técnico
   aparece en la guía de ayuda, para quien quiera saberlo, no en el camino.

2. **Una sola decisión por pantalla.** Quien entra elige quién es, y a partir
   de ahí solo ve SUS tareas. Una lista de seis pestañas técnicas obliga al
   usuario a decidir algo que no sabe: qué servicio de Azure necesita.

3. **Los pasos siempre visibles.** Cada tarea muestra en qué consiste antes de
   empezar. Es el «explainability» aplicado a la interfaz: el usuario sabe qué
   va a pasar y qué tiene que hacer.

4. **Voz y móvil no son un extra.** El enunciado pide que gente de bodega, sin
   computadora, pueda usarlo. Por eso hay un botón de voz grande y las tarjetas
   se apilan en una columna cuando la pantalla es estrecha.
"""

from __future__ import annotations

import streamlit as st

from portal import PERSONAS, TAREAS, TAREAS_POR_CLAVE, Persona, Tarea


# =============================================================================
# Estilos
#
# Un poco de CSS para que la app se vea como un producto y no como un cuaderno
# de pruebas: tarjetas con borde suave, tipografía más legible en móvil y
# botones con área táctil suficiente.
# =============================================================================

CSS = """
<style>
/* Tarjeta de tarea: área táctil amplia, legible en celular. */
.rc-tarjeta {
    border: 1px solid rgba(49, 51, 63, 0.16);
    border-radius: 14px;
    padding: 18px 18px 14px 18px;
    background: #ffffff;
    height: 100%;
    transition: border-color .15s ease, box-shadow .15s ease;
}
.rc-tarjeta:hover {
    border-color: rgba(49, 51, 63, 0.34);
    box-shadow: 0 2px 10px rgba(49, 51, 63, 0.08);
}
.rc-tarjeta h4 {
    margin: 0 0 6px 0;
    font-size: 1.06rem;
    line-height: 1.3;
}
.rc-tarjeta p {
    margin: 0;
    font-size: 0.92rem;
    color: rgba(49, 51, 63, 0.78);
    line-height: 1.45;
}
.rc-etiqueta {
    display: inline-block;
    font-size: 0.72rem;
    letter-spacing: .03em;
    text-transform: uppercase;
    color: rgba(49, 51, 63, 0.6);
    margin-bottom: 10px;
}

/* Portada: titular grande y legible, sin adornos. */
.rc-portada h1 {
    font-size: 2.1rem;
    margin-bottom: .3rem;
    line-height: 1.15;
}
.rc-portada p {
    font-size: 1.02rem;
    color: rgba(49, 51, 63, 0.82);
    margin-top: 0;
}

/* Cifra destacada de impacto. */
.rc-cifra {
    font-size: 1.9rem;
    font-weight: 700;
    line-height: 1.1;
    margin: 0;
}
.rc-cifra-etiqueta {
    font-size: .82rem;
    color: rgba(49, 51, 63, 0.7);
    margin: 0;
}

/* Pasos de una tarea. */
.rc-paso {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    margin-bottom: 10px;
}
.rc-paso-num {
    flex: 0 0 26px;
    height: 26px;
    border-radius: 50%;
    background: rgba(49, 51, 63, 0.08);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: .82rem;
    font-weight: 600;
}
.rc-paso-txt { font-size: .94rem; line-height: 1.45; padding-top: 3px; }

/* En pantallas estrechas, menos relleno y botones más altos. */
@media (max-width: 640px) {
    .rc-tarjeta { padding: 14px; border-radius: 12px; }
    .rc-portada h1 { font-size: 1.6rem; }
    .rc-cifra { font-size: 1.5rem; }
}
</style>
"""


def aplicar_estilos() -> None:
    """Inyecta el CSS una sola vez."""
    st.markdown(CSS, unsafe_allow_html=True)


# =============================================================================
# Tarjetas
# =============================================================================

def tarjeta_tarea(tarea: Tarea, persona: Persona | None = None) -> None:
    """Pinta la tarjeta descriptiva de una tarea (sin el botón)."""
    contexto = ""
    if persona is not None:
        contexto = f" · Para {persona.nombre}"
    st.markdown(
        f"""
        <div class="rc-tarjeta">
          <span class="rc-etiqueta">{tarea.emoji} {tarea.aptitud.split('·')[0].strip()}</span>
          <h4>{tarea.titulo}</h4>
          <p>{tarea.para_que}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def pasos_tarea(tarea: Tarea) -> None:
    """Muestra los pasos de la tarea, numerados y legibles."""
    if not tarea.pasos:
        return
    piezas = []
    for i, paso in enumerate(tarea.pasos, 1):
        piezas.append(
            f'<div class="rc-paso">'
            f'<div class="rc-paso-num">{i}</div>'
            f'<div class="rc-paso-txt">{paso}</div>'
            f'</div>'
        )
    st.markdown("".join(piezas), unsafe_allow_html=True)


def cifra(valor: str, etiqueta: str) -> None:
    """Cifra destacada con su etiqueta debajo."""
    st.markdown(
        f'<p class="rc-cifra">{valor}</p>'
        f'<p class="rc-cifra-etiqueta">{etiqueta}</p>',
        unsafe_allow_html=True,
    )


# =============================================================================
# Navegación
# =============================================================================

def selector_de_persona() -> str | None:
    """
    Pregunta quién eres y devuelve la clave de la persona.

    Devuelve None si el usuario prefiere ver todo el portal. Es importante que
    elegir persona sea OPCIONAL: un revisor que entra por primera vez no es
    ninguna de las cinco personas, y no se le debe obligar a fingir que lo es.
    """
    opciones = ["Ver todo el portal"] + [
        f"{p.emoji} {p.nombre} — {p.puesto}" for p in PERSONAS
    ]
    eleccion = st.radio(
        "¿Quién eres?",
        opciones,
        index=0,
        horizontal=True,
        label_visibility="collapsed",
        key="selector_persona",
        help=(
            "Elige tu puesto y verás solo las tareas que te sirven. "
            "Si solo estás explorando, déjalo en «Ver todo el portal»."
        ),
    )

    if eleccion == "Ver todo el portal":
        return None
    for p in PERSONAS:
        if eleccion == f"{p.emoji} {p.nombre} — {p.puesto}":
            return p.clave
    return None


def panel_persona(persona: Persona) -> None:
    """Ficha con la preocupación y la definición de éxito de la persona."""
    st.markdown(f"### {persona.emoji} {persona.nombre}")
    st.caption(f"{persona.puesto}")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Lo que le preocupa**")
        st.write(persona.preocupacion)
    with c2:
        st.markdown("**Para esta persona, éxito es**")
        st.write(persona.exito)

    if persona.contexto:
        st.info(persona.contexto)


# =============================================================================
# Avisos de estado
# =============================================================================

def aviso_modo_demo(modo_demo_activo: bool) -> None:
    """
    Aviso de que los datos son de ejemplo.

    Recibe el estado como parámetro en lugar de consultarlo: si importara la
    aplicación para preguntárselo, se crearía una dependencia circular
    (app -> ui -> app). Quien llama ya sabe si el modo demo está activo.
    """
    if modo_demo_activo:
        st.warning(
            "🔶 **Estás viendo datos de ejemplo.** La aplicación no está "
            "conectada a Azure en este momento, así que las respuestas no "
            "vienen de los servicios reales."
        )


def aviso_ia() -> None:
    """
    Recordatorio de que se habla con una IA. Es el principio de Transparencia
    aplicado en la interfaz, no solo en el documento.
    """
    st.caption(
        "🤖 **Estás hablando con una IA**, no con una persona. Cada respuesta "
        "indica de qué documento salió. Si algo no está en los documentos "
        "oficiales de Río Claro, la IA debe decir que no lo sabe."
    )


def chip_estado(texto: str, tipo: str = "info") -> None:
    """Etiqueta corta de estado (info, exito, aviso, error)."""
    iconos = {"info": "ℹ️", "exito": "✅", "aviso": "⚠️", "error": "❌"}
    funcion = {
        "info": st.info,
        "exito": st.success,
        "aviso": st.warning,
        "error": st.error,
    }.get(tipo, st.info)
    funcion(f"{iconos.get(tipo, 'ℹ️')} {texto}")
