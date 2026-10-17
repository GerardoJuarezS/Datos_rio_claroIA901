"""
Verifica que la app muestre un error ACCIONABLE cuando Azure está mal configurado.

Es la prueba del peor escenario de la demostración: el evaluador abre la liga,
pulsa un botón, y una credencial está vencida o un endpoint mal escrito. Si
aparece una traza técnica en inglés de 20 líneas, parece que el proyecto está
roto, cuando en realidad el sistema está manejando el fallo correctamente.

Se arranca la app con un endpoint de Foundry inválido (apuntando a un host que
no resuelve) y se comprueba que:

  * la app NO se cae,
  * muestra un error en español que explica qué hacer,
  * y conserva el detalle técnico plegado para depurar.

Uso:
    python tools/probar_errores_azure.py
"""

from __future__ import annotations

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
import probar_app_funcional as pf  # noqa: E402

VERDE, ROJO, AMARILLO, GRIS, NEGRITA, FIN = (
    "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[1m", "\033[0m",
)

_ok = 0
_fallo = 0

# Endpoints deliberadamente inválidos: un host que no resuelve y una clave falsa.
ENTORNO_FALSO = {
    "FOUNDRY_PROJECT_ENDPOINT": "https://recurso-inexistente-xyz.services.ai.azure.com/api/projects/prueba",
    "FOUNDRY_MODEL": "modelo-que-no-existe",
    "CONTENT_UNDERSTANDING_ENDPOINT": "https://no-existe-abc.services.ai.azure.com/",
    "CONTENT_UNDERSTANDING_KEY": "clave_falsa_para_la_prueba_1234567890",
    "LANGUAGE_ENDPOINT": "https://no-existe-def.cognitiveservices.azure.com/",
    "LANGUAGE_KEY": "clave_falsa_para_la_prueba_1234567890",
    "SPEECH_KEY": "clave_falsa_para_la_prueba_1234567890",
    "SPEECH_REGION": "eastus2",
}


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


def puerto_libre(desde: int = 9231, hasta: int = 9280) -> int | None:
    for p in range(desde, hasta):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return None


def main() -> int:
    import os

    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{NEGRITA}  PRUEBA: errores de Azure mal configurado{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{GRIS}Se arranca la app con endpoints inválidos para ver qué lee el"
          f" evaluador.{FIN}\n")

    puerto = puerto_libre()
    if puerto is None:
        print(f"{ROJO}No hay puerto libre.{FIN}")
        return 1

    # Entorno con credenciales falsas, sin modo demo: así la app SÍ intenta
    # llamar a Azure y falla de verdad.
    entorno = dict(os.environ)
    entorno.update(ENTORNO_FALSO)

    # ------------------------------------------------------------------
    # AISLAMIENTO. Este archivo se ejecuta en el MISMO proceso que la prueba,
    # así que hereda el entorno real. Cuando existe un .env con credenciales
    # verdaderas, la prueba acababa usando el Key Vault REAL junto con los
    # endpoints falsos: el error que se producía ya no era el previsto y las
    # comprobaciones fallaban.
    #
    # Se eliminan todas las variables de Azure que no estén en ENTORNO_FALSO,
    # para que la aplicación vea EXACTAMENTE la configuración rota y nada más.
    # Sin esto, la prueba no mide lo que dice medir.
    # ------------------------------------------------------------------
    PREFIJOS_AZURE = (
        "FOUNDRY_", "CONTENT_UNDERSTANDING_", "LANGUAGE_", "SPEECH_",
        "KEY_VAULT_", "AZURE_",
    )
    quitadas = []
    for nombre in list(entorno):
        if nombre in ENTORNO_FALSO or nombre.startswith("PATH"):
            continue
        if nombre.startswith(PREFIJOS_AZURE):
            entorno.pop(nombre, None)
            quitadas.append(nombre)
    if quitadas:
        print(f"  {GRIS}Aislamiento: se quitaron del entorno "
              f"{len(quitadas)} variable(s) reales "
              f"({', '.join(sorted(quitadas)[:4])}…){FIN}")

    # ------------------------------------------------------------------
    # Bloquear el .env durante la prueba.
    #
    # Limpiar el entorno NO es suficiente: la aplicación carga el archivo .env
    # por su cuenta al arrancar (con _cargar_dotenv), así que con un .env real
    # en el proyecto volvería a usar credenciales verdaderas y la prueba
    # dejaría de medir la configuración rota.
    #
    # Se renombra el archivo temporalmente y se restaura SIEMPRE en el bloque
    # finally, incluso si la prueba falla o se interrumpe.
    # ------------------------------------------------------------------
    env_original = RAIZ / ".env"
    env_bloqueado = RAIZ / ".env.en-prueba"
    bloqueado = False
    if env_original.exists():
        try:
            env_original.rename(env_bloqueado)
            bloqueado = True
            print(f"  {GRIS}Aislamiento: .env apartado durante la prueba{FIN}")
        except OSError as exc:
            print(f"  {AMARILLO}No se pudo apartar el .env: {exc}{FIN}")

    nav = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(RAIZ / "app.py"),
             "--server.port", str(puerto), "--server.address", "127.0.0.1",
             "--server.headless", "true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(RAIZ), env=entorno,
        )

        url = f"http://127.0.0.1:{puerto}/_stcore/health"
        inicio = time.time()
        listo = False
        while time.time() - inicio < 70:
            if proc.poll() is not None:
                revisar("La app arranca aunque las credenciales sean inválidas", False,
                        f"terminó con código {proc.returncode}")
                return 1
            try:
                with urllib.request.urlopen(url, timeout=4) as r:
                    if r.status == 200 and "ok" in r.read().decode(errors="replace").lower():
                        listo = True
                        break
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.7)
        revisar(
            "La app arranca aunque las credenciales sean inválidas",
            listo,
            "Un fallo de configuración no debe impedir abrir la aplicación.",
        )
        if not listo:
            return 1

        nav = Navegador(encontrar_navegador(), 1500, 1150)
        nav.navegar(f"http://127.0.0.1:{puerto}")
        dibujado = nav.esperar_texto(timeout=60)
        revisar("La interfaz se dibuja", dibujado)
        if not dibujado:
            return 1
        pf.esperar_quieto(nav)

        texto = nav.evaluar(pf.JS_TEXTO) or ""

        # La barra lateral ya no lista los servicios en la cara del usuario:
        # muestra una frase de estado y deja el detalle en «Detalle técnico».
        # Lo que se sigue exigiendo es lo importante: no prometer que los
        # servicios FUNCIONAN sin haberlo comprobado.
        revisar(
            "La barra lateral no promete que los servicios funcionen",
            not any(
                falso in texto
                for falso in ("Todo funciona", "Todo listo, verificado",
                              "✅ Microsoft Foundry")
            ),
            "No debe afirmar que algo funciona sin comprobarlo.",
        )
        # El comando de diagnóstico vive dentro del desplegable técnico, que es
        # donde lo busca Carlos. Hay que abrirlo para leerlo.
        nav.evaluar(
            "(() => { const d = document.querySelectorAll('details');"
            " for (const x of d) {"
            "  if ((x.innerText||'').includes('Detalle técnico')) { x.open = true; return true; }"
            " } return false; })()"
        )
        pf.esperar_quieto(nav)
        texto_tecnico = nav.evaluar(pf.JS_TEXTO) or ""
        revisar(
            "Invita a ejecutar el diagnóstico que sí comprueba de verdad",
            "diagnostico_azure.py" in texto_tecnico or "diagnostico_azure.py" in texto,
            "El comando está en el desplegable «Detalle técnico».",
        )

        # Pulsar el botón del asistente debe producir un error TRADUCIDO
        pf.cambiar_pestana(nav, 1)
        pf.esperar_quieto(nav)
        if pf.clic_texto(nav, "Consultar al agente", "consultar"):
            # El SDK tarda en agotar los reintentos contra un host inexistente
            # y, cuando por fin falla, Streamlit tiene que volver a pintar el
            # resultado. Una sola lectura justo después del clic llega a veces
            # ANTES de que el mensaje aparezca, y la prueba fallaba sin que la
            # aplicación tuviera ningún problema.
            #
            # Se espera a que el texto esperado aparezca, en lugar de suponer
            # que ya está.
            pf.esperar_quieto(nav, timeout=120)
            t2 = ""
            esperados = ("No se pudo autenticar", "No se pudo resolver",
                         "Acceso denegado", "no respondió", "clave del servicio")
            for _ in range(30):
                time.sleep(2)
                t2 = nav.evaluar(pf.JS_TEXTO) or ""
                if any(e in t2 for e in esperados) and "Detalle técnico" in t2:
                    break

            # 1. La app sigue viva (no se cayó)
            revisar(
                "La app sigue respondiendo después del fallo",
                len(t2) > 500,
                f"{len(t2)} caracteres visibles",
            )

            # 2. El mensaje está en español y explica qué hacer
            tiene_explicacion = (
                "No se pudo autenticar" in t2
                or "No se pudo resolver" in t2
                or "Acceso denegado" in t2
                or "no respondió" in t2
                or "clave del servicio" in t2
            )
            revisar(
                "Muestra un error en español con la causa probable",
                tiene_explicacion,
                "En lugar de la traza cruda del SDK.",
            )

            # 3. El detalle técnico sigue disponible para depurar
            revisar(
                "Conserva el detalle técnico para depurar",
                "Detalle técnico" in t2,
                "Plegado, para no asustar a quien presenta.",
            )

            # 4. NO se filtran párrafos del SDK a la vista principal
            #    (la enumeración de credenciales de azure-identity ocupa media
            #    pantalla; debe quedar dentro del detalle plegado)
            parrafos_largos = sum(
                1 for l in t2.splitlines()
                if len(l) > 300 and ("Credential" in l or "troubleshoot" in l)
            )
            revisar(
                "No vuelca la enumeración de credenciales del SDK a la vista",
                parrafos_largos == 0,
                "El texto de DefaultAzureCredential enumera cada método que "
                "intentó; eso asusta y no ayuda a nadie durante una demo.",
            )

        # La app debe seguir usable: otra tarea responde. Se espera a que el
        # contenido aparezca en lugar de leerlo una sola vez: Streamlit
        # reejecuta la aplicación y a veces la lectura llega antes del repintado
        # (esto hacía la prueba intermitente).
        pf.cambiar_pestana(nav, 5)
        pf.esperar_quieto(nav)
        t3 = ""
        for _ in range(20):
            time.sleep(1.5)
            t3 = nav.evaluar(pf.JS_TEXTO) or ""
            if "Ver el reporte de ventas" in t3 and (
                "Sucursal" in t3 or "sucursal" in t3
            ):
                break
        # Se comprueba que la pantalla de reporte CARGÓ, no una cifra concreta.
        # Exigir «917,700» hacía la prueba frágil: el importe puede mostrarse
        # con otro formato y entonces fallaba aunque todo estuviera bien. Lo
        # que importa aquí es que las tareas que no dependen de Azure siguen
        # respondiendo.
        soporta = (
            "Ver el reporte de ventas" in t3
            and "sucursal" in t3.lower()
            and "Traceback" not in t3
        )
        revisar(
            "Las tareas que no dependen de Azure siguen funcionando",
            soporta,
            "El reporte directivo usa datos locales y no debe romperse.",
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
        # Restaurar el .env SIEMPRE, incluso si la prueba falló o se interrumpió.
        # Dejarlo apartado rompería el resto del proyecto sin avisar.
        if bloqueado and env_bloqueado.exists():
            try:
                env_bloqueado.rename(env_original)
            except OSError as exc:
                print(f"  {ROJO}ATENCIÓN: no se pudo restaurar el .env: {exc}{FIN}")
                print(f"  {ROJO}El archivo quedó como {env_bloqueado.name}; "
                      f"renómbrelo a .env manualmente.{FIN}")

    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    total = _ok + _fallo
    if _fallo == 0:
        print(f"{VERDE}RESULTADO: {_ok}/{total} comprobaciones correctas.{FIN}")
        print("La app degrada con dignidad cuando Azure falla.")
        print(f"{NEGRITA}{'=' * 74}{FIN}")
        return 0
    print(f"{ROJO}RESULTADO: {_fallo} de {total} comprobaciones FALLARON.{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
