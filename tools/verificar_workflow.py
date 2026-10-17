"""
Verifica el flujo de GitHub Actions (.github/workflows/deploy.yml).

POR QUÉ ESTA PRUEBA EXISTE
--------------------------
Este archivo tenía un error real que habría impedido el despliegue: instalaba
las dependencias con

    pip install --target=".python_packages/lib/site-packages" -r requirements.txt

Ese mecanismo es el de App Service en **Windows**. En App Service Linux con una
imagen "Blessed" (la del desplegable Stack, como PYTHON:3.11), Oryx crea su
propio entorno virtual (`antenv`) y NO añade esa carpeta al `sys.path`. El
resultado era «ModuleNotFoundError: No module named 'streamlit'» con el
despliegue marcado como exitoso: el peor tipo de fallo, porque nadie sabe
dónde mirar.

Como el flujo solo se ejecuta al subir a GitHub, un error aquí no se descubre
hasta el día del despliegue. Esta comprobación lo detecta sin necesidad de
repositorio ni de Azure.

Uso:
    python tools/verificar_workflow.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent
WORKFLOW = RAIZ / ".github" / "workflows" / "deploy.yml"

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
        for l in str(detalle).splitlines()[:8]:
            print(f"        {GRIS}{l}{FIN}")


def main() -> int:
    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{NEGRITA}  VERIFICACIÓN DEL FLUJO DE GITHUB ACTIONS{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}\n")

    if not WORKFLOW.exists():
        print(f"  {AMARILLO}No existe {WORKFLOW.relative_to(RAIZ)}{FIN}")
        print(f"  {GRIS}Es opcional: sin él, despliegue con 'az webapp deploy'.{FIN}\n")
        # No es un fallo: el despliegue por ZIP es la otra vía válida.
        return 0

    texto = WORKFLOW.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Las comprobaciones de CONTENIDO se hacen sobre el archivo sin comentarios.
    #
    # Esto ya ha hecho falta cuatro veces en este proyecto: el propio comentario
    # que explica por qué NO se usa algo (aquí, "--target=.python_packages")
    # hacía saltar la comprobación como falso positivo. Buscar una cadena en
    # todo el texto no distingue el código de la documentación que lo rodea.
    # ------------------------------------------------------------------
    lineas_codigo = [
        l for l in texto.splitlines()
        if l.strip() and not l.lstrip().startswith("#")
    ]
    codigo = "\n".join(lineas_codigo)

    # ------------------------------------------------------------------
    print("1. ESTRUCTURA DEL ARCHIVO")
    for clave, descripcion in (
        ("name:", "tiene nombre"),
        ("on:", "se dispara con algún evento"),
        ("jobs:", "declara trabajos"),
        ("runs-on:", "declara el sistema operativo del ejecutor"),
        ("actions/checkout", "descarga el repositorio"),
    ):
        revisar(f"El flujo {descripcion}", clave in codigo)

    revisar(
        "Se dispara al hacer push a main o manualmente",
        "branches: [main]" in codigo or "workflow_dispatch" in codigo,
    )

    # ------------------------------------------------------------------
    print("\n2. MECANISMO DE INSTALACIÓN DE DEPENDENCIAS")
    # El error real: --target es para App Service Windows; en Linux no funciona.
    revisar(
        "NO usa --target=.python_packages (mecanismo de App Service Windows)",
        "--target" not in codigo and ".python_packages" not in codigo,
        "En App Service Linux (imagen Blessed), Oryx crea su propio entorno\n"
        "(antenv) y no añade esa carpeta al sys.path. La aplicación fallaría con\n"
        "'No module named streamlit' aunque el despliegue dijera que fue bien.",
    )
    revisar(
        "Instala desde requirements.txt para poder verificar",
        re.search(r"pip install -r requirements\.txt", codigo) is not None,
        "Las comprobaciones previas necesitan las dependencias instaladas.",
    )

    # ------------------------------------------------------------------
    print("\n3. COMPROBACIONES ANTES DE DESPLEGAR")
    scripts_esperados = [
        ("tools/autotest.py", "la lógica del negocio"),
        ("tools/verificar_dependencias.py", "requirements.txt completo"),
        ("tools/probar_provision.py", "el script de provisión"),
    ]
    for script, descripcion in scripts_esperados:
        revisar(
            f"Ejecuta {Path(script).name} ({descripcion})",
            script in codigo,
        )
        revisar(
            f"El script {Path(script).name} existe de verdad",
            (RAIZ / script).exists(),
            "Un flujo que llama a un script inexistente falla en el despliegue.",
        )

    revisar(
        "Verifica que la aplicación compile",
        "py_compile" in codigo,
    )
    revisar(
        "Comprueba que no se filtre el archivo .env",
        ".env" in codigo and "git ls-files" in codigo,
        "Si alguien sube el .env por descuido, el despliegue se detiene.",
    )
    revisar(
        "Comprueba que los datos y las facturas se despliegan",
        "catalogo_unificado.csv" in codigo and "factura_limpia.pdf" in codigo,
        "Sin ellos la aplicación arranca pero el asistente no responde.",
    )

    # ------------------------------------------------------------------
    print("\n4. ORDEN DE LOS PASOS")
    pos_instalar = codigo.find("pip install -r requirements.txt")
    pos_verificar = codigo.find("tools/autotest.py")
    pos_desplegar = codigo.find("azure/webapps-deploy")
    revisar(
        "Las comprobaciones van DESPUÉS de instalar las dependencias",
        -1 < pos_instalar < pos_verificar,
        "Si no, los scripts fallarían por falta de paquetes.",
    )
    revisar(
        "El despliegue va DESPUÉS de las comprobaciones",
        -1 < pos_verificar < pos_desplegar,
        "Así no se publica una versión que no pasa las pruebas.",
    )

    # ------------------------------------------------------------------
    print("\n5. CONFIGURACIÓN DEL DESPLIEGUE")
    revisar(
        "Usa azure/webapps-deploy",
        "azure/webapps-deploy" in codigo,
    )
    revisar(
        "Usa el perfil de publicación como secreto",
        "AZURE_WEBAPP_PUBLISH_PROFILE" in codigo and "secrets." in codigo,
        "El secreto se guarda en GitHub, no en el archivo.",
    )
    revisar(
        "El nombre de la aplicación coincide con el de la provisión",
        "rioclaro-ai901" in codigo,
        "Debe coincidir con cfg.app de tools/provision_azure.py.",
    )
    # La versión de Python debe coincidir con el runtime de App Service.
    m = re.search(r'PYTHON_VERSION:\s*"([\d.]+)"', codigo)
    version_flujo = m.group(1) if m else None
    revision = (RAIZ / "tools" / "provision_azure.py").read_text(encoding="utf-8")
    m2 = re.search(r'"PYTHON:([\d.]+)"', revision)
    version_provision = m2.group(1) if m2 else None
    revisar(
        f"La versión de Python coincide con la de App Service ({version_provision})",
        version_flujo == version_provision,
        f"flujo: {version_flujo} · provisión: {version_provision}\n"
        "Si difieren, el código podría funcionar en el ejecutor y fallar en el "
        "servidor (o al contrario).",
    )

    # ------------------------------------------------------------------
    print("\n6. SEGURIDAD DEL ARCHIVO")
    # Un secreto escrito directamente en el YAML quedaría visible en GitHub.
    sospechosos = re.findall(
        r'(?i)(?:password|secret|key|token|credential)\s*[:=]\s*["\']([^"\'${{}}]{16,})["\']',
        codigo,
    )
    revisar(
        "No hay credenciales escritas directamente en el flujo",
        not sospechosos,
        "\n".join(sospechosos) if sospechosos else
        "Debe usar ${{ secrets.NOMBRE }}.",
    )

    # ------------------------------------------------------------------
    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    total = _ok + _fallo
    if _fallo == 0:
        print(f"{VERDE}RESULTADO: {_ok}/{total} comprobaciones correctas.{FIN}")
        print("El flujo de despliegue continuo es correcto.")
        print(f"{NEGRITA}{'=' * 74}{FIN}")
        return 0
    print(f"{ROJO}RESULTADO: {_fallo} de {total} comprobaciones FALLARON.{FIN}")
    print(f"{AMARILLO}El despliegue por GitHub Actions fallaría.{FIN}")
    print(f"{GRIS}Recuerde: la otra vía (az webapp deploy con un ZIP) no usa este"
          f" archivo.{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
