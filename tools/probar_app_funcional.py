"""
Prueba funcional de la aplicación, de extremo a extremo y sin Azure.

`verificar_todo.py` comprueba que la aplicación ARRANCA. Esto comprueba que
FUNCIONA: abre la app en un navegador real, activa el modo demostración, hace
clic en los botones de cada pestaña y verifica lo que aparece en pantalla.

Es la única verificación que detecta errores de tiempo de ejecución dentro de
las pestañas (un fallo en el manejador de un botón, una tabla mal construida,
una excepción que solo se dispara al pulsar), que ni la compilación ni el
endpoint de salud pueden ver.

Funciona sin credenciales de Azure porque activa el interruptor "Forzar modo
DEMO", que es justo el modo en que el evaluador podría ver la aplicación.

Uso:
    python tools/probar_app_funcional.py
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

from capturar_pantallas import Navegador, encontrar_navegador  # noqa: E402

VERDE, ROJO, AMARILLO, GRIS, CIAN, NEGRITA, FIN = (
    "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[96m",
    "\033[1m", "\033[0m",
)

_ok = 0
_fallo = 0
_errores_vistos: list[str] = []


def revisar(titulo: str, condicion: bool, detalle: str = "") -> None:
    global _ok, _fallo
    if condicion:
        _ok += 1
        print(f"  {VERDE}OK{FIN}    {titulo}")
    else:
        _fallo += 1
        print(f"  {ROJO}FALLA{FIN} {titulo}")
    if detalle:
        for l in str(detalle).splitlines()[:6]:
            print(f"        {GRIS}{l}{FIN}")


def seccion(t: str) -> None:
    print(f"\n{AMARILLO}{t}{FIN}")


# ---------------------------------------------------------------------------
# Utilidades de interacción con la página
# ---------------------------------------------------------------------------

# Streamlit envuelve una excepción en este contenedor. Es la señal más fiable
# de que algo falló en el código de la app al interactuar.
JS_EXCEPCIONES = """
(() => {
  const nodos = document.querySelectorAll(
    '[data-testid="stException"], .stException, [data-testid="stExceptionMessage"]'
  );
  return Array.from(nodos).map(n => (n.innerText || '').slice(0, 400));
})()
"""

# Alertas de Streamlit: st.error, st.warning, st.info, st.success
JS_ALERTAS = """
(() => {
  const nodos = document.querySelectorAll('[data-testid="stAlert"]');
  return Array.from(nodos).map(n => {
    const txt = (n.innerText || '').replace(/\\s+/g,' ').trim();
    return txt.slice(0, 300);
  });
})()
"""

JS_TEXTO = "(document.body ? document.body.innerText : '')"


def _sin_emoji(s: str) -> str:
    """Quita emojis y símbolos para poder comparar etiquetas de forma estable."""
    return re.sub(r"[^\w\s.:\-áéíóúñÁÉÍÓÚÑ]", "", s or "").strip()


def clic_texto(nav: Navegador, texto: str, etiqueta: str) -> bool:
    """
    Hace clic en el control cuyo texto contenga `texto`.

    TRES DETALLES QUE COSTARON UN DIAGNÓSTICO CADA UNO:

    1. Las pestañas de Streamlit (st.tabs) NO son elementos <button>: se
       renderizan como <p role="tab"> dentro de data-baseweb="tab-list".
    2. Las etiquetas llevan emoji ("🧾 2. Facturas"), así que comparar contra
       "2. Facturas" de forma literal falla. Por eso se comparan sin emojis.
    3. Las casillas (st.checkbox) y los encabezados de expander (st.expander)
       tampoco son <button>: son <label> y <summary> respectivamente.

    Si no se cubren los tres casos, la prueba falla por su propia culpa y no
    por un defecto de la aplicación, que es lo que ocurrió las dos primeras
    veces.
    """
    import json as _json

    expresion = """
    (() => {
      const buscar = %s;
      const limpiar = s => (s || '')
          .replace(/[^\\w\\s.:\\-áéíóúñÁÉÍÓÚÑ]/g, '')
          .replace(/\\s+/g, ' ')
          .trim();
      const objetivoBuscado = limpiar(buscar);
      const visibles = el => !!(el.offsetWidth || el.offsetHeight ||
                                el.getClientRects().length);

      // Se cubren los cuatro tipos de control interactivo de Streamlit.
      const selectores = [
        'button',                 // st.button
        '[role="tab"]',           // st.tabs
        'summary',                // st.expander (cabecera)
        'label',                  // st.checkbox, st.radio
      ];
      const candidatos = [];
      for (const sel of selectores) {
          for (const el of document.querySelectorAll(sel)) {
              if (visibles(el)) candidatos.push(el);
          }
      }

      let objetivo = candidatos.find(el => limpiar(el.innerText) === objetivoBuscado);
      if (!objetivo) {
          objetivo = candidatos.find(el => limpiar(el.innerText).includes(objetivoBuscado));
      }
      if (!objetivo) return false;

      // En un <label> o un <summary>, lo que recibe el clic es el control
      // interno o el propio elemento resumen.
      const aClicar = objetivo.querySelector('input[type="checkbox"]') || objetivo;
      if (aClicar.disabled) return false;

      objetivo.scrollIntoView({block: 'center'});
      aClicar.click();
      return true;
    })()
    """ % _json.dumps(texto)
    return bool(nav.evaluar(expresion))


def modo_demo_activo(nav: Navegador) -> bool:
    """
    Comprueba el ESTADO de la casilla, no el texto.

    Verificar el aviso en pantalla no basta: si el clic no ocurrió, el aviso
    no aparece pero tampoco se sabe si el modo demo está activo o no. Esto se
    consulta directamente al DOM.
    """
    return bool(nav.evaluar("""
    (() => {
      const cajas = document.querySelectorAll('input[type="checkbox"]');
      for (const c of cajas) {
          if (c.checked) return true;
      }
      return false;
    })()
    """))


def _abrir_opciones_avanzadas(nav: Navegador) -> bool:
    """
    Abre el desplegable «Opciones avanzadas» de la barra lateral.

    La casilla de datos de ejemplo ya no está a la vista: se escondió dentro de
    un desplegable porque un usuario normal no necesita verla, y en el celular
    ocupaba espacio útil. Las pruebas tienen que abrirlo antes de pulsarla.
    """
    if nav.evaluar(
        "(() => { const d = document.querySelectorAll('details'); "
        "for (const x of d) { if ((x.innerText||'').includes('Opciones avanzadas')) "
        "{ if (!x.open) { x.open = true; } return true; } } return false; })()"
    ):
        esperar_quieto(nav)
        return True
    # Respaldo: pulsar el resumen del desplegable.
    clic_texto(nav, "Opciones avanzadas", "opciones avanzadas")
    esperar_quieto(nav)
    return True


def desactivar_modo_demo(nav: Navegador) -> bool:
    """
    Desmarca la casilla 'Usar datos de ejemplo' si está marcada.

    Hace falta para generar las capturas de entrega con datos REALES de Azure.
    El generador de capturas activaba el modo demo siempre, así que las
    imágenes mostraban datos de ejemplo aunque hubiera credenciales
    configuradas: el documento de entrega acababa evidenciando el modo
    demostración, justo lo contrario de lo que pide el enunciado.

    Devuelve True si al terminar el modo demo está desactivado (ya lo estaba o
    se desmarcó correctamente).
    """
    if not modo_demo_activo(nav):
        return True

    _abrir_opciones_avanzadas(nav)

    # Se pulsa la etiqueta de la casilla. `forzar_demo` es la clave del widget.
    if not clic_texto(nav, "Usar datos de ejemplo", "casilla de ejemplo"):
        return False

    # Streamlit puede tardar un ciclo en reflejar el cambio de estado.
    for _ in range(12):
        if not modo_demo_activo(nav):
            return True
        time.sleep(0.4)
    return False


def azure_confirmado(nav: Navegador) -> bool:
    """
    ¿La aplicación confirma que va a usar los servicios de Azure de verdad?

    Comprobar solo que la casilla de modo demo esté desmarcada NO basta: si las
    credenciales fueran inválidas, la casilla seguiría bien y las capturas
    saldrían con datos de ejemplo sin que nadie lo notara.

    CÓMO SE COMPRUEBA, Y POR QUÉ ASÍ
    --------------------------------
    La barra lateral marca cada servicio con ⏳ (configurado) o ⚠️ (falta la
    credencial). La comprobación DEBE mirar solo las LÍNEAS DE SERVICIO, porque
    la leyenda de la barra lateral contiene la frase «falta la credencial»:

        ⏳ = configurado · ⚠️ = falta la credencial

    Buscar esa frase en todo el texto daba siempre «no confirmado», incluso con
    todo correctamente configurado: la leyenda se saboteba a sí misma. Es el
    mismo error que ya apareció antes con los comentarios del código, donde un
    verificador encontraba la explicación de por qué algo NO se usa y lo tomaba
    como si se usara.
    """
    barra = nav.evaluar(
        "(() => { const s = document.querySelector("
        "'section[data-testid=\"stSidebar\"]'); return s ? s.innerText : ''; })()"
    ) or ""

    if "datos de ejemplo" in barra.lower():
        return False

    # Solo las líneas de servicio: las que empiezan por ⏳ o ⚠️ y NO son la
    # leyenda (la leyenda contiene «=»).
    servicios = []
    for linea in barra.splitlines():
        limpia = linea.strip()
        if not (limpia.startswith("⏳") or limpia.startswith("⚠️")):
            continue
        if "=" in limpia:          # es la leyenda, no un servicio
            continue
        servicios.append(limpia)

    if not servicios:
        return False
    return all(s.startswith("⏳") for s in servicios)


def activar_modo_demo(nav: Navegador) -> bool:
    """Activa la casilla 'Usar datos de ejemplo' y confirma que quedó marcada."""
    _abrir_opciones_avanzadas(nav)
    if not clic_texto(nav, "Usar datos de ejemplo", "casilla de ejemplo"):
        return False
    esperar_quieto(nav)
    # Reintento: Streamlit puede tardar un ciclo en reflejar el estado.
    for _ in range(10):
        if modo_demo_activo(nav):
            return True
        time.sleep(0.4)
    return False


# Mapa de la numeración antigua (pestañas) a las tareas del portal nuevo.
# El portal se organiza por tarea, no por servicio de Azure, así que las pruebas
# navegan por el nombre de la tarea. Se mantiene la numeración para no reescribir
# las 37 comprobaciones, pero cada número apunta ahora a una tarea.
TAREA_POR_NUMERO = {
    1: "Preguntar algo",
    2: "Revisar facturas",
    3: "Atender quejas",
    4: "Hablar por voz",
    5: "Ver el reporte de ventas",
    6: "Cómo usamos la IA",
}


def abrir_tarea(nav: Navegador, titulo: str) -> bool:
    """
    Abre una tarea del portal por su título, usando la barra de navegación.

    El portal nuevo no usa pestañas: usa un selector de tareas (st.pills), que
    en el DOM son botones con `role="tab"` pero sin el atributo de pestaña
    clásico. Se busca por el texto, que es más estable que la posición: si
    mañana se añade una tarea, la posición de las demás cambia y las pruebas
    por índice fallarían sin motivo.
    """
    import json as _json

    expresion = """
    (() => {
      const objetivo = %s;
      const candidatos = Array.from(document.querySelectorAll('button'))
          .filter(el => !!(el.offsetWidth || el.offsetHeight));
      for (const c of candidatos) {
          const t = (c.innerText || '').replace(/\\s+/g, ' ').trim();
          if (t.includes(objetivo)) {
              c.scrollIntoView({block: 'center'});
              c.click();
              return true;
          }
      }
      return false;
    })()
    """ % _json.dumps(titulo)
    if not nav.evaluar(expresion):
        return False

    # Streamlit reejecuta la app: hay que esperar a que el contenido cambie.
    esperar_quieto(nav)
    return True


def cambiar_pestana(nav: Navegador, numero: int) -> bool:
    """
    Cambia a la pantalla indicada por su número y confirma que el cambio ocurrió.

    NOTA: la app ya no usa pestañas técnicas, sino tareas. Esta función conserva
    la numeración antigua y la traduce a la tarea correspondiente, para que las
    comprobaciones existentes sigan siendo válidas y no haya que reescribirlas.
    """
    titulo = TAREA_POR_NUMERO.get(numero)
    if titulo is None:
        return False
    return abrir_tarea(nav, titulo)


def _cambiar_pestana_dom(nav: Navegador, numero: int) -> bool:
    """Versión antigua, por índice de pestaña. Se conserva por referencia."""
    import json as _json

    expresion = """
    (() => {
      const botones = Array.from(document.querySelectorAll('[role="tab"]'))
          .filter(el => !!(el.offsetWidth || el.offsetHeight));
      const objetivo = botones[%d];
      if (!objetivo) return false;
      objetivo.scrollIntoView({block: 'center'});
      objetivo.click();
      return true;
    })()
    """ % (numero - 1)
    if not nav.evaluar(expresion):
        return False

    # Confirmar que la pestaña quedó seleccionada
    inicio = time.time()
    while time.time() - inicio < 20:
        seleccionada = nav.evaluar(
            """
            (() => {
              const b = Array.from(document.querySelectorAll('[role="tab"]'))
                  .filter(el => !!(el.offsetWidth || el.offsetHeight));
              const t = b[%d];
              return t ? t.getAttribute('aria-selected') : null;
            })()
            """
            % (numero - 1)
        )
        if seleccionada == "true":
            return True
        time.sleep(0.4)
    return False


def esperar_quieto(nav: Navegador, timeout: float = 40.0) -> None:
    """
    Espera a que Streamlit termine de reejecutar la aplicación.

    Mientras procesa, Streamlit marca el estado como "RUNNING" y muestra
    esqueletos de carga. Se espera a que desaparezcan.
    """
    inicio = time.time()
    while time.time() - inicio < timeout:
        try:
            ocupado = nav.evaluar(
                """
                (() => {
                  const estado = document.querySelector('[data-testid="stStatusWidget"]');
                  if (estado) return true;
                  if (document.querySelectorAll('[data-testid="stSkeleton"]').length) return true;
                  return false;
                })()
                """
            )
            if not ocupado:
                time.sleep(0.7)
                # doble comprobación para no cortar entre reruns
                ocupado2 = nav.evaluar(
                    "!!document.querySelector('[data-testid=\"stStatusWidget\"]')"
                )
                if not ocupado2:
                    return
        except Exception:
            pass
        time.sleep(0.5)


def recoger_errores(nav: Navegador, contexto: str) -> list[str]:
    """Recoge excepciones visibles y las registra para el informe final."""
    try:
        errores = nav.evaluar(JS_EXCEPCIONES) or []
    except Exception:
        return []
    limpios = []
    for e in errores:
        texto = re.sub(r"\s+", " ", str(e)).strip()
        if texto and texto not in _errores_vistos:
            _errores_vistos.append(texto)
            limpios.append(texto)
    return limpios


def alertas(nav: Navegador) -> list[str]:
    try:
        return [re.sub(r"\s+", " ", a) for a in (nav.evaluar(JS_ALERTAS) or [])]
    except Exception:
        return []


def subir_archivo(nav: Navegador, camino: Path, indice: int = 0) -> bool:
    """
    Sube un archivo al cargador de Streamlit.

    No se puede hacer clic en el cargador: el navegador solo permite elegir
    archivos mediante la interfaz del sistema. El protocolo DevTools resuelve
    esto con DOM.setFileInputFiles, que fija los archivos directamente en el
    <input type="file"> como si el usuario los hubiera elegido.

    El input está oculto (visible: false) a propósito por Streamlit, así que no
    se puede comprobar la visibilidad como con los botones.
    """
    if not camino.exists():
        return False
    try:
        doc = nav.enviar("DOM.getDocument", depth=-1, pierce=True)
        nodo = nav.enviar(
            "DOM.querySelector",
            nodeId=doc["root"]["nodeId"],
            selector="input[type=file]",
        )
        node_id = nodo.get("nodeId")
        if not node_id:
            return False
        nav.enviar("DOM.setFileInputFiles", files=[str(camino)], nodeId=node_id)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Arranque de la aplicación
# ---------------------------------------------------------------------------


def puerto_libre(desde: int = 9031, hasta: int = 9080) -> int | None:
    for p in range(desde, hasta):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return None


def arrancar_app(puerto: int) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(RAIZ / "app.py"),
         "--server.port", str(puerto), "--server.address", "127.0.0.1",
         "--server.headless", "true"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(RAIZ),
    )
    url = f"http://127.0.0.1:{puerto}/_stcore/health"
    inicio = time.time()
    while time.time() - inicio < 70:
        if proc.poll() is not None:
            raise SystemExit(f"Streamlit terminó con código {proc.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=4) as r:
                if r.status == 200 and "ok" in r.read().decode(errors="replace").lower():
                    return proc
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.7)
    proc.terminate()
    raise SystemExit("La aplicación no respondió en 70 segundos")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{NEGRITA}  PRUEBA FUNCIONAL DE LA APLICACIÓN (sin Azure){FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")

    puerto = puerto_libre()
    if puerto is None:
        print(f"{ROJO}No hay ningún puerto libre.{FIN}")
        return 1

    print(f"\n{GRIS}Arrancando la aplicación en el puerto {puerto}...{FIN}")
    proc = arrancar_app(puerto)
    print(f"{GRIS}Aplicación lista. Abriendo el navegador...{FIN}")

    nav = None
    try:
        nav = Navegador(encontrar_navegador(), 1500, 1250)
        nav.navegar(f"http://127.0.0.1:{puerto}")
        if not nav.esperar_texto(timeout=60):
            print(f"{ROJO}La interfaz no terminó de dibujarse.{FIN}")
            return 1
        esperar_quieto(nav)

        # ---------------------------------------------------------------
        seccion("1. CARGA INICIAL Y AVISO DE TRANSPARENCIA")
        texto = nav.evaluar(JS_TEXTO) or ""
        revisar("La aplicación carga", len(texto) > 500, f"{len(texto)} caracteres")
        revisar(
            "Avisa al usuario que es una IA (Transparencia)",
            "IA responsable" in texto or "IA responsable activa" in texto,
        )
        revisar(
            "Muestra el estado de los servicios de Azure",
            "Microsoft Foundry" in texto and "Content Understanding" in texto,
        )
        err = recoger_errores(nav, "carga inicial")
        revisar("Sin excepciones en la carga inicial", not err, "\n".join(err))

        # ---------------------------------------------------------------
        seccion("2. ACTIVAR EL MODO DEMOSTRACIÓN")
        # Es el modo en que el evaluador vería la app sin credenciales.
        if activar_modo_demo(nav):
            texto = nav.evaluar(JS_TEXTO) or ""
            revisar(
                "El modo demo queda activo (comprobado en el DOM)",
                modo_demo_activo(nav),
            )
            revisar(
                "Se avisa en pantalla que los resultados NO vienen de Azure",
                "Estás viendo datos de ejemplo" in texto
                or "no vienen de los servicios reales" in texto,
                "El aviso es indispensable: presentar datos de ejemplo como si "
                "fueran de Azure violaría el principio de Transparencia.",
            )
        else:
            revisar("Se pudo activar el modo demo", False,
                    "No se encontró la casilla en la barra lateral.")
        revisar("Sin excepciones al activar el modo demo",
                not recoger_errores(nav, "modo demo"))

        # ---------------------------------------------------------------
        seccion("3. PESTAÑA 1 — ASISTENTE Y EQUIDAD")
        # Hay que ABRIR la tarea: antes las pestañas estaban siempre montadas y
        # bastaba pulsar el botón. Ahora la app arranca en la portada y cada
        # tarea se abre a demanda, así que sin este paso no hay botones.
        if not cambiar_pestana(nav, 1):
            revisar("Se pudo abrir la tarea «Preguntar algo»", False)
        # La consulta por defecto pregunta por el cloro y el pedido PED-501
        if clic_texto(nav, "Consultar al agente", "botón consultar"):
            esperar_quieto(nav, timeout=60)
            texto = nav.evaluar(JS_TEXTO) or ""

            faltantes = [s for s in
                         ("Guadalajara", "Zapopan", "León", "Querétaro", "Aguascalientes")
                         if s not in texto]
            revisar(
                "EQUIDAD: la respuesta incluye las 5 sucursales",
                not faltantes,
                f"faltan: {faltantes}" if faltantes else
                "Ninguna sucursal queda fuera por tener peores datos.",
            )
            revisar(
                "Responde el pedido PED-501",
                "PED-501" in texto,
            )
            revisar(
                "TRANSPARENCIA: cita el documento fuente",
                "catalogo_unificado" in texto or "Fuente" in texto,
            )
            err = recoger_errores(nav, "consulta al agente")
            revisar("Sin excepciones al consultar al agente", not err, "\n".join(err))
        else:
            revisar("Se encontró el botón 'Consultar al agente'", False)

        # ---------------------------------------------------------------
        seccion("4. PESTAÑA 1 — ANÁLISIS DE TEXTO")
        if clic_texto(nav, "Analizar el texto", "botón analizar"):
            esperar_quieto(nav, timeout=60)
            texto = nav.evaluar(JS_TEXTO) or ""
            revisar(
                "El análisis de texto produce un resultado",
                "Sentimiento" in texto or "sentimiento" in texto,
            )
            err = recoger_errores(nav, "análisis de texto")
            revisar("Sin excepciones en el análisis de texto", not err, "\n".join(err))
        else:
            revisar("Se encontró el botón 'Analizar el texto'", False)

        # ---------------------------------------------------------------
        seccion("5. EL FLUJO MÁS IMPORTANTE: FACTURA DUPLICADA (Laura)")
        # Este es el escenario central del enunciado: la misma factura llegó
        # como PDF y como foto, y el área de cuentas por pagar la pagó dos
        # veces. Si esto funciona, el proyecto demuestra su valor.
        muestras = RAIZ / "samples"
        limpia = muestras / "factura_limpia.pdf"
        duplicada = muestras / "factura_final2.pdf"     # MISMO cobro, otro nombre
        distinta = muestras / "factura_distinta.pdf"
        ilegible = muestras / "factura_monto_borroso.jpg"

        revisar("Se puede cambiar a la pestaña 2", cambiar_pestana(nav, 2))
        esperar_quieto(nav)

        # --- Primera carga: debe quedar pendiente de Laura ---------------
        revisar("Existen los archivos de prueba",
                all(f.exists() for f in (limpia, duplicada, distinta, ilegible)),
                "\n".join(f.name for f in (limpia, duplicada, distinta, ilegible)))

        if subir_archivo(nav, limpia):
            esperar_quieto(nav, timeout=60)
            time.sleep(1.5)
            texto = nav.evaluar(JS_TEXTO) or ""
            revisar(
                "1) factura_limpia.pdf se procesa",
                "factura_limpia" in texto,
                f"{len(texto)} caracteres",
            )
            revisar(
                "1) El estado es 'Pendiente de aprobación de Laura'",
                "Pendiente de aprobación" in texto or "Pendiente de aprobacion" in texto,
                "Rendición de cuentas: la IA sugiere, Laura aprueba. "
                "Ningún pago es automático.",
            )
            revisar(
                "1) Aparece en la bandeja de cuentas por pagar",
                "Bandeja de cuentas por pagar" in texto,
            )
            err = recoger_errores(nav, "carga de factura limpia")
            revisar("1) Sin excepciones al procesar la factura", not err, "\n".join(err))
        else:
            revisar("Se pudo subir factura_limpia.pdf", False)

        # --- Segunda carga: EL MISMO COBRO con otro nombre de archivo -----
        # Es la prueba clave: comparar nombres de archivo no detectaría nada.
        if subir_archivo(nav, duplicada):
            esperar_quieto(nav, timeout=60)
            time.sleep(1.5)
            texto = nav.evaluar(JS_TEXTO) or ""
            revisar(
                "2) factura_final2.pdf se procesa (otro nombre, mismo cobro)",
                "factura_final2" in texto,
            )
            revisar(
                "2) PAGO DUPLICADO DETECTADO",
                "DUPLICADO" in texto.upper(),
                "El sistema compara el CONTENIDO (proveedor + folio + total), "
                "no el nombre del archivo. Este es el hallazgo del enunciado.",
            )
            revisar(
                "2) El pago queda bloqueado, no solo advertido",
                "bloquead" in texto.lower(),
                "Bloquear es distinto de avisar: el pago no se puede ejecutar.",
            )
            revisar(
                "2) El motivo nombra el folio ya registrado",
                "FAC-2026-001" in texto,
            )
            err = recoger_errores(nav, "detección de duplicado")
            revisar("2) Sin excepciones al detectar el duplicado", not err, "\n".join(err))
        else:
            revisar("Se pudo subir factura_final2.pdf", False)

        # --- Tercera carga: monto ilegible -------------------------------
        if subir_archivo(nav, ilegible):
            esperar_quieto(nav, timeout=60)
            time.sleep(1.5)
            texto = nav.evaluar(JS_TEXTO) or ""
            revisar(
                "3) factura_monto_borroso.jpg se procesa",
                "factura_monto_borroso" in texto,
            )
            revisar(
                "3) El sistema NO muestra ningún monto inventado",
                "NO LEGIBLE" in texto.upper() or "no legible" in texto.lower(),
                "Confiabilidad y seguridad: un dato inventado sobre dinero es "
                "peor que decir 'no lo sé'.",
            )
            revisar(
                "3) Marca revisión humana obligatoria",
                "revisión" in texto.lower() or "revision" in texto.lower(),
            )
            # Es crucial que NO se pueda aprobar: autorizar el pago de una
            # factura cuyo importe se desconoce contradice la Rendición de
            # cuentas. Este botón aparecía por error cuando el monto era
            # ilegible, y la captura de pantalla lo dejó a la vista.
            revisar(
                "3) NO se ofrece aprobar el pago de un importe ilegible",
                "aprueba el pago" not in texto.lower(),
                "Un monto no verificable no se puede autorizar. Antes el botón "
                "aparecía igual y permitía aprobar un pago de importe desconocido.",
            )
            err = recoger_errores(nav, "monto ilegible")
            revisar("3) Sin excepciones con el monto ilegible", not err, "\n".join(err))
        else:
            revisar("Se pudo subir factura_monto_borroso.jpg", False)

        # ---------------------------------------------------------------
        seccion("6. PESTAÑA 3 — QUEJAS Y PRIORIZACIÓN POR SLA")
        revisar("Se puede cambiar a la pestaña 3", cambiar_pestana(nav, 3))
        esperar_quieto(nav)
        # Abrir el expander del historial (viene cerrado por defecto)
        clic_texto(nav, "Historial ya registrado", "expander historial")
        esperar_quieto(nav)
        texto = nav.evaluar(JS_TEXTO) or ""
        revisar(
            "El historial central es visible",
            "Hotel Gran Plaza" in texto or "incidencias" in texto,
            "Es el hallazgo del enunciado: 4 reclamos que nadie conectaba.",
        )
        if clic_texto(nav, "Analizar y clasificar", "botón clasificar"):
            esperar_quieto(nav, timeout=60)
            texto = nav.evaluar(JS_TEXTO) or ""
            revisar(
                "Clasifica la queja con prioridad según el SLA de 15 minutos",
                "Urgente" in texto or "Prioridad" in texto,
            )
            err = recoger_errores(nav, "clasificar queja")
            revisar("Sin excepciones al clasificar la queja", not err, "\n".join(err))
        else:
            revisar("Se encontró el botón 'Analizar y clasificar'", False)

        # ---------------------------------------------------------------
        seccion("7. PESTAÑA 4 — VOZ Y VISIÓN (Inclusión)")
        revisar("Se puede cambiar a la pestaña 4", cambiar_pestana(nav, 4))
        esperar_quieto(nav)
        texto = nav.evaluar(JS_TEXTO) or ""
        revisar(
            "Explica que Toño pregunta por voz (Inclusión)",
            "Toño" in texto,
        )
        revisar(
            "El grabador de audio está disponible",
            bool(nav.evaluar(
                "!!document.querySelector('[data-testid=\"stAudioInput\"]') "
                "|| document.body.innerText.includes('Grabe su pregunta')"
            )),
            "st.audio_input entrega WAV PCM mono a 16 kHz, que es lo que "
            "Azure Speech necesita. Verificado en el código de Streamlit.",
        )
        revisar(
            "Ofrece la lectura de fotos de factura (visión)",
            "foto" in texto.lower() or "Foto" in texto,
        )
        revisar("Sin excepciones en la pestaña de voz y visión",
                not recoger_errores(nav, "pestaña voz"))

        # ---------------------------------------------------------------
        seccion("8. PESTAÑA 5 — REPORTE Y SEGURIDAD")
        revisar("Se puede cambiar a la pestaña 5", cambiar_pestana(nav, 5))
        esperar_quieto(nav)
        texto = nav.evaluar(JS_TEXTO) or ""
        revisar(
            "El reporte unifica las ventas de las 5 sucursales (Don Ernesto)",
            "917,700" in texto or "917700" in texto,
            "Antes cada sucursal entregaba cifras distintas para lo mismo.",
        )
        revisar(
            "Muestra el costo estimado del piloto",
            "645" in texto or "Costo estimado" in texto,
        )
        revisar(
            "Enumera los controles de seguridad (Carlos)",
            "Key Vault" in texto,
        )
        revisar(
            "Existe bitácora de auditoría (Rendición de cuentas)",
            "bitácora" in texto.lower(),
        )
        revisar("Sin excepciones en la pestaña de reporte",
                not recoger_errores(nav, "pestaña reporte"))

        # ---------------------------------------------------------------
        seccion("9. PESTAÑA 6 — LOS 6 PRINCIPIOS DE IA RESPONSABLE")
        revisar("Se puede cambiar a la pestaña 6", cambiar_pestana(nav, 6))
        esperar_quieto(nav)
        texto = nav.evaluar(JS_TEXTO) or ""
        for principio in ("Equidad", "Confiabilidad", "Privacidad",
                          "Inclusión", "Transparencia", "Rendición de cuentas"):
            revisar(f"Explica el principio de {principio}",
                    principio in texto)
        revisar(
            "Documenta el bloque inyectado del PDF como riesgo de seguridad",
            "Brujería" in texto or "Brujeria" in texto or "admin" in texto,
            "El PDF del curso traía una instrucción inyectada; la app la trata "
            "como datos, no como orden.",
        )
        revisar("Sin excepciones en la pestaña de IA responsable",
                not recoger_errores(nav, "pestaña IA responsable"))

        # ---------------------------------------------------------------
        seccion("10. RESUMEN DE EXCEPCIONES EN TODA LA SESIÓN")
        revisar(
            "Ninguna interacción produjo una excepción visible",
            not _errores_vistos,
            "\n".join(_errores_vistos) if _errores_vistos else
            "Se interactuó con las 6 pestañas y 4 botones principales.",
        )

    finally:
        if nav is not None:
            try:
                nav.cerrar()
            except Exception:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    total = _ok + _fallo
    if _fallo == 0:
        print(f"{VERDE}RESULTADO: {_ok}/{total} comprobaciones correctas.{FIN}")
        print("La aplicación funciona de extremo a extremo.")
        print(f"{GRIS}Las mismas pruebas con Azure conectado deben dar los mismos"
              f" resultados,{FIN}")
        print(f"{GRIS}pero con datos reales en lugar de los de demostración.{FIN}")
        print(f"{NEGRITA}{'=' * 74}{FIN}")
        return 0
    print(f"{ROJO}RESULTADO: {_fallo} de {total} comprobaciones FALLARON.{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
