"""
Verificación integral del proyecto Río Claro AI-901.

Ejecuta TODAS las comprobaciones que no necesitan Azure, en orden, y da un
resumen final. Es el comando que conviene correr antes de cada ensayo de la
demostración y justo antes de entregar.

Uso:
    python tools/verificar_todo.py

Código de salida 0 = todo bien. Distinto de 0 = algo falla.
"""

from __future__ import annotations

import importlib
import py_compile
import re
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent
PY = sys.executable

VERDE, ROJO, AMARILLO, GRIS, CIAN, NEGRITA, FIN = (
    "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[96m",
    "\033[1m", "\033[0m",
)

secciones: list[tuple[str, bool, str]] = []


def cabecera(n: int, titulo: str) -> None:
    print(f"\n{CIAN}{'─' * 74}{FIN}")
    print(f"{CIAN}{NEGRITA}{n}. {titulo}{FIN}")
    print(f"{CIAN}{'─' * 74}{FIN}")


def linea(ok: bool, texto: str, detalle: str = "") -> None:
    marca = f"{VERDE}OK{FIN}   " if ok else f"{ROJO}FALLA{FIN}"
    print(f"  {marca} {texto}")
    if detalle:
        print(f"         {GRIS}{detalle}{FIN}")


def ejecutar(script: str) -> tuple[bool, str]:
    """Corre otro script de verificación y devuelve (exito, ultima linea util)."""
    ruta = RAIZ / script
    if not ruta.exists():
        return False, "no existe"
    proc = subprocess.run(
        [PY, str(ruta)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(RAIZ),
    )
    salida = (proc.stdout or "") + (proc.stderr or "")
    utiles = [
        l.strip()
        for l in salida.splitlines()
        if "RESULTADO" in l or "Correctas:" in l or "Fallidas:" in l
    ]
    return proc.returncode == 0, " | ".join(utiles[-2:]) if utiles else "sin resumen"


def probar_arranque(timeout: float = 75.0) -> tuple[bool, str]:
    """
    Levanta la aplicación en un puerto libre y consulta su endpoint de salud.

    Es la comprobación más valiosa del conjunto: demuestra que Streamlit
    arranca de verdad con este código, no solo que el archivo compila. Cubre
    fallos que `py_compile` no ve, como un import mal escrito en tiempo de
    ejecución o un error en la configuración de Streamlit.

    Streamlit expone /_stcore/health, que responde 'ok' cuando está listo.
    """
    import socket
    import time
    import urllib.error
    import urllib.request

    # Buscar un puerto libre
    puerto = None
    for candidato in range(8971, 9020):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", candidato)) != 0:
                puerto = candidato
                break
    if puerto is None:
        return False, "no se encontró un puerto libre"

    proceso = subprocess.Popen(
        [PY, "-m", "streamlit", "run", str(RAIZ / "app.py"),
         "--server.port", str(puerto), "--server.address", "127.0.0.1",
         "--server.headless", "true"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(RAIZ),
    )
    try:
        url = f"http://127.0.0.1:{puerto}/_stcore/health"
        inicio = time.time()
        ultimo_error = ""
        while time.time() - inicio < timeout:
            if proceso.poll() is not None:
                return False, (
                    f"el proceso terminó con código {proceso.returncode}.\n"
                    "Ejecute 'streamlit run app.py' a mano para ver el error."
                )
            try:
                with urllib.request.urlopen(url, timeout=5) as r:
                    cuerpo = r.read().decode(errors="replace").strip()
                if r.status == 200 and "ok" in cuerpo.lower():
                    segundos = time.time() - inicio
                    return True, f"puerto {puerto} · respondió 'ok' en {segundos:.1f}s"
                ultimo_error = f"HTTP {r.status}: {cuerpo[:60]}"
            except (urllib.error.URLError, OSError) as exc:
                ultimo_error = str(exc)[:80]
            time.sleep(0.8)
        return False, f"no respondió en {timeout:.0f}s (último: {ultimo_error})"
    finally:
        try:
            proceso.terminate()
            proceso.wait(timeout=10)
        except Exception:
            try:
                proceso.kill()
            except Exception:
                pass


def main() -> int:
    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{NEGRITA}  VERIFICACIÓN INTEGRAL — PROYECTO AI-901 — RÍO CLARO{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")

    # -----------------------------------------------------------------
    cabecera(1, "ESTRUCTURA DEL PROYECTO")
    obligatorios = [
        "app.py", "rio_claro.py", "requirements.txt", "startup.sh",
        ".streamlit/config.toml", ".env.example", ".gitignore",
        "README.md", "ENTREGA.md", "GUIA_DESPLIEGUE.md",
        "data/catalogo_unificado.csv",
        "data/politicas_y_pedidos_activos.txt",
        "data/historial_quejas.jsonl",
        "samples/factura_limpia.pdf",
        "samples/factura_final2.pdf",
        "samples/factura_monto_borroso.jpg",
        "samples/factura_foto_borrosa.jpg",
        "docs/instrucciones_agente.txt",
        "tools/autotest.py",
        "tools/probar_provision.py",
        "tools/probar_app_funcional.py",
        "tools/probar_directorio_trabajo.py",
        "tools/probar_errores_azure.py",
        "tools/verificar_dependencias.py",
        "tools/verificar_workflow.py",
        "tools/verificar_entrega.py",
        "tools/provision_azure.py",
        "tools/diagnostico_azure.py",
        "tools/generar_capturas_entrega.py",
    ]
    faltan = [f for f in obligatorios if not (RAIZ / f).exists()]
    todo_ok = not faltan
    linea(todo_ok, f"Los {len(obligatorios)} archivos esenciales existen",
          "" if todo_ok else "faltan: " + ", ".join(faltan))
    secciones.append(("Estructura", todo_ok, f"{len(obligatorios) - len(faltan)}/{len(obligatorios)}"))

    # -----------------------------------------------------------------
    cabecera(2, "SINTAXIS DE TODO EL CÓDIGO PYTHON")
    fallos = []
    for archivo in sorted(RAIZ.glob("*.py")) + sorted((RAIZ / "tools").glob("*.py")):
        try:
            py_compile.compile(str(archivo), doraise=True)
        except py_compile.PyCompileError as exc:
            fallos.append(f"{archivo.name}: {exc}")
    ok = not fallos
    linea(ok, "Todos los archivos .py compilan",
          "" if ok else "\n".join(fallos))
    secciones.append(("Sintaxis", ok, f"{len(fallos)} error(es)"))

    # -----------------------------------------------------------------
    cabecera(3, "DEPENDENCIAS INSTALADAS")
    modulos = [
        "streamlit", "pandas",
        "azure.identity", "azure.ai.projects",
        "azure.ai.contentunderstanding", "azure.ai.textanalytics",
        "azure.cognitiveservices.speech", "azure.keyvault.secrets",
    ]
    ausentes = []
    for m in modulos:
        try:
            importlib.import_module(m)
        except ImportError:
            ausentes.append(m)
    ok = not ausentes
    linea(ok, f"Los {len(modulos)} módulos necesarios están instalados",
          "" if ok else "faltan: " + ", ".join(ausentes) + "\nEjecute: pip install -r requirements.txt")
    secciones.append(("Dependencias", ok, f"{len(modulos) - len(ausentes)}/{len(modulos)}"))

    # -----------------------------------------------------------------
    cabecera(4, "SEGURIDAD: NINGUNA CLAVE EN EL CÓDIGO")
    # Patrón de asignación de una clave real (16+ caracteres alfanuméricos)
    patron = re.compile(
        r"""(api[_-]?key|subscription[_-]?key|password|secret|token)"""
        r"""\s*[:=]\s*["'][A-Za-z0-9_\-]{16,}["']""",
        re.I,
    )
    sospechosos = []
    for archivo in list(RAIZ.glob("*.py")) + list((RAIZ / "tools").glob("*.py")) + list(RAIZ.glob("*.sh")):
        for i, l in enumerate(archivo.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if l.lstrip().startswith("#"):
                continue
            if patron.search(l):
                sospechosos.append(f"{archivo.name}:{i}")
    ok = not sospechosos
    linea(ok, "No hay credenciales escritas en el código",
          "" if ok else "revisar: " + ", ".join(sospechosos))
    secciones.append(("Sin claves en código", ok, f"{len(sospechosos)} sospechoso(s)"))

    # -----------------------------------------------------------------
    cabecera(5, "SEGURIDAD: EL .env ESTÁ PROTEGIDO")
    ignorado = False
    if (RAIZ / ".gitignore").exists():
        contenido = (RAIZ / ".gitignore").read_text(encoding="utf-8")
        ignorado = bool(re.search(r"^\.env$", contenido, re.M))
    ok = ignorado
    linea(ok, ".env figura en .gitignore",
          "Si el .env se filtra a un repositorio público, alguien puede gastar su crédito de Azure.")
    secciones.append((".env ignorado", ok, ""))

    # -----------------------------------------------------------------
    cabecera(6, "SEGURIDAD: CONFIGURACIÓN DE STREAMLIT")
    config = RAIZ / ".streamlit" / "config.toml"
    problemas = []
    if config.exists():
        texto = config.read_text(encoding="utf-8")
        # OJO: se ancla al inicio de línea y se ignoran los comentarios.
        # Si no, el propio comentario que explica "NO se pone enableCORS = false"
        # haría saltar la comprobación como falso positivo.
        activas = [
            l for l in texto.splitlines()
            if l.strip() and not l.lstrip().startswith("#")
        ]
        cuerpo = "\n".join(activas)
        if re.search(r"^\s*enableCORS\s*=\s*false", cuerpo, re.I | re.M):
            problemas.append(
                "enableCORS = false le dice a Streamlit que acepte conexiones "
                "WebSocket desde cualquier origen. Use enableCORS = true junto "
                "con corsAllowedOrigins."
            )
        if not re.search(r"^\s*enableXsrfProtection\s*=\s*true", cuerpo, re.I | re.M):
            problemas.append("Falta enableXsrfProtection = true.")
        if re.search(r"^\s*developmentMode\s*=\s*true", cuerpo, re.I | re.M):
            problemas.append("developmentMode = true impide usar --server.port.")
        if not re.search(r"^\s*corsAllowedOrigins\s*=", cuerpo, re.I | re.M):
            problemas.append("Falta corsAllowedOrigins (lista blanca de orígenes).")
    else:
        problemas.append("No existe .streamlit/config.toml")
    ok = not problemas
    linea(ok, "La configuración de Streamlit es segura",
          "" if ok else "\n".join(problemas))
    secciones.append(("Config Streamlit", ok, ""))

    # -----------------------------------------------------------------
    cabecera(7, "SCRIPT DE ARRANQUE (startup.sh)")
    # Estas tres comprobaciones existen porque los tres errores ya ocurrieron:
    #   * --server.enableCORS false anulaba la configuración segura del .toml
    #   * un guion largo (—) en el echo podía romper el arranque en UTF-8
    #   * los finales de línea CRLF rompen los .sh en App Service
    arranque = RAIZ / "startup.sh"
    problemas_arranque = []
    if not arranque.exists():
        problemas_arranque.append("No existe startup.sh")
    else:
        crudo = arranque.read_bytes()
        if b"\r\n" in crudo:
            problemas_arranque.append(
                "Tiene finales de línea CRLF. App Service fallará con "
                "'bad interpreter'. Guarde con finales LF."
            )
        texto_arranque = crudo.decode("utf-8", errors="replace")

        # Las comprobaciones de contenido se hacen SOLO sobre las líneas
        # ejecutables. Los comentarios de este archivo mencionan a propósito
        # "--server.enableCORS" para explicar por qué NO se usa; si se buscara
        # en todo el texto, la propia documentación dispararía el error.
        # (Este falso positivo ya ocurrió dos veces en este proyecto.)
        ejecutables = [
            l for l in texto_arranque.splitlines()
            if l.strip() and not l.lstrip().startswith("#")
        ]
        cuerpo_arranque = "\n".join(ejecutables)

        if re.search(r"--server\.enableCORS", cuerpo_arranque, re.I):
            problemas_arranque.append(
                "Pasa --server.enableCORS en la línea de comandos, lo que ANULA "
                "la configuración segura de .streamlit/config.toml y acepta "
                "conexiones desde cualquier origen. Elimine ese argumento."
            )
        # Caracteres no ASCII fuera de comentarios: el entorno de arranque
        # puede no ser UTF-8 y el script fallaría antes de llegar a Streamlit.
        for i, l in enumerate(ejecutables, 1):
            no_ascii = [c for c in l if ord(c) > 127]
            if no_ascii:
                problemas_arranque.append(
                    f"Línea ejecutable con caracteres no ASCII {no_ascii!r} "
                    f"(puede romper el arranque): {l.strip()[:60]}"
                )
        if "streamlit run" not in cuerpo_arranque:
            problemas_arranque.append("No arranca Streamlit.")
        if "--server.port" not in cuerpo_arranque:
            problemas_arranque.append(
                "No fija --server.port; App Service no sabrá en qué puerto escuchar."
            )
        # El script usa "app.py" con ruta relativa y Streamlit busca su
        # configuración en el directorio de trabajo. Sin un "cd" al directorio
        # del propio script, arrancar desde otro sitio falla y la configuración
        # de seguridad (.streamlit/config.toml) no se aplica.
        if not re.search(r"^\s*cd\s", cuerpo_arranque, re.M):
            problemas_arranque.append(
                "No hace 'cd' al directorio del script. Con una ruta relativa "
                "('app.py'), arrancar desde otro directorio falla, y Streamlit "
                "no encontraría .streamlit/config.toml."
            )
    ok = not problemas_arranque
    linea(ok, "startup.sh es correcto y seguro",
          "" if ok else "\n".join(problemas_arranque))
    secciones.append(("Script de arranque", ok, ""))

    # -----------------------------------------------------------------
    cabecera(8, "MOTOR DEL NEGOCIO (41 pruebas)")
    ok, resumen = ejecutar("tools/autotest.py")
    linea(ok, "La lógica del negocio pasa todas las pruebas", resumen)
    secciones.append(("Motor del negocio", ok, resumen))

    # -----------------------------------------------------------------
    cabecera(9, "PROVISIONADOR DE AZURE")
    # Prueba con ejecutor simulado: verifica la lista de comandos, el orden y el
    # manejo de errores, sin tocar Azure. Sustituye a la validación estática que
    # se hacía del antiguo script de bash.
    ok, resumen = ejecutar("tools/probar_provision.py")
    linea(
        ok,
        "El provisionador pasa sus 50 pruebas (con ejecutor simulado)",
        resumen,
    )
    # El modo ensayo no debe ejecutar nada: se comprueba que responda sin error
    prov = RAIZ / "tools" / "provision_azure.py"
    ensayo_ok = False
    if prov.exists():
        p = subprocess.run(
            [PY, str(prov), "--dry-run"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(RAIZ),
        )
        salida = (p.stdout or "")
        ensayo_ok = p.returncode == 0 and "no se creará nada" in salida
    linea(
        ensayo_ok,
        "El modo ensayo (--dry-run) funciona sin Azure",
        "Permite revisar los 33 comandos antes de ejecutarlos de verdad.",
    )
    secciones.append(("Provisionador", ok and ensayo_ok, resumen))

    # -----------------------------------------------------------------
    cabecera(10, "FACTURAS DE PRUEBA")
    ok, resumen = ejecutar("tools/verificar_facturas.py")
    linea(ok, "Las facturas PDF tienen capa de texto extraíble", resumen)
    # Además, el duplicado debe existir aunque se llame distinto
    dup_ok = (RAIZ / "samples" / "factura_final2.pdf").exists()
    linea(dup_ok, "Existe la factura duplicada con otro nombre (factura_final2.pdf)",
          "Es la que demuestra la detección de pagos duplicados.")
    secciones.append(("Facturas", ok and dup_ok, resumen))

    # ------------------------------------------------------------------
    cabecera(11, "ARRANQUE REAL DE LA APLICACIÓN")
    # Se levanta Streamlit en un puerto libre y se consulta su endpoint de
    # salud. Es la única comprobación que demuestra que la app arranca de
    # verdad, no solo que compila.
    arranque_ok, detalle_arranque = probar_arranque()
    linea(arranque_ok, "La aplicación arranca y responde por HTTP", detalle_arranque)
    secciones.append(("Arranque de la app", arranque_ok, detalle_arranque))

    # ------------------------------------------------------------------
    cabecera(12, "PRUEBA FUNCIONAL DE EXTREMO A EXTREMO")
    # Abre la app en un navegador real, activa el modo demo, recorre las 6
    # pestañas, pulsa los botones y SUBE las facturas de prueba para verificar
    # el flujo de duplicados. Es la única comprobación que detecta errores de
    # tiempo de ejecución dentro de los manejadores de eventos, y ya encontró
    # uno real: el caso de monto ilegible mostraba un monto confiable.
    #
    # Es la más lenta del conjunto (1-2 minutos), por eso va al final.
    funcional_ok, resumen_funcional = ejecutar("tools/probar_app_funcional.py")
    linea(
        funcional_ok,
        "La aplicación funciona de extremo a extremo",
        resumen_funcional or
        "recorrió las 6 pestañas, pulsó los botones y subió las 4 facturas de prueba",
    )
    secciones.append(("Prueba funcional", funcional_ok, resumen_funcional))

    # ------------------------------------------------------------------
    cabecera(13, "LA APP FUERA DEL DIRECTORIO DEL PROYECTO")
    # Azure App Service arranca la aplicación desde /home/site/wwwroot, y
    # Streamlit busca .streamlit/config.toml en el DIRECTORIO DE TRABAJO. Si el
    # código usara rutas relativas, funcionaría aquí y fallaría en Azure.
    # Esta prueba simula exactamente esa condición.
    cwd_ok, resumen_cwd = ejecutar("tools/probar_directorio_trabajo.py")
    linea(
        cwd_ok,
        "La aplicación funciona desde otro directorio (como en App Service)",
        resumen_cwd or "simula el arranque con /home/site/wwwroot como directorio",
    )
    secciones.append(("Directorio de trabajo", cwd_ok, resumen_cwd))

    # ------------------------------------------------------------------
    cabecera(14, "COMPORTAMIENTO CUANDO AZURE FALLA")
    # Es la prueba del peor escenario de la demostración: credenciales vencidas
    # o un endpoint mal escrito. Comprueba que la aplicación no se caiga, que el
    # error se traduzca a una instrucción en español y que no se vuelque la
    # enumeración de credenciales del SDK a la vista del evaluador.
    err_ok, resumen_err = ejecutar("tools/probar_errores_azure.py")
    linea(
        err_ok,
        "La aplicación degrada con dignidad si Azure falla",
        resumen_err or "arranca con endpoints inválidos y traduce los errores",
    )
    secciones.append(("Errores de Azure", err_ok, resumen_err))

    # ------------------------------------------------------------------
    cabecera(15, "DEPENDENCIAS DECLARADAS (requirements.txt)")
    # En App Service, Oryx instala ÚNICAMENTE lo que declara requirements.txt.
    # Como en la computadora de desarrollo los paquetes suelen estar instalados
    # en todo el entorno, la aplicación funciona aunque el archivo esté
    # incompleto: el fallo solo aparece al desplegar.
    dep_ok, resumen_dep = ejecutar("tools/verificar_dependencias.py")
    linea(
        dep_ok,
        "requirements.txt incluye todo lo que el código importa",
        resumen_dep or "contrasta los import reales contra lo declarado",
    )
    secciones.append(("Dependencias", dep_ok, resumen_dep))

    # ------------------------------------------------------------------
    cabecera(16, "FLUJO DE DESPLIEGUE CONTINUO (GitHub Actions)")
    # Este archivo tenía un error real: instalaba las dependencias con
    # --target=.python_packages, que es el mecanismo de App Service en WINDOWS.
    # En Linux, Oryx crea su propio entorno y no añade esa carpeta al sys.path,
    # así que la aplicación fallaba con "No module named streamlit" aunque el
    # despliegue dijera que había ido bien.
    # Como el flujo solo se ejecuta al subir a GitHub, un error aquí no se
    # descubre hasta el día del despliegue.
    wf_ok, resumen_wf = ejecutar("tools/verificar_workflow.py")
    linea(
        wf_ok,
        "El flujo de GitHub Actions desplegaría correctamente",
        resumen_wf or "verifica estructura, orden de pasos y seguridad",
    )
    secciones.append(("Flujo de despliegue", wf_ok, resumen_wf))

    # ------------------------------------------------------------------
    cabecera(17, "DOCUMENTO DE ENTREGA (requisitos del enunciado)")
    # El enunciado exige «un documento Markdown (Solo markdown, no se aceptará
    # otro formato)» con imágenes, la explicación del problema resuelto y las
    # seis preguntas de IA responsable «con evidencia de su propio prototipo».
    # Esta comprobación contrasta ENTREGA.md con esos requisitos.
    ent_ok, resumen_ent = ejecutar("tools/verificar_entrega.py")
    linea(
        ent_ok,
        "El documento de entrega cumple los requisitos del enunciado",
        resumen_ent or "formato, capturas, problema, cargas y seis principios",
    )
    secciones.append(("Documento de entrega", ent_ok, resumen_ent))

    # -----------------------------------------------------------------
    print(f"\n{NEGRITA}{'=' * 74}{FIN}")
    print(f"{NEGRITA}  RESUMEN{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    for nombre, ok, detalle in secciones:
        marca = f"{VERDE}OK{FIN}   " if ok else f"{ROJO}FALLA{FIN}"
        extra = f"  {GRIS}{detalle}{FIN}" if detalle else ""
        print(f"  {marca} {nombre}{extra}")

    fallidas = [n for n, ok, _ in secciones if not ok]
    print()
    if not fallidas:
        print(f"{VERDE}{NEGRITA}  Todo correcto: el proyecto está listo.{FIN}")
        print()
        print(f"{GRIS}  Comandos útiles:{FIN}")
        print(f"{GRIS}    python tools/diagnostico_azure.py    # comprobar Azure en local{FIN}")
        print(f"{GRIS}    python tools/probar_despliegue.py    # probar la app publicada{FIN}")
        print(f"{GRIS}    python tools/desplegar.py            # volver a desplegar{FIN}")
        print(f"{GRIS}    python tools/verificar_entrega.py    # revisar el documento{FIN}")
        print()
        print(f"{GRIS}  Apagar la aplicación cuando no la use "
              f"(Carlos: «que se pueda apagar»):{FIN}")
        print(f"{GRIS}    az webapp stop  -n rioclaro-ai901 -g rg-rio-claro-ai901{FIN}")
        print(f"{GRIS}    az webapp start -n rioclaro-ai901 -g rg-rio-claro-ai901{FIN}")
        print()
        return 0

    print(f"{ROJO}{NEGRITA}  {len(fallidas)} sección(es) con problemas: {', '.join(fallidas)}{FIN}")
    print()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
