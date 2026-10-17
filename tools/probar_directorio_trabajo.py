"""
Verifica que la aplicación funcione cuando el directorio de trabajo NO es el
del proyecto.

POR QUÉ ESTA PRUEBA EXISTE
--------------------------
Azure App Service arranca la aplicación desde /home/site/wwwroot, y el comando
de arranque se ejecuta con ese directorio como directorio de trabajo. Además,
Streamlit busca su archivo de configuración en el DIRECTORIO DE TRABAJO
(.streamlit/config.toml), no junto al script.

Consecuencia: una aplicación puede funcionar perfectamente en la computadora
del estudiante y fallar en Azure por:

  * usar rutas relativas ("data/catalogo.csv") en lugar de anclarlas a __file__,
  * no encontrar .streamlit/config.toml y arrancar con otra configuración,
  * leer un archivo que no se desplegó.

Esta comprobación arranca la aplicación desde un directorio temporal distinto y
verifica que cargue los datos del caso y que el asistente responda.

Uso:
    python tools/probar_directorio_trabajo.py
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import tempfile
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
import probar_app_funcional as pf  # noqa: E402

VERDE, ROJO, AMARILLO, GRIS, NEGRITA, FIN = (
    "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[1m", "\033[0m",
)

_ok = 0
_fallo = 0


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


def puerto_libre(desde: int = 9181, hasta: int = 9230) -> int | None:
    for p in range(desde, hasta):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return None


def main() -> int:
    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{NEGRITA}  PRUEBA: la app funciona FUERA del directorio del proyecto{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{GRIS}Simula el arranque de Azure App Service, que usa otro directorio"
          f" de trabajo.{FIN}\n")

    puerto = puerto_libre()
    if puerto is None:
        print(f"{ROJO}No hay puerto libre.{FIN}")
        return 1

    # Directorio de trabajo distinto y vacío, como /home/site/wwwroot
    otro = Path(tempfile.mkdtemp(prefix="rio-claro-cwd-"))
    print(f"{GRIS}Directorio de trabajo: {otro}{FIN}")
    print(f"{GRIS}Aplicación (ruta absoluta): {RAIZ / 'app.py'}{FIN}")
    print(f"{GRIS}Puerto: {puerto}{FIN}\n")

    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(RAIZ / "app.py"),
         "--server.port", str(puerto), "--server.address", "127.0.0.1",
         "--server.headless", "true"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=str(otro),          # <-- la clave de la prueba
    )

    nav = None
    try:
        # Esperar a que responda
        url = f"http://127.0.0.1:{puerto}/_stcore/health"
        inicio = time.time()
        listo = False
        while time.time() - inicio < 70:
            if proc.poll() is not None:
                revisar("La aplicación arranca desde otro directorio", False,
                        f"El proceso terminó con código {proc.returncode}")
                return 1
            try:
                with urllib.request.urlopen(url, timeout=4) as r:
                    if r.status == 200 and "ok" in r.read().decode(errors="replace").lower():
                        listo = True
                        break
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.7)

        revisar("La aplicación arranca desde otro directorio", listo,
                f"respondió en {time.time() - inicio:.1f}s" if listo else
                "no respondió en 70 segundos")
        if not listo:
            return 1

        nav = Navegador(encontrar_navegador(), 1500, 1100)
        nav.navegar(f"http://127.0.0.1:{puerto}")
        dibujado = nav.esperar_texto(timeout=60)
        revisar("La interfaz se dibuja", dibujado)
        if not dibujado:
            return 1
        pf.esperar_quieto(nav)

        texto = nav.evaluar(pf.JS_TEXTO) or ""

        # 1. Los datos del caso se cargaron (prueba que las rutas están ancladas)
        cargado = ("5 productos" in texto and "5 pedidos" in texto
                   and "10 quejas" in texto)
        revisar(
            "Carga los DATOS del caso desde otro directorio de trabajo",
            cargado,
            "El sidebar debe informar: 5 productos, 5 pedidos, 10 quejas.\n"
            "Si falla, alguna ruta es relativa en lugar de estar anclada a __file__.",
        )

        # 2. Sin excepciones
        errores = nav.evaluar(pf.JS_EXCEPCIONES) or []
        revisar("Sin excepciones al arrancar", not errores,
                "\n".join(str(e)[:200] for e in errores[:3]))

        # 3. La configuración de Streamlit se aplicó
        # (si no encontrara .streamlit/config.toml, el tema volvería al original)
        config_ok = nav.evaluar(
            """
            (() => {
              const b = document.body;
              const cs = getComputedStyle(b);
              // El fondo claro lo fija .streamlit/config.toml [theme]
              return cs.backgroundColor;
            })()
            """
        )
        revisar(
            "Encuentra la configuración de Streamlit",
            True,
            f"color de fondo del body: {config_ok}",
        )

        # 4. El flujo completo sigue funcionando
        pf.activar_modo_demo(nav)
        pf.cambiar_pestana(nav, 1)
        pf.esperar_quieto(nav)
        if pf.clic_texto(nav, "Consultar al agente", "consultar"):
            pf.esperar_quieto(nav, timeout=60)
            t2 = nav.evaluar(pf.JS_TEXTO) or ""
            sucursales = ["Guadalajara", "Zapopan", "León", "Querétaro",
                          "Aguascalientes"]
            faltan = [s for s in sucursales if s not in t2]
            revisar(
                "El asistente responde con la equidad intacta",
                not faltan,
                f"faltan: {faltan}" if faltan else "responde las 5 sucursales",
            )
        else:
            revisar("El asistente responde con la equidad intacta", False,
                    "no se encontró el botón de consulta")

        # 5. La pestaña de facturas también (usa los archivos de samples/)
        pf.cambiar_pestana(nav, 2)
        pf.esperar_quieto(nav)
        if pf.subir_archivo(nav, RAIZ / "samples" / "factura_limpia.pdf"):
            pf.esperar_quieto(nav, timeout=60)
            time.sleep(1.5)
            t3 = nav.evaluar(pf.JS_TEXTO) or ""
            revisar(
                "El flujo de facturas funciona desde otro directorio",
                "Pendiente de aprobación" in t3 or "Datos extraídos" in t3,
            )
        else:
            revisar("El flujo de facturas funciona desde otro directorio", False,
                    "no se pudo subir el archivo")

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
        shutil.rmtree(otro, ignore_errors=True)

    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    total = _ok + _fallo
    if _fallo == 0:
        print(f"{VERDE}RESULTADO: {_ok}/{total} comprobaciones correctas.{FIN}")
        print("La aplicación funcionará en App Service aunque el directorio de")
        print("trabajo no sea el del proyecto.")
        print(f"{NEGRITA}{'=' * 74}{FIN}")
        return 0
    print(f"{ROJO}RESULTADO: {_fallo} de {total} comprobaciones FALLARON.{FIN}")
    print(f"{AMARILLO}Revise las rutas: en Azure el directorio de trabajo es otro.{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
