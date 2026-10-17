"""
Comprueba que requirements.txt incluya TODO lo que el código importa.

POR QUÉ ESTA PRUEBA EXISTE
--------------------------
En la computadora de desarrollo los paquetes suelen estar instalados en todo el
entorno, así que la aplicación funciona aunque `requirements.txt` esté
incompleto. En App Service es distinto: Oryx crea un entorno virtual y ejecuta
`pip install -r requirements.txt`. Si falta un paquete, la aplicación no arranca
y el navegador solo muestra «Application Error».

Esta comprobación:

  1. Lee todos los `import` de los archivos .py del proyecto con el módulo ast
     (no con expresiones regulares, que confundirían un import dentro de una
     cadena de texto).
  2. Distingue los módulos de la biblioteca estándar de los de terceros.
  3. Contrasta los terceros contra lo declarado en requirements.txt.

Uso:
    python tools/verificar_dependencias.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent

VERDE, ROJO, AMARILLO, GRIS, NEGRITA, FIN = (
    "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[1m", "\033[0m",
)

_ok = 0
_fallo = 0
_aviso = 0


def revisar(titulo: str, condicion: bool, detalle: str = "") -> None:
    global _ok, _fallo
    if condicion:
        _ok += 1
        print(f"  {VERDE}OK{FIN}    {titulo}")
    else:
        _fallo += 1
        print(f"  {ROJO}FALLA{FIN} {titulo}")
    if detalle:
        for l in str(detalle).splitlines()[:10]:
            print(f"        {GRIS}{l}{FIN}")


def avisar(titulo: str, detalle: str = "") -> None:
    global _aviso
    _aviso += 1
    print(f"  {AMARILLO}AVISO{FIN} {titulo}")
    if detalle:
        for l in str(detalle).splitlines()[:6]:
            print(f"        {GRIS}{l}{FIN}")


# ---------------------------------------------------------------------------
# Mapa de nombre de módulo -> nombre de paquete en PyPI
# ---------------------------------------------------------------------------
# Muchos paquetes se importan con un nombre distinto del que se instala. Sin
# este mapa, la comprobación daría falsos positivos en todos ellos.
MODULO_A_PAQUETE = {
    "streamlit": "streamlit",
    "pandas": "pandas",
    "numpy": "numpy",
    "PIL": "Pillow",
    "azure": "azure-*",          # se resuelve por subpaquete abajo
    "cv2": "opencv-python",
    "dotenv": "python-dotenv",
    "yaml": "PyYAML",
    "dateutil": "python-dateutil",
    "sklearn": "scikit-learn",
    "pypdf": "pypdf",
}

# Subpaquetes de `azure` que corresponden a paquetes distintos.
AZURE_SUBMODULOS = {
    "identity": "azure-identity",
    "core": "azure-core",
    "ai.projects": "azure-ai-projects",
    "ai.contentunderstanding": "azure-ai-contentunderstanding",
    "ai.textanalytics": "azure-ai-textanalytics",
    "cognitiveservices.speech": "azure-cognitiveservices-speech",
    "keyvault.secrets": "azure-keyvault-secrets",
    "storage.blob": "azure-storage-blob",
}

# Módulos que el proyecto usa a propósito como OPCIONALES (se importan dentro de
# un try/except o solo en una ruta concreta). No deben contar como faltantes.
OPCIONALES_CONOCIDOS = {
    "azure.keyvault.secrets",   # solo si KEY_VAULT_URI está definido
    "ffmpeg",
}

# Módulos DEL PROPIO PROYECTO. No son paquetes de terceros y no deben aparecer
# en requirements.txt.
#
# POR QUÉ HACE FALTA ESTA LISTA: las herramientas de desarrollo importan la
# aplicación para probarla (por ejemplo, el diagnóstico llama a
# extraer_factura). Un verificador que no distinga un módulo local de un paquete
# instalable reporta un falso positivo y manda a buscar una dependencia que no
# existe. Ocurrió con `import app` en tools/diagnostico_azure.py.
MODULOS_PROPIOS = {
    "app",
    "rio_claro",
    # Portal del usuario: personas, tareas y textos en lenguaje llano.
    "portal",
    # Piezas de interfaz compartidas (estilos, tarjetas, navegación).
    "ui",
}


def modulo_estandar(nombre: str) -> bool:
    """¿Es un módulo de la biblioteca estándar?"""
    return nombre in sys.stdlib_module_names


def imports_de(archivo: Path) -> set[tuple[str, int]]:
    """
    Devuelve el conjunto de (módulo, línea) importados por un archivo Python.

    Se usa ast para no confundir un import que aparece dentro de una cadena de
    texto (por ejemplo, el código de ejemplo en los mensajes de la aplicación).
    """
    try:
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        print(f"  {ROJO}No se pudo analizar {archivo.name}: {exc}{FIN}")
        return set()

    encontrados: set[tuple[str, int]] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                encontrados.add((alias.name, nodo.lineno))
        elif isinstance(nodo, ast.ImportFrom):
            # Ignorar importaciones relativas (from . import x)
            if nodo.level and nodo.level > 0:
                continue
            if nodo.module:
                encontrados.add((nodo.module, nodo.lineno))
    return encontrados


def normalizar_a_paquete(modulo: str) -> str | None:
    """
    Traduce un nombre de módulo al paquete que hay que instalar.

    Devuelve None si es de la biblioteca estándar o si es el propio proyecto.
    """
    raiz = modulo.split(".")[0]

    if modulo_estandar(raiz):
        return None
    if raiz in MODULOS_PROPIOS:       # módulos del propio proyecto
        return None

    # Herramientas del propio repositorio en tools/. Se importan entre sí
    # (por ejemplo, desplegar.py reutiliza encontrar_az de provision_azure), y
    # no son paquetes instalables.
    if raiz in ("provision_azure", "capturar_pantallas", "probar_app_funcional",
                "probar_provision", "verificar_todo", "desplegar"):
        return None

    if raiz == "azure":
        # Se busca el subpaquete más específico que coincida
        for sub, paquete in sorted(AZURE_SUBMODULOS.items(),
                                   key=lambda x: -len(x[0])):
            if modulo == f"azure.{sub}" or modulo.startswith(f"azure.{sub}."):
                return paquete
        return "azure-*"

    if raiz in MODULO_A_PAQUETE:
        return MODULO_A_PAQUETE[raiz]

    # Sin mapa: se asume que el nombre del paquete es el del módulo. Es lo
    # habitual y, si no lo fuera, la prueba del entorno limpio lo detectaría.
    return raiz


def leer_requirements() -> tuple[set[str], list[str]]:
    """Devuelve (nombres de paquete declarados, líneas originales)."""
    ruta = RAIZ / "requirements.txt"
    if not ruta.exists():
        return set(), []

    declarados: set[str] = set()
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    for linea in lineas:
        limpia = linea.split("#")[0].strip()
        if not limpia or limpia.startswith("-"):
            continue
        # Quitar el especificador de versión: "paquete>=1.2" -> "paquete"
        nombre = re.split(r"[<>=!\[;]", limpia)[0].strip()
        if nombre:
            declarados.add(nombre.lower())
    return declarados, lineas


def main() -> int:
    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{NEGRITA}  VERIFICACIÓN DE DEPENDENCIAS (requirements.txt){FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{GRIS}En App Service, Oryx instala SOLO lo que declara requirements.txt.{FIN}")
    print(f"{GRIS}Un paquete que falte impide arrancar la aplicación.{FIN}\n")

    declarados, lineas = leer_requirements()
    revisar("Existe requirements.txt", bool(lineas),
            f"{len(lineas)} líneas" if lineas else "archivo ausente o vacío")
    revisar("Declara al menos 8 paquetes", len(declarados) >= 8,
            ", ".join(sorted(declarados)))

    # ------------------------------------------------------------------
    # Recolectar imports de todo el código desplegable.
    # Se incluyen los scripts de tools/ porque también se despliegan y el
    # usuario puede ejecutarlos en la consola de App Service.
    archivos = sorted(RAIZ.glob("*.py")) + sorted((RAIZ / "tools").glob("*.py"))
    revisar("Hay archivos .py que analizar", len(archivos) >= 5,
            f"{len(archivos)} archivos")

    por_paquete: dict[str, list[str]] = {}
    for archivo in archivos:
        for modulo, linea in imports_de(archivo):
            paquete = normalizar_a_paquete(modulo)
            if paquete is None:
                continue
            etiqueta = f"{archivo.name}:{linea} -> {modulo}"
            por_paquete.setdefault(paquete, []).append(etiqueta)

    print(f"\n{GRIS}Paquetes de terceros detectados en el código:{FIN}")
    for paquete in sorted(por_paquete):
        estado = "declarado" if paquete.lower() in declarados else "FALTA"
        color = VERDE if estado == "declarado" else ROJO
        print(f"  {color}{estado:10s}{FIN} {paquete}")

    # ------------------------------------------------------------------
    print()
    faltantes = {
        p: usos for p, usos in por_paquete.items()
        if p.lower() not in declarados
        and not p.endswith("-*")
        and p not in MODULOS_PROPIOS
    }
    if faltantes:
        revisar(
            "Todos los paquetes usados están declarados en requirements.txt",
            False,
            "\n".join(
                f"{p}  (usado en {usos[0]})" for p, usos in sorted(faltantes.items())
            ) + "\n\nEn App Service la aplicación NO arrancaría. "
                "Agregue estos paquetes a requirements.txt.",
        )
    else:
        revisar("Todos los paquetes usados están declarados en requirements.txt",
                True, f"{len(por_paquete)} paquetes de terceros en uso")

    # ------------------------------------------------------------------
    # Coherencia entre los módulos del proyecto y el paquete de despliegue.
    #
    # Un módulo local que no se sube a App Service hace que la app desplegada
    # falle con ModuleNotFoundError, y eso solo se descubre al probarla ya en
    # Azure. Ocurrió al añadir portal.py y ui.py: el empaquetador tenía la
    # lista de archivos escrita a mano y no los incluía.
    #
    # Ahora el empaquetador los descubre solo; esta comprobación vigila que
    # siga haciéndolo.
    # ------------------------------------------------------------------
    try:
        sys.path.insert(0, str(RAIZ / "tools"))
        import importlib

        import desplegar as empaquetador
        importlib.reload(empaquetador)

        modulos_locales = {
            a.stem for a in RAIZ.glob("*.py")
            if not a.stem.startswith("_")
        }
        incluidos = {Path(m).stem for m in empaquetador.modulos_python()}
        fuera = modulos_locales - incluidos

        revisar(
            "El paquete de despliegue incluye todos los módulos del proyecto",
            not fuera,
            (f"Fuera del paquete: {sorted(fuera)}\n\n"
             "La app desplegada fallaría con ModuleNotFoundError.")
            if fuera else
            f"{len(incluidos)} módulos: {', '.join(sorted(incluidos))}",
        )
    except Exception as exc:
        revisar(
            "Se pudo comprobar el paquete de despliegue",
            False,
            f"{type(exc).__name__}: {str(exc)[:150]}",
        )

    # ------------------------------------------------------------------
    # Comprobación inversa: paquetes declarados que no se usan directamente.
    # No es un error (pueden ser dependencias transitivas necesarias, como
    # azure-core o azure-storage-blob), pero conviene saberlo.
    print()
    sin_uso_directo = sorted(
        d for d in declarados
        if not any(d == p.lower() for p in por_paquete)
        and not d.startswith("azure-")          # los usa el SDK por dentro
    )
    if sin_uso_directo:
        avisar(
            "Paquetes declarados que no se importan directamente",
            "\n".join(sin_uso_directo) +
            "\nPuede ser correcto (dependencias transitivas). Revise que no "
            "sean innecesarios.",
        )
    else:
        revisar("No hay paquetes declarados sin uso aparente", True)

    # ------------------------------------------------------------------
    # Comprobación crítica: los cuatro servicios de Azure del proyecto deben
    # estar declarados. Sin ellos la aplicación arranca pero no funciona.
    print()
    obligatorios = {
        "azure-ai-projects": "Microsoft Foundry (IA generativa y agentes)",
        "azure-ai-contentunderstanding": "Content Understanding (facturas)",
        "azure-ai-textanalytics": "Azure AI Language (texto)",
        "azure-cognitiveservices-speech": "Azure Speech (voz)",
        "azure-identity": "Autenticación (DefaultAzureCredential)",
        "azure-keyvault-secrets": "Key Vault (secretos)",
    }
    for paquete, descripcion in obligatorios.items():
        revisar(
            f"Declara {paquete} ({descripcion})",
            paquete.lower() in declarados,
        )

    # ------------------------------------------------------------------
    # Comprobación de que las versiones mínimas son alcanzables.
    #
    # Es fácil escribir "azure-ai-projects>=2.3.0" copiando de la documentación
    # y que la versión no exista. Aquí se comprueba que el especificador tenga
    # forma válida; la existencia real de la versión la confirma pip al instalar.
    print()
    problemas_version = []
    for linea in lineas:
        limpia = linea.split("#")[0].strip()
        if not limpia or limpia.startswith("-"):
            continue
        if not re.match(r"^[A-Za-z0-9_.\-\[\]]+\s*(>=|==|~=|>)\s*[0-9]", limpia):
            problemas_version.append(limpia)
    revisar(
        "Todos los paquetes declaran una versión mínima válida",
        not problemas_version,
        "\n".join(problemas_version) if problemas_version else
        "Declarar versiones mínimas evita que pip instale una versión "
        "incompatible con el código.",
    )

    # Aviso si algún paquete no tiene versión mínima: en App Service conviene
    # fijarla para que el despliegue sea reproducible.
    sin_version = []
    for linea in lineas:
        limpia = linea.split("#")[0].strip()
        if not limpia or limpia.startswith("-"):
            continue
        if not re.search(r"[<>=~]", limpia):
            sin_version.append(limpia)
    if sin_version:
        avisar(
            "Paquetes sin versión mínima fijada",
            "\n".join(sin_version) +
            "\nNo es un error, pero sin versión mínima un despliegue futuro "
            "podría instalar una versión incompatible.",
        )

    # ------------------------------------------------------------------
    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    total = _ok + _fallo
    if _fallo == 0:
        print(f"{VERDE}RESULTADO: {_ok}/{total} comprobaciones correctas.{FIN}")
        if _aviso:
            print(f"{AMARILLO}{_aviso} aviso(s) que no impiden el despliegue.{FIN}")
        print("requirements.txt está completo: la aplicación arrancará en App Service.")
        print()
        print(f"{GRIS}Esta comprobación es estática. Para verificar de verdad que las")
        print(f"versiones existen y se instalan, cree un entorno limpio:{FIN}")
        print(f"{GRIS}  python -m venv .venv && .venv/Scripts/pip install -r requirements.txt{FIN}")
        print(f"{NEGRITA}{'=' * 74}{FIN}")
        return 0
    print(f"{ROJO}RESULTADO: {_fallo} de {total} comprobaciones FALLARON.{FIN}")
    print(f"{ROJO}Faltan dependencias: la aplicación NO arrancaría en App Service.{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
