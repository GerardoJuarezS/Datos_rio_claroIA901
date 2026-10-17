"""
Comprueba en la aplicación DESPLEGADA que la identidad administrada funcione.

POR QUÉ ESTA PRUEBA ES LA DEFINITIVA
------------------------------------
Un «HTTP 200» solo demuestra que Streamlit arrancó. No demuestra que la
aplicación pueda hacer su trabajo: llamar a los servicios de Azure y leer los
secretos del Key Vault con su identidad administrada.

Aquí se abre la aplicación publicada en un navegador real, se navega a la
pestaña de seguridad, se pulsa el botón de comprobación y se lee el resultado
que la propia aplicación muestra. Es la única prueba que cubre la cadena
completa: navegador -> App Service -> identidad administrada -> Entra ID ->
Key Vault -> modelo de Foundry.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capturar_pantallas import Navegador, encontrar_navegador  # noqa: E402

VERDE, ROJO, AMARILLO, GRIS, NEGRITA, FIN = (
    "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[1m", "\033[0m",
)

URL = "https://rioclaro-ai901.azurewebsites.net"


def main() -> int:
    print()
    print(f"{NEGRITA}{'=' * 72}{FIN}")
    print(f"{NEGRITA}  PRUEBA DE LA APLICACIÓN DESPLEGADA{FIN}")
    print(f"{NEGRITA}{'=' * 72}{FIN}\n")
    print(f"{GRIS}URL: {URL}{FIN}\n")

    ejecutable = encontrar_navegador()
    if not ejecutable:
        print(f"{ROJO}No se encontró un navegador (Edge o Chrome).{FIN}\n")
        return 1

    nav = Navegador(ejecutable, ancho=1500, alto=1400)
    try:
        print(f"{GRIS}Abriendo la aplicación publicada…{FIN}")
        nav.navegar(URL)
        if not nav.esperar_texto(timeout=120):
            print(f"{ROJO}La aplicación no terminó de cargar.{FIN}\n")
            return 1
        print(f"{VERDE}OK{FIN}    La aplicación cargó en el navegador")

        # El portal se organiza por TAREA, no por servicio de Azure. La
        # comprobación de conexión vive en «Comprobar el sistema», que es donde
        # Carlos la buscaría.
        if not nav.clic_por_texto("Comprobar el sistema"):
            print(f"{ROJO}No se encontró la tarea «Comprobar el sistema».{FIN}\n")
            return 1
        print(f"{VERDE}OK{FIN}    Se abrió la tarea «Comprobar el sistema»")
        time.sleep(3)

        # Pulsar el botón de comprobación
        if not nav.clic_por_texto("Comprobar la conexión con Azure"):
            print(f"{ROJO}No se encontró el botón de comprobación.{FIN}\n")
            return 1
        print(f"{GRIS}Pulsado el botón; esperando a Azure (puede tardar 30-60 s)…{FIN}")

        # El diagnóstico muestra resultados como ✅ / ❌. Se espera al veredicto.
        textos = ("El modelo", "Se leyeron", "No se pudo", "Faltan")
        encontrado = ""
        for _ in range(40):
            time.sleep(3)
            contenido = nav.evaluar(
                "Array.from(document.querySelectorAll("
                "'[data-testid=\"stAlert\"], [data-testid=\"stMarkdownContainer\"]'))"
                ".map(e => e.innerText).join('\\n')"
            ) or ""
            if any(t in contenido for t in textos):
                encontrado = contenido
                break

        print()
        if not encontrado:
            print(f"{ROJO}La aplicación no mostró el resultado del diagnóstico.{FIN}\n")
            return 1

        # Mostrar las líneas del diagnóstico.
        # Streamlit duplica el texto en el DOM (el contenedor y su copia para
        # lectores de pantalla), así que se eliminan las repeticiones
        # consecutivas antes de mostrar.
        lineas = [l.strip() for l in encontrado.splitlines() if l.strip()]
        limpias: list[str] = []
        for linea in lineas:
            if limpias and limpias[-1] == linea:
                continue
            limpias.append(linea)

        inicio = next(
            (i for i, l in enumerate(limpias)
             if "Estado de la conexión" in l or "conexión con Azure" in l),
            0,
        )
        for linea in limpias[inicio:inicio + 22]:
            if linea.startswith("✅"):
                print(f"{VERDE}{linea}{FIN}")
            elif linea.startswith("❌"):
                print(f"{ROJO}{linea}{FIN}")
            elif linea.startswith("⚠️"):
                print(f"{AMARILLO}{linea}{FIN}")
            elif linea.startswith(("Pulse", "Comprueba")):
                continue
            else:
                print(f"{GRIS}{linea[:150]}{FIN}")

        print()
        fallos = encontrado.count("❌")
        exitos = encontrado.count("✅")
        print(f"{NEGRITA}{'=' * 72}{FIN}")
        if fallos == 0 and exitos >= 3:
            print(f"  {VERDE}LA APLICACIÓN DESPLEGADA FUNCIONA CON AZURE{FIN}")
            print(f"  {exitos} comprobaciones correctas, 0 fallos.")
            print(f"  La identidad administrada tiene los permisos necesarios.")
            print(f"{NEGRITA}{'=' * 72}{FIN}\n")
            return 0
        print(f"  {ROJO}{fallos} fallo(s) y {exitos} acierto(s) en Azure.{FIN}")
        print(f"{NEGRITA}{'=' * 72}{FIN}\n")
        return 1

    finally:
        try:
            nav.cerrar()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
