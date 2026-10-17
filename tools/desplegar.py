"""
Empaqueta el proyecto y lo despliega en Azure App Service.

Se empaqueta en un ZIP y se despliega con `az webapp deploy`. Oryx (el sistema
de compilación de App Service) instala las dependencias de requirements.txt en
el servidor, así que el ZIP solo lleva el código.

QUÉ SE INCLUYE Y QUÉ NO
-----------------------
Se incluyen solo los archivos que la aplicación necesita en ejecución. Quedan
fuera, a propósito:
  * .env          -> los secretos van en App Settings y Key Vault, NUNCA en el ZIP
  * tools/        -> son scripts de desarrollo, no forman parte del producto
  * docs/         -> documentación y capturas
  * .git/         -> historial de control de versiones
  * .github/      -> flujo de CI/CD

Incluir .env en el paquete sería el error más grave posible en este proyecto:
el ZIP se sube a Azure y los secretos acabarían en el servidor en claro,
además de en cualquier copia del paquete. Hay una comprobación explícita que
aborta si el .env aparece dentro del ZIP.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent
PAQUETE = RAIZ / "deploy.zip"

GRIS, VERDE, ROJO, AMARILLO, NEGRITA, FIN = (
    "\033[90m", "\033[92m", "\033[91m", "\033[93m", "\033[1m", "\033[0m",
)

# Archivos y carpetas que forman la aplicación desplegada.
#
# Los módulos de Python NO se listan a mano: se DESCUBREN. Con una lista fija,
# añadir un módulo nuevo (portal.py, ui.py) y olvidar añadirlo aquí producía un
# paquete incompleto que fallaba en Azure con ModuleNotFoundError, y solo se
# descubría al probar la app ya desplegada. Ocurrió exactamente así al pasar el
# portal a producto.
INCLUIR_CARPETAS = [
    "data",
    "samples",
    ".streamlit",
]

# Archivos que no son código pero la aplicación necesita en ejecución.
INCLUIR_OTROS = [
    "requirements.txt",
    "startup.sh",
]

# Nunca deben acabar en el paquete.
PROHIBIDOS = {".env", ".env.local", "deploy.zip", ".env.example"}
PROHIBIDAS_CARPETAS = {"tools", "docs", ".git", ".github", "__pycache__",
                       ".venv", "venv", "node_modules"}

# Scripts de trabajo que no forman parte del producto.
NO_EMPAQUETAR = {
    "_convertir", "_corregir", "_limpiar", "_analisis",
    "_pulir", "_pulir2", "_pulir3", "_ver_portada", "_ver_nav",
    "_caps", "_act_tests", "_ver_sidebar", "_ver_error", "_ver_total",
    "_ver_total2", "_ver_pdf", "_ver_variantes", "_ver_legibilidad",
    "_diag_cu", "_diag_cu2", "_diag_cu3", "_diag_cu4", "_diag_cu5",
    "_diag_cu6", "_diag_cu7", "_diag_cu8", "_diag_read", "_prueba_extraccion",
    "_actualizar", "_u",
}


def modulos_python() -> list[str]:
    """
    Descubre los módulos de Python de la raíz del proyecto.

    Se incluyen los .py sueltos de la raíz: app.py, rio_claro.py, portal.py,
    ui.py y cualquiera que se añada en el futuro. Las herramientas de
    desarrollo viven en tools/ y no se suben: no son parte del producto.
    """
    modulos = []
    for archivo in sorted(RAIZ.glob("*.py")):
        if archivo.stem in NO_EMPAQUETAR or archivo.stem.startswith("_"):
            continue
        modulos.append(archivo.name)
    return modulos


INCLUIR_ARCHIVOS = INCLUIR_OTROS


def crear_paquete() -> tuple[bool, str]:
    """Crea deploy.zip. Devuelve (ok, mensaje)."""
    if PAQUETE.exists():
        PAQUETE.unlink()

    agregados = 0
    with zipfile.ZipFile(PAQUETE, "w", zipfile.ZIP_DEFLATED) as z:
        # Primero los módulos de Python, descubiertos automáticamente.
        modulos = modulos_python()
        print(f"  {GRIS}Módulos de Python detectados: {', '.join(modulos)}{FIN}")
        for nombre in modulos:
            z.write(RAIZ / nombre, nombre)
            agregados += 1
            print(f"  {VERDE}+{FIN} {nombre}")

        # Después los archivos que no son código pero hacen falta.
        for nombre in INCLUIR_ARCHIVOS:
            ruta = RAIZ / nombre
            if not ruta.exists():
                return False, f"Falta un archivo necesario: {nombre}"
            # startup.sh debe conservar los finales de línea LF: con CRLF, el
            # contenedor Linux falla con «bad interpreter: No such file or
            # directory». Por eso se escribe el contenido tal cual, sin que
            # Windows lo traduzca.
            datos = ruta.read_bytes()
            if nombre.endswith(".sh"):
                datos = datos.replace(b"\r\n", b"\n")
            z.writestr(nombre, datos)
            agregados += 1
            print(f"  {VERDE}+{FIN} {nombre}")

        for carpeta in INCLUIR_CARPETAS:
            base = RAIZ / carpeta
            if not base.exists():
                print(f"  {AMARILLO}!{FIN} {carpeta}/ no existe, se omite")
                continue
            for archivo in sorted(base.rglob("*")):
                if not archivo.is_file():
                    continue
                if archivo.name in PROHIBIDOS:
                    continue
                if any(p in archivo.parts for p in PROHIBIDAS_CARPETAS):
                    continue
                relativo = archivo.relative_to(RAIZ).as_posix()
                z.write(archivo, relativo)
                agregados += 1
            print(f"  {VERDE}+{FIN} {carpeta}/")

    # ------------------------------------------------------------------
    # Comprobación de seguridad: ningún secreto dentro del paquete.
    # Se hace DESPUÉS de crearlo, leyendo su contenido real. Comprobar la
    # lista de archivos no basta: un .env podría colarse por otra ruta.
    # ------------------------------------------------------------------
    with zipfile.ZipFile(PAQUETE) as z:
        nombres = z.namelist()
        for nombre in nombres:
            base = Path(nombre).name
            if base in PROHIBIDOS:
                PAQUETE.unlink(missing_ok=True)
                return False, (
                    f"ABORTADO: '{nombre}' quedó dentro del paquete.\n"
                    "Contiene secretos y NUNCA debe subirse a Azure."
                )

    tamano = PAQUETE.stat().st_size
    return True, f"{agregados} archivos, {tamano / 1024:.0f} KB"


def desplegar(nombre_app: str, grupo: str) -> int:
    print()
    print(f"{NEGRITA}Desplegando en {nombre_app}…{FIN}")
    print(f"{GRIS}(Oryx instalará las dependencias en el servidor; puede tardar "
          f"varios minutos){FIN}")
    print()

    # Se resuelve la ruta del ejecutable en lugar de confiar en que "az" esté en
    # el PATH del subproceso. En Windows, instalar Azure CLI actualiza el PATH
    # del usuario, pero los procesos ya abiertos conservan el viejo: eso hace
    # que subprocess.run(["az", ...]) falle con
    # «FileNotFoundError: El sistema no puede encontrar el archivo
    # especificado», que no menciona Azure ni el PATH.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from provision_azure import encontrar_az

        az = encontrar_az() or "az"
    except ImportError:
        az = "az"
    print(f"{GRIS}Usando: {az}{FIN}")

    proc = subprocess.run(
        [
            az, "webapp", "deploy",
            "--name", nombre_app,
            "--resource-group", grupo,
            "--src-path", str(PAQUETE),
            "--type", "zip",
            "--clean", "true",
            "--timeout", "900",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        print(f"{ROJO}El despliegue falló.{FIN}")
        print((proc.stderr or proc.stdout or "")[:2000])
        return 1
    print(f"{VERDE}Despliegue enviado correctamente.{FIN}")
    if proc.stdout:
        print(f"{GRIS}{proc.stdout.strip()[:600]}{FIN}")
    return 0


def main() -> int:
    grupo = "rg-rio-claro-ai901"
    app = "rioclaro-ai901"
    for i, arg in enumerate(sys.argv):
        if arg == "--grupo" and i + 1 < len(sys.argv):
            grupo = sys.argv[i + 1]
        if arg == "--app" and i + 1 < len(sys.argv):
            app = sys.argv[i + 1]

    print()
    print(f"{NEGRITA}{'=' * 72}{FIN}")
    print(f"{NEGRITA}  EMPAQUETADO Y DESPLIEGUE — RÍO CLARO{FIN}")
    print(f"{NEGRITA}{'=' * 72}{FIN}\n")

    ok, mensaje = crear_paquete()
    if not ok:
        print(f"\n{ROJO}{mensaje}{FIN}\n")
        return 1
    print(f"\n{VERDE}Paquete listo:{FIN} {mensaje}")

    if "--solo-paquete" in sys.argv:
        print(f"{GRIS}Se pidió solo empaquetar; no se despliega.{FIN}\n")
        return 0

    codigo = desplegar(app, grupo)
    if codigo == 0:
        print()
        print(f"{NEGRITA}{'=' * 72}{FIN}")
        print(f"  {VERDE}Listo.{FIN} Compruebe la aplicación en:")
        print(f"  {NEGRITA}https://{app}.azurewebsites.net{FIN}")
        print(f"{NEGRITA}{'=' * 72}{FIN}")
        print(f"\n{GRIS}El primer arranque tarda 1-2 minutos: Oryx está instalando")
        print(f"las dependencias. Para ver el registro:")
        print(f"  az webapp log tail --name {app} --resource-group {grupo}{FIN}\n")
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
