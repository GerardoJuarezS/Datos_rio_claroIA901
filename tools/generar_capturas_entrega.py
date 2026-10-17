"""
Generador de las capturas del documento de entrega.

A diferencia de `capturar_pantallas.py`, que solo fotografía cada pestaña recién
abierta, este script INTERACTÚA con la aplicación y captura los estados con
contenido real: la respuesta del asistente con las cinco sucursales, la factura
procesada, el pago duplicado bloqueado y el monto ilegible.

Esos cuatro estados son la evidencia que pide el enunciado, y ninguno se ve en
una captura de la pestaña vacía.

Las capturas se generan con el MODO DEMO activado, porque no hay credenciales
de Azure en la máquina. Cada imagen lo advierte en pantalla, y el documento de
entrega lo explica. Lo que se demuestra es real en ambos casos:

  * REAL sin Azure: la recuperación del catálogo unificado, la equidad entre
    sucursales, la detección de duplicados por contenido, el umbral de
    confianza, la priorización por SLA y la bitácora.
  * NECESITA AZURE: la extracción con Content Understanding, el agente de
    Foundry, Azure Speech y Azure AI Language.

Uso:
    python tools/generar_capturas_entrega.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

from capturar_pantallas import Navegador, encontrar_navegador  # noqa: E402
import probar_app_funcional as pf  # noqa: E402

DESTINO = RAIZ / "docs" / "capturas"

VERDE, ROJO, AMARILLO, GRIS, CIAN, NEGRITA, FIN = (
    "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[96m",
    "\033[1m", "\033[0m",
)

_ok = 0
_fallo = 0


def desplazar_a(nav: Navegador, texto: str) -> str:
    """
    Desplaza el panel principal hasta dejar visible el texto indicado.

    POR QUÉ NO SE USA scrollIntoView: el contenedor con scroll de Streamlit es
    <main data-testid="stMain">, con overflow:auto. Llamar a scrollIntoView
    sobre un elemento interno NO desplaza ese contenedor padre, así que la
    captura sale idéntica a la anterior. Hay que fijar su scrollTop a mano.

    Devuelve una descripción de lo que hizo, para poder depurarlo.
    """
    import json as _json

    return str(
        nav.evaluar(
            """
            (() => {
              const buscar = %s;
              const principal = document.querySelector('[data-testid="stMain"]')
                             || document.scrollingElement;
              if (!principal) return 'sin contenedor con scroll';

              // Se busca el elemento MÁS PEQUEÑO que contenga el texto, para
              // no acabar desplazándose a un contenedor que engloba toda la
              // página (lo que dejaría el scroll al principio).
              let objetivo = null;
              for (const el of document.querySelectorAll('p, h3, h4, div, span, label')) {
                  const t = el.innerText || '';
                  if (!t.includes(buscar)) continue;
                  if (t.length > 400) continue;
                  if (objetivo === null ||
                      t.length < (objetivo.innerText || '').length) {
                      objetivo = el;
                  }
              }
              if (!objetivo) return 'texto no encontrado: ' + buscar;

              const caja = objetivo.getBoundingClientRect();
              const cajaPadre = principal.getBoundingClientRect();
              // Posicionar el elemento hacia el tercio superior de la ventana.
              const destino = principal.scrollTop
                            + (caja.top - cajaPadre.top)
                            - (cajaPadre.height * 0.25);
              principal.scrollTop = Math.max(0, destino);
              return 'desplazado a ' + Math.round(principal.scrollTop)
                     + ' de ' + Math.round(principal.scrollHeight - principal.clientHeight);
            })()
            """
            % _json.dumps(texto)
        )
    )


def _azure_configurado() -> bool:
    """
    ¿Está Azure configurado de verdad?

    IMPORTANTE: hay que cargar el .env ANTES de mirar el entorno.
    Este script se ejecuta como programa aparte y NO hereda lo que la aplicación
    carga por su cuenta: la aplicación lee el .env dentro de su propio proceso.
    Sin esta carga, `os.environ` nunca tiene las credenciales, la comprobación
    daba «Azure no configurado» y las capturas salían en modo demo aunque todo
    estuviera bien. Ocurrió exactamente así.

    Se comprueba además que las variables tengan VALOR, no que existan: un .env
    con claves vacías haría caer la aplicación al modo demo sin avisar, y las
    capturas saldrían con datos de ejemplo creyendo que son reales.
    """
    archivo = RAIZ / ".env"
    if archivo.exists():
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, _, valor = linea.partition("=")
            # No se pisa lo que ya venga del entorno real: en App Service las
            # credenciales van en variables, no en un archivo.
            os.environ.setdefault(clave.strip(), valor.strip())

    necesarias = (
        "FOUNDRY_PROJECT_ENDPOINT",
        "CONTENT_UNDERSTANDING_ENDPOINT",
        "CONTENT_UNDERSTANDING_KEY",
        "SPEECH_KEY",
        "LANGUAGE_ENDPOINT",
        "LANGUAGE_KEY",
    )
    return all((os.environ.get(n) or "").strip() for n in necesarias)


def capturar(
    nav: Navegador,
    nombre: str,
    espera: float = 1.6,
    centrar_en: str | None = None,
    esperar_a: str | tuple[str, ...] | None = None,
    limite: float = 90.0,
) -> bool:
    """
    Captura el estado actual de la pantalla.

    `centrar_en` es un fragmento de texto que se desplaza a la vista antes de
    fotografiar. Es necesario porque varias pantallas son más altas que la
    ventana: sin desplazarse, la parte importante de la evidencia (el motivo
    del bloqueo, por ejemplo) queda fuera del recorte.

    `esperar_a` es texto que debe aparecer ANTES de fotografiar. Hace falta
    porque las llamadas a Azure tardan mucho más que el modo demostración: sin
    esta espera, la captura se tomaba con el indicador de carga en pantalla
    («Extrayendo con Azure Content Understanding…») y la tabla de resultados
    todavía vacía. La imagen servía de muy poco como evidencia.
    """
    destino = DESTINO / nombre
    try:
        pf.esperar_quieto(nav)

        # ------------------------------------------------------------------
        # Esperar a que la llamada a Azure TERMINE de verdad.
        #
        # Comprobar solo que aparezca un texto NO basta: en el flujo de facturas
        # el texto «Datos extraídos» ya estaba en pantalla de la factura
        # ANTERIOR, así que la espera terminaba de inmediato y la captura salía
        # con el indicador de carga puesto y el resultado viejo. Por eso se
        # espera, además, a que desaparezca el indicador de Streamlit.
        # ------------------------------------------------------------------
        objetivos = ()
        if esperar_a:
            objetivos = (esperar_a,) if isinstance(esperar_a, str) else esperar_a

        inicio = time.time()
        while time.time() - inicio < limite:
            texto = nav.evaluar(pf.JS_TEXTO) or ""
            cargando = ("Extrayendo con Azure" in texto
                        or "Consultando al agente" in texto
                        or "Analizando" in texto)
            listo = (not objetivos) or any(o in texto for o in objetivos)
            if listo and not cargando:
                break
            time.sleep(1.5)
        else:
            if objetivos:
                print(f"        {AMARILLO}No se confirmó "
                      f"{' / '.join(objetivos)[:50]!r} sin carga en {limite:.0f}s; "
                      f"se captura igualmente{FIN}")
        # Un instante extra para que Streamlit termine de pintar.
        time.sleep(1.5)

        if centrar_en:
            resultado = desplazar_a(nav, centrar_en)
            time.sleep(1.0)
            if "no encontrado" in resultado:
                print(f"        {AMARILLO}{resultado}{FIN}")
        nav.capturar(destino, espera=espera)
        peso = destino.stat().st_size
        if peso < 3000:
            print(f"  {AMARILLO}AVISO{FIN} {nombre} pesa muy poco ({peso} bytes); "
                  f"puede estar en blanco")
            return False
        print(f"  {VERDE}OK{FIN}    {nombre}  ({peso:,} bytes)")
        return True
    except Exception as exc:
        print(f"  {ROJO}FALLA{FIN} {nombre}: {exc}")
        return False


def main() -> int:
    global _ok, _fallo

    DESTINO.mkdir(parents=True, exist_ok=True)

    # Se decide ANTES de arrancar nada, para poder anunciarlo en la cabecera y
    # para que el mensaje final sepa qué se usó realmente.
    con_azure = _azure_configurado()

    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{NEGRITA}  CAPTURAS PARA EL DOCUMENTO DE ENTREGA{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    if con_azure:
        print(f"{VERDE}Azure está configurado: las capturas se generarán con los "
              f"servicios reales.{FIN}")
    else:
        print(f"{AMARILLO}No hay credenciales: las capturas saldrán en modo demo "
              f"y cada imagen lo advertirá.{FIN}")

    puerto = pf.puerto_libre(9081, 9130)
    if puerto is None:
        print(f"{ROJO}No hay puerto libre.{FIN}")
        return 1

    print(f"\n{GRIS}Arrancando la aplicación en el puerto {puerto}...{FIN}")
    proc = pf.arrancar_app(puerto)

    nav = None
    try:
        nav = Navegador(encontrar_navegador(), 1500, 1300)
        nav.navegar(f"http://127.0.0.1:{puerto}")
        if not nav.esperar_texto(timeout=60):
            print(f"{ROJO}La interfaz no se dibujó.{FIN}")
            return 1
        pf.esperar_quieto(nav)

        print(f"\n{CIAN}1. Estado inicial{FIN}")
        capturar(nav, "01_estado_inicial.png")

        # ------------------------------------------------------------------
        # ¿MODO DEMO O AZURE REAL?
        #
        # Antes este script activaba SIEMPRE el modo demostración, así que las
        # capturas mostraban datos de ejemplo incluso con credenciales
        # configuradas. Eso dejaba el documento de entrega evidenciando el modo
        # demo, que es justo lo contrario de lo que pide el enunciado.
        #
        # Ahora se decide según si hay credenciales. Se comprueba que la app
        # tenga Azure configurado, no que el archivo .env exista: un .env con
        # valores vacíos no sirve de nada.
        # ------------------------------------------------------------------
        print(f"\n{CIAN}2. Modo de ejecución{FIN}")
        if con_azure:
            desactivado = pf.desactivar_modo_demo(nav)
            estado = "desactivado" if desactivado else "NO se pudo desactivar"
            print(f"  Azure está configurado: modo demo {estado}")
            print(f"  {GRIS}Las capturas mostrarán datos reales de Azure.{FIN}")
            if not desactivado:
                print(f"  {ROJO}ATENCIÓN: las capturas saldrán en modo demo.{FIN}")
                return 1
            capturar(nav, "01_estado_inicial.png")
            # Se comprueba que la app CONFIRME la conexión, no solo que la
            # casilla esté desmarcada: si las credenciales fallaran, la casilla
            # estaría bien y las capturas saldrían con datos de ejemplo.
            if not pf.azure_confirmado(nav):
                print(f"  {ROJO}La app no confirma la conexión con Azure. "
                      f"Revise las credenciales.{FIN}")
                return 1
            print(f"  {VERDE}La aplicación confirma que usará Azure.{FIN}")
        else:
            print(f"  {AMARILLO}Azure no está configurado: se usará el modo demo.{FIN}")
            print(f"  {GRIS}Las capturas mostrarán datos de ejemplo, no de Azure.{FIN}")
            print(f"  {GRIS}Para capturar con Azure: cree el .env con sus "
                  f"credenciales y repita.{FIN}")
            pf.activar_modo_demo(nav)
            # No se captura el modo demo en una imagen aparte: el documento de
            # entrega no la usa, y generarla dejaba un archivo huérfano en
            # docs/capturas/ que nadie abría.

        print(f"\n{CIAN}3. Asistente: respuesta con las 5 sucursales (Equidad){FIN}")
        pf.cambiar_pestana(nav, 1)
        pf.esperar_quieto(nav)
        if pf.clic_texto(nav, "Consultar al agente", "consultar"):
            pf.esperar_quieto(nav, timeout=60)
            time.sleep(1.5)
            capturar(nav, "03_asistente_equidad.png")
        else:
            print(f"  {ROJO}FALLA{FIN} no se pudo pulsar 'Consultar al agente'")
            _fallo += 1

        print(f"\n{CIAN}4. Análisis de texto (Azure AI Language){FIN}")
        if pf.clic_texto(nav, "Analizar el texto", "analizar"):
            pf.esperar_quieto(nav, timeout=60)
            time.sleep(1.5)
            capturar(nav, "04_analisis_texto.png", esperar_a=("Sentimiento", "palabras clave", "Idioma"))
        else:
            print(f"  {ROJO}FALLA{FIN} no se pudo pulsar 'Analizar el texto'")
            _fallo += 1

        print(f"\n{CIAN}5. Factura limpia: pendiente de aprobación de Laura{FIN}")
        pf.cambiar_pestana(nav, 2)
        pf.esperar_quieto(nav)
        if pf.subir_archivo(nav, RAIZ / "samples" / "factura_limpia.pdf"):
            pf.esperar_quieto(nav, timeout=60)
            time.sleep(2.0)
            capturar(nav, "05_factura_limpia.png", centrar_en="Decisión del sistema",
                     esperar_a="Datos extraídos")
        else:
            print(f"  {ROJO}FALLA{FIN} no se pudo subir la factura limpia")
            _fallo += 1

        print(f"\n{CIAN}6. EL MISMO COBRO con otro nombre: pago duplicado bloqueado{FIN}")
        if pf.subir_archivo(nav, RAIZ / "samples" / "factura_final2.pdf"):
            pf.esperar_quieto(nav, timeout=60)
            time.sleep(2.0)
            # Una sola toma: la del motivo del bloqueo, que es la evidencia más
            # importante del proyecto. Antes se hacían dos capturas de la misma
            # pantalla y solo se usaba esta; la otra quedaba huérfana.
            capturar(nav, "06b_motivo_duplicado.png",
                     centrar_en="Ya existe un registro idéntico", espera=1.0,
                     esperar_a=("PAGO DUPLICADO", "duplicad"))
        else:
            print(f"  {ROJO}FALLA{FIN} no se pudo subir la factura duplicada")
            _fallo += 1

        print(f"\n{CIAN}7. Monto ilegible: no se inventa ninguna cifra{FIN}")
        if pf.subir_archivo(nav, RAIZ / "samples" / "factura_monto_borroso.jpg"):
            pf.esperar_quieto(nav, timeout=60)
            time.sleep(2.0)
            capturar(nav, "07_monto_ilegible.png", centrar_en="Decisión del sistema",
                     esperar_a=("NO LEGIBLE", "revisión humana", "Datos extraídos"))
            capturar(nav, "07b_sin_monto_ni_revision.png",
                     centrar_en="NO LEGIBLE", espera=1.0)
        else:
            print(f"  {ROJO}FALLA{FIN} no se pudo subir la foto con monto ilegible")
            _fallo += 1

        print(f"\n{CIAN}8. Bandeja de cuentas por pagar con las tres facturas{FIN}")
        capturar(nav, "08_bandeja_cuentas_por_pagar.png", esperar_a="factura_limpia",
                     
                 centrar_en="Bandeja de cuentas por pagar", espera=1.0)

        print(f"\n{CIAN}9. Quejas: historial central y priorización por SLA{FIN}")
        pf.cambiar_pestana(nav, 3)
        pf.esperar_quieto(nav)
        pf.clic_texto(nav, "Historial ya registrado", "historial")
        pf.esperar_quieto(nav)
        if pf.clic_texto(nav, "Analizar y clasificar", "clasificar"):
            pf.esperar_quieto(nav, timeout=60)
            time.sleep(1.5)
        capturar(nav, "09_quejas_sla.png")

        print(f"\n{CIAN}10. Voz y visión (Inclusión){FIN}")
        pf.cambiar_pestana(nav, 4)
        pf.esperar_quieto(nav)
        capturar(nav, "10_voz_vision.png")

        print(f"\n{CIAN}11. Reporte directivo y costo del piloto{FIN}")
        pf.cambiar_pestana(nav, 5)
        pf.esperar_quieto(nav)
        capturar(nav, "11_reporte_directivo.png")
        # Abrir el desglose del costo
        if pf.clic_texto(nav, "Desglose del costo del piloto", "costo"):
            pf.esperar_quieto(nav)
            capturar(nav, "12_costo_piloto.png")
        else:
            print(f"  {AMARILLO}AVISO{FIN} no se encontró el desglose del costo")

        print(f"\n{CIAN}12. IA responsable: los seis principios con evidencia{FIN}")
        pf.cambiar_pestana(nav, 6)
        pf.esperar_quieto(nav)
        capturar(nav, "13_ia_responsable.png", espera=2.0)

        print(f"\n{CIAN}13. Bitácora de auditoría (Rendición de cuentas){FIN}")
        pf.cambiar_pestana(nav, 5)
        pf.esperar_quieto(nav)
        nav.evaluar("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.0)
        capturar(nav, "14_bitacora_auditoria.png", espera=1.0)

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

    # ---------------------------------------------------------------
    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    generadas = sorted(DESTINO.glob("*.png"))
    print(f"  {VERDE}{len(generadas)} capturas en {DESTINO}{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")

    # El mensaje final depende de lo que se haya usado de verdad. Antes decía
    # siempre «se generaron en MODO DEMO», incluso cuando las capturas sí
    # venían de Azure: un aviso que miente hace perder tiempo revisando algo
    # que estaba bien.
    if con_azure:
        print(f"""
{VERDE}Estas capturas se generaron con AZURE CONECTADO.{FIN}

  Los datos que muestran vienen de los servicios reales: Microsoft Foundry,
  Azure AI Language, Azure Speech y Content Understanding.

  Antes de entregar, repase que:
    * la barra lateral muestre ⏳ en los cuatro servicios, no ⚠️;
    * no aparezca el aviso «Modo demo activo»;
    * el flujo de facturas muestre la decisión del sistema con datos reales.
""")
    else:
        print(f"""
{AMARILLO}IMPORTANTE ANTES DE ENTREGAR:{FIN}

  Estas capturas se generaron en MODO DEMO, sin Azure conectado. Sirven para
  redactar el documento y para ver la aplicación completa, pero el enunciado
  exige evidenciar el funcionamiento con Azure.

  Cuando tenga sus credenciales:
    1. Cree el archivo .env con sus claves (vea .env.example).
    2. Ejecute este mismo script: se regeneran con datos de Azure.
    3. Repase que la barra lateral muestre ⏳ y no ⚠️.
""")
    return 0 if _fallo == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
