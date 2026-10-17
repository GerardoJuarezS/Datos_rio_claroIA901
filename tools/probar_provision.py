"""
Pruebas del provisionador de Azure, sin tocar Azure.

Verifican el flujo de provisión con un ejecutor simulado. Es exactamente lo que
el script de bash no permitía hacer, y es lo que ya detectó dos errores reales
(el endpoint del proyecto mal armado y el nombre del proyecto escrito a mano).

Uso:
    python tools/probar_provision.py
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

from provision_azure import (  # noqa: E402
    Config,
    Ejecutor,
    construir_pasos,
    construir_pasos_con_identificadores,
    ejecutar_plan,
)

VERDE, ROJO, AMARILLO, GRIS, FIN = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"

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
        for l in detalle.splitlines():
            print(f"        {GRIS}{l}{FIN}")


def seccion(t: str) -> None:
    print(f"\n{AMARILLO}{t}{FIN}")


# ---------------------------------------------------------------------------
# Simulacros
# ---------------------------------------------------------------------------


class EjecutorSimulado(Ejecutor):
    """
    Ejecutor que no llama a Azure. Permite decidir qué comandos fallan y qué
    devuelven, para probar el manejo de errores.
    """

    def __init__(self, fallar: set[str] | None = None, respuestas: dict[str, str] | None = None):
        super().__init__(dry_run=False)
        self.fallar = fallar or set()
        self.respuestas = respuestas or {}
        self.llamadas: list[list[str]] = []

    def az(self, args: list[str], capturar: bool = False):
        self.llamadas.append(list(args))
        texto = " ".join(args)

        for patron in self.fallar:
            if patron in texto:
                return 1, f"ERROR simulado: falló '{patron}'"

        for patron, salida in self.respuestas.items():
            if patron in texto:
                return 0, salida

        # Respuestas por defecto razonables según el tipo de comando
        if "--query" in args and "id" in args:
            return 0, "/subscriptions/0000/resourceGroups/rg/providers/Microsoft.X/y"
        if "principalId" in texto:
            return 0, "11111111-2222-3333-4444-555555555555"
        if "keys" in args and "list" in args:
            return 0, "clave_simulada_de_prueba_1234567890"
        if "properties.endpoint" in texto:
            return 0, "https://rioclaro-foundry.services.ai.azure.com/"
        return 0, ""


# ---------------------------------------------------------------------------
# Pruebas
# ---------------------------------------------------------------------------


def main() -> int:
    print()
    print("=" * 74)
    print("PRUEBAS DEL PROVISIONADOR DE AZURE (sin tocar Azure)")
    print("=" * 74)

    cfg = Config()

    # ------------------------------------------------------------------
    seccion("1. CONSTRUCCIÓN DE LA LISTA DE COMANDOS (función pura)")
    pasos = construir_pasos(cfg)
    revisar("Se generan pasos", len(pasos) > 20, f"{len(pasos)} pasos base")
    todos = construir_pasos_con_identificadores(cfg)
    revisar("Con identificadores y secretos hay más pasos", len(todos) > len(pasos),
            f"{len(todos)} pasos completos")

    def texto_de(pasos_lista) -> str:
        return "\n".join(" ".join(p.args) for p in pasos_lista)

    cuerpo = texto_de(todos)

    revisar("Se crea el grupo de recursos",
            "group create" in cuerpo and cfg.grupo in cuerpo)
    revisar("Se registra el proveedor de Cognitive Services",
            "provider register" in cuerpo)
    revisar("Se crea el recurso de Foundry con kind AIServices y SKU S0",
            "--kind AIServices" in cuerpo and "--sku S0" in cuerpo)
    revisar("Se crea el PROYECTO de Foundry",
            "account project create" in cuerpo and cfg.proyecto in cuerpo)
    revisar("El plan de App Service es Linux",
            "--is-linux" in cuerpo,
            "Sin --is-linux el plan sería Windows y Streamlit no funcionaría.")
    revisar("Se configura el comando de arranque",
            "startup.sh" in cuerpo)
    revisar("Se activa la identidad administrada",
            "identity assign" in cuerpo)
    revisar("Se activa la escritura durante el despliegue",
            "SCM_DO_BUILD_DURING_DEPLOYMENT=true" in cuerpo,
            "Sin esto, App Service no instala requirements.txt.")
    # En App Service Linux con imágenes "Blessed" (PYTHON:3.11), el puerto del
    # contenedor lo controla la variable PORT. WEBSITES_PORT NO TIENE EFECTO:
    # solo aplica a contenedores personalizados. Este fue un error real: se
    # configuraba WEBSITES_PORT=8000, que en una app Python no hace nada, y la
    # configuración del puerto quedaba ambigua.
    revisar(
        "Se fija PORT (la variable que controla el puerto en imágenes Blessed)",
        "PORT=8000" in cuerpo,
        "El puerto debe coincidir en tres sitios: esta variable, startup.sh y "
        ".streamlit/config.toml.",
    )
    revisar(
        "NO se usa WEBSITES_PORT, que no tiene efecto en imágenes Blessed",
        "WEBSITES_PORT=" not in cuerpo,
        "WEBSITES_PORT solo aplica a contenedores personalizados.",
    )

    # ------------------------------------------------------------------
    seccion("2. EL ENDPOINT DEL PROYECTO, NO EL DEL RECURSO")
    # Este fue un error real: se guardaba el endpoint del recurso y el SDK
    # de Foundry fallaba con un mensaje que no explicaba la causa.
    revisar(
        "El endpoint del proyecto incluye /api/projects/",
        "/api/projects/" in cfg.endpoint_proyecto,
        cfg.endpoint_proyecto,
    )
    paso_appsettings = next(p for p in todos if "appsettings" in p.args)
    valor_proyecto = next(
        (a for a in paso_appsettings.args if a.startswith("FOUNDRY_PROJECT_ENDPOINT=")),
        "",
    )
    revisar(
        "FOUNDRY_PROJECT_ENDPOINT apunta al proyecto",
        "/api/projects/" in valor_proyecto,
        valor_proyecto or "(no encontrado)",
    )
    valor_cu = next(
        (a for a in paso_appsettings.args if a.startswith("CONTENT_UNDERSTANDING_ENDPOINT=")),
        "",
    )
    revisar(
        "CONTENT_UNDERSTANDING_ENDPOINT apunta al recurso (sin /api/projects/)",
        "/api/projects/" not in valor_cu and valor_cu.endswith("azure.com/"),
        valor_cu or "(no encontrado)",
    )

    # ------------------------------------------------------------------
    seccion("3. SECRETOS EN KEY VAULT")
    secretos_esperados = [
        "foundry-project-endpoint",
        "content-understanding-endpoint",
        "content-understanding-key",
        "speech-key",
        "speech-region",
        "language-endpoint",
        "language-key",
    ]
    pasos_secretos = [p for p in todos if p.args[:3] == ["keyvault", "secret", "set"]]
    nombres = [p.args[p.args.index("--name") + 1] for p in pasos_secretos]
    revisar(
        f"Se guardan los {len(secretos_esperados)} secretos",
        set(nombres) == set(secretos_esperados),
        f"encontrados: {sorted(nombres)}",
    )
    paso_proy = next((p for p in pasos_secretos if "foundry-project-endpoint" in p.args), None)
    if paso_proy:
        valor = paso_proy.args[paso_proy.args.index("--value") + 1]
        revisar(
            "El secreto foundry-project-endpoint se construye con el endpoint del PROYECTO",
            "/api/projects/" in valor,
            valor,
        )
        revisar(
            "Ese secreto no depende de ningún marcador sin rellenar",
            "{" not in valor,
            "Si dependiera de {ENDPOINT_PROYECTO}, Azure guardaría la cadena\n"
            "literal '{ENDPOINT_PROYECTO}' como valor del secreto, porque ningún\n"
            "paso anterior rellena esa variable.",
        )
    else:
        revisar("Existe el secreto foundry-project-endpoint", False)
    revisar(
        "Ningún secreto se pasa por variable de entorno del shell",
        all("--value" in p.args for p in pasos_secretos),
    )

    # ------------------------------------------------------------------
    seccion("4. PERMISOS (los dos roles obligatorios)")
    revisar("Se asigna 'Cognitive Services User'",
            "Cognitive Services User" in cuerpo)
    revisar("Se asigna 'Key Vault Secrets User'",
            "Key Vault Secrets User" in cuerpo)
    revisar(
        "Las asignaciones de rol NO son críticas",
        all(not p.critico for p in todos if "role assignment" in " ".join(p.args)),
        "Si fallan (cuenta sin permisos de Owner), el script avisa y continúa\n"
        "en lugar de abortar a mitad de la provisión.",
    )

    # ------------------------------------------------------------------
    seccion("5. MODELOS DESPLEGADOS")
    despliegues = [p for p in todos if p.args[:4] == ["cognitiveservices", "account", "deployment", "create"]]
    modelos = [p.args[p.args.index("--model-name") + 1] for p in despliegues]
    # Se despliegan 3 modelos, no 5. La razón está documentada en el script: en
    # una suscripción Azure for Students se comprobó que gpt-4.1,
    # text-embedding-3-large y TODOS los modelos de imagen tienen cuota 0.
    # Desplegarlos sería intentar algo que siempre falla.
    revisar("Se despliegan 3 modelos", len(modelos) == 3, ", ".join(modelos))
    for requerido in (cfg.modelo_chat, cfg.modelo_principal, cfg.modelo_embed):
        revisar(f"Se despliega '{requerido}'", requerido in modelos)
    revisar(
        "Content Understanding tiene sus modelos para facturas y embeddings",
        cfg.modelo_principal in modelos and cfg.modelo_embed in modelos,
        "prebuilt-invoice necesita un modelo de finalización y uno de\n"
        "embeddings. Sin ellos falla con 'Default model deployment not\n"
        "configured'.",
    )
    revisar(
        "Se usa text-embedding-3-small (el que tiene cuota)",
        "text-embedding-3-small" in modelos,
        "text-embedding-3-large tiene cuota 0 en suscripciones de estudiante.",
    )
    revisar(
        "NO se usa dall-e (retirado el 4-mar-2026)",
        not any("dall-e" in m.lower() for m in modelos),
    )
    revisar(
        "NO se intenta desplegar un modelo de imagen por defecto",
        not any("image" in m.lower() for m in modelos),
        "En la suscripción de prueba TODOS los modelos de imagen tienen cuota 0\n"
        "(de OpenAI y de Microsoft). La generación de imágenes es la única\n"
        "función opcional; la visión usa el modelo multimodal y sí funciona.",
    )
    revisar(
        "Existe la opción de intentarlo con --con-modelo-imagen",
        "con_modelo_imagen" in (
            RAIZ / "tools" / "provision_azure.py"
        ).read_text(encoding="utf-8"),
        "Para suscripciones que sí permitan modelos de imagen.",
    )

    # ------------------------------------------------------------------
    seccion("6. NOMBRES VÁLIDOS PARA AZURE")
    revisar(
        "El nombre de Key Vault solo tiene alfanuméricos",
        cfg.almacen.isalnum(),
        f"'{cfg.almacen}' — Key Vault no admite guiones ni guiones bajos en el nombre",
    )
    revisar(
        "El nombre de Key Vault tiene entre 3 y 24 caracteres",
        3 <= len(cfg.almacen) <= 24,
        f"{len(cfg.almacen)} caracteres",
    )
    revisar(
        "Los nombres de recurso son válidos",
        all(
            n.replace("-", "").isalnum() and 2 <= len(n) <= 64
            for n in (cfg.recurso_ia, cfg.recurso_voz, cfg.recurso_idioma, cfg.app, cfg.plan)
        ),
        f"{cfg.recurso_ia}, {cfg.recurso_voz}, {cfg.recurso_idioma}, {cfg.app}, {cfg.plan}",
    )
    for etiqueta, valor in (
        ("endpoint del proyecto", cfg.endpoint_proyecto),
        ("endpoint del recurso IA", cfg.endpoint_ia),
        ("endpoint de Language", cfg.endpoint_idioma),
        ("URI de Key Vault", cfg.uri_keyvault),
        ("URL de la app", cfg.url_app),
    ):
        revisar(f"{etiqueta} tiene forma de URL", valor.startswith("https://"), valor)

    # ------------------------------------------------------------------
    seccion("7. FLUJO COMPLETO CON EJECUTOR SIMULADO")
    ejec = EjecutorSimulado()
    resultados = ejecutar_plan(cfg, todos, ejec)
    fallidos = [d for d, ok, _ in resultados if not ok]
    revisar("Todos los pasos se ejecutan sin fallo", not fallidos,
            f"{len(resultados)} pasos" + (f" · fallidos: {fallidos}" if fallidos else ""))
    revisar("Se registraron todos los comandos", len(ejec.llamadas) == len(todos),
            f"{len(ejec.llamadas)} comandos")
    revisar("El endpoint del proyecto quedó resuelto en las llamadas",
            any("/api/projects/" in " ".join(c) for c in ejec.llamadas))
    revisar("La identidad administrada quedó resuelta en las asignaciones de rol",
            not any("{PRINCIPAL_ID}" in " ".join(c) for c in ejec.llamadas),
            "No deben quedar marcadores sin sustituir.")

    # Comprobación clave: en una ejecución REAL, ningún valor enviado a Azure
    # puede contener un marcador sin resolver. Si lo tuviera, Azure guardaría
    # la cadena literal como si fuera un valor legítimo.
    marcadores = []
    for llamada in ejec.llamadas:
        for arg in llamada:
            # Los nombres de los secretos no son marcadores; los valores sí importan
            if "{" in arg and "}" in arg and not arg.startswith("--"):
                marcadores.append(arg)
    revisar(
        "Ningún comando enviado a Azure contiene un marcador sin resolver",
        not marcadores,
        "\n".join(marcadores) if marcadores else
        "Se revisaron los valores de los 33 comandos reales.",
    )

    # Y en concreto: los secretos guardados deben ser valores reales
    valores_secretos = []
    for llamada in ejec.llamadas:
        if llamada[:3] == ["keyvault", "secret", "set"]:
            valores_secretos.append(llamada[llamada.index("--value") + 1])
    revisar(
        "Los 7 secretos guardados son valores reales",
        len(valores_secretos) == 7 and not any("{" in v for v in valores_secretos),
        "; ".join(v[:45] for v in valores_secretos),
    )

    # ------------------------------------------------------------------
    seccion("8. MANEJO DE ERRORES")
    # Un fallo NO crítico no debe detener la provisión.
    ejec2 = EjecutorSimulado(fallar={"deployment create"})
    res2 = ejecutar_plan(cfg, todos, ejec2)
    revisar(
        "Un fallo al desplegar un modelo NO detiene la provisión",
        len(res2) == len(todos),
        f"se ejecutaron {len(res2)} de {len(todos)} pasos",
    )

    # Un fallo CRÍTICO sí debe detenerla.
    ejec3 = EjecutorSimulado(fallar={"group create"})
    res3 = ejecutar_plan(cfg, todos, ejec3)
    revisar(
        "Un fallo al crear el grupo de recursos SÍ detiene la provisión",
        len(res3) < len(todos),
        f"se detuvo en el paso {len(res3)} de {len(todos)}",
    )

    # Un fallo en los roles no debe detenerla (la cuenta puede no ser Owner).
    # Son TRES asignaciones de rol en total: dos para la identidad administrada
    # de la aplicación y una para tu cuenta (Key Vault Secrets Officer, que hace
    # falta para poder escribir los secretos).
    ejec4 = EjecutorSimulado(fallar={"role assignment create"})
    res4 = ejecutar_plan(cfg, todos, ejec4)
    fallidos4 = [d for d, ok, _ in res4 if not ok]
    revisar(
        "Un fallo al asignar roles NO detiene la provisión",
        len(fallidos4) == 3 and len(res4) == len(todos),
        f"{len(fallidos4)} fallos reportados, pero se completaron los {len(res4)} pasos",
    )

    # ------------------------------------------------------------------
    seccion("9. MODO ENSAYO")
    ejec5 = EjecutorSimulado()
    ejec5.dry_run = True
    ejec5.prefijar_variables_conocidas(cfg)
    antes = len(ejec5.comandos_ejecutados)
    ejecutar_plan(cfg, todos, ejec5)
    revisar("El modo ensayo no ejecuta ningún comando contra Azure",
            len(ejec5.comandos_ejecutados) == 0,
            f"comandos enviados a az: {len(ejec5.comandos_ejecutados)}")
    resuelto = ejec5.resolver("{ENDPOINT_PROYECTO}")
    revisar("El ensayo resuelve el endpoint del proyecto",
            "/api/projects/" in resuelto, resuelto)
    revisar("El ensayo no inventa claves",
            "se lee de Azure" in ejec5.resolver("{CLAVE_IA}"),
            "Las claves dependen de Azure: se explica en lugar de inventarlas.")

    # ------------------------------------------------------------------
    seccion("10. VERIFICACIÓN PREVIA DEL ENTORNO")
    # Estas comprobaciones existen porque el problema más frecuente al empezar
    # es la cuenta: una cuenta personal de Microsoft hace que las asignaciones
    # de rol de Entra ID y el control de acceso de Key Vault fallen con errores
    # de permisos que el estudiante no puede resolver. Detectar eso ANTES de
    # crear recursos ahorra media hora de confusión.
    from provision_azure import DOMINIOS_PERSONALES, comprobar_requisitos

    revisar(
        "Reconoce los dominios personales más comunes",
        {"outlook.com", "hotmail.com", "live.com", "gmail.com"}.issubset(
            set(DOMINIOS_PERSONALES)
        ),
        ", ".join(DOMINIOS_PERSONALES),
    )

    casos_cuenta = [
        ("alumno@universidad.edu.mx", False, "cuenta institucional"),
        ("estudiante@tec.mx", False, "cuenta institucional"),
        ("juan@gmail.com", True, "cuenta personal"),
        ("x@outlook.com", True, "cuenta personal"),
        ("y@hotmail.es", True, "cuenta personal"),
        ("z@empresa.com", False, "cuenta corporativa"),
    ]
    for correo, esperado, descripcion in casos_cuenta:
        c = correo.lower()
        detectado = any(c.endswith(f"@{d}") for d in DOMINIOS_PERSONALES)
        revisar(
            f"Clasifica '{correo}' como {descripcion}",
            detectado == esperado,
            f"esperaba personal={esperado}, obtuvo {detectado}",
        )

    # Sin Azure instalado, la función debe devolver False con instrucciones,
    # no lanzar una excepción.
    try:
        puede, mensaje = comprobar_requisitos()
        revisar(
            "comprobar_requisitos() no lanza excepción sin Azure",
            isinstance(puede, bool) and bool(mensaje),
            f"devuelve puede_continuar={puede}",
        )
        if not puede:
            revisar(
                "El mensaje explica cómo instalar Azure CLI o iniciar sesión",
                ("winget install" in mensaje or "az login" in mensaje
                 or "Azure CLI" in mensaje),
                "El mensaje debe ser accionable, no un volcado técnico.",
            )
    except Exception as exc:
        revisar("comprobar_requisitos() no lanza excepción sin Azure", False,
                f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    seccion("11. MODELOS POR DEFECTO DE CONTENT UNDERSTANDING")
    # Los analizadores preconstruidos (el de facturas entre ellos) NO funcionan
    # sin este mapeo. Falla con "Default model deployment not configured", que
    # es el error más común después de desplegar y no explica nada.
    #
    # La parte fácil de olvidar son los ALIAS: los analizadores preconstruidos no
    # referencian "gpt-4.1" sino "prebuilt-analyzer-completion". Si solo se mapea
    # el nombre del modelo, siguen fallando.
    import io
    import contextlib
    from provision_azure import configurar_modelos_por_defecto

    # Capturar la salida para que la prueba no ensucie la consola
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        resultado = configurar_modelos_por_defecto(
            cfg,
            {"ENDPOINT_IA": "https://no-existe-para-la-prueba.services.ai.azure.com/",
             "CLAVE_IA": "clave_falsa_para_la_prueba_1234567890"},
        )
    texto_salida = salida.getvalue()

    revisar(
        "No lanza excepción si el servicio no responde",
        resultado is False,
        "Debe devolver False y avisar: la provisión no se detiene por esto.",
    )
    revisar(
        "El aviso explica que NO detiene la provisión",
        "NO detiene" in texto_salida or "no detiene" in texto_salida.lower(),
        "El estudiante debe saber que puede continuar.",
    )
    revisar(
        "El aviso menciona el rol que más falla",
        "Cognitive Services User" in texto_salida,
        "Es la causa más frecuente de este error concreto.",
    )

    # Los alias deben estar en el mapeo. Se comprueba inspeccionando la
    # constante que arma el diccionario, sin llamar al servicio.
    fuente = (RAIZ / "tools" / "provision_azure.py").read_text(encoding="utf-8")
    for alias, para_que in (
        ("prebuilt-analyzer-completion", "los analizadores preconstruidos como prebuilt-invoice"),
        ("prebuilt-analyzer-completion-mini", "los analizadores de búsqueda"),
        ("prebuilt-analyzer-embedding", "los analizadores que usan embeddings"),
    ):
        revisar(
            f"Mapea el alias '{alias}'",
            alias in fuente,
            f"Lo necesitan {para_que}. Sin este alias, el analizador sigue fallando "
            f"aunque el nombre del modelo esté bien.",
        )

    revisar(
        "El mapeo usa update_defaults() del SDK",
        "update_defaults" in fuente and "model_deployments" in fuente,
        "Permite automatizarlo en lugar de configurarlo a mano en el portal.",
    )

    # ------------------------------------------------------------------
    print()
    print("=" * 74)
    total = _ok + _fallo
    if _fallo == 0:
        print(f"{VERDE}RESULTADO: {_ok}/{total} pruebas pasaron.{FIN}")
        print("El provisionador está verificado y listo para ejecutarse.")
        print("=" * 74)
        return 0
    print(f"{ROJO}RESULTADO: {_fallo} de {total} pruebas FALLARON.{FIN}")
    print("=" * 74)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
