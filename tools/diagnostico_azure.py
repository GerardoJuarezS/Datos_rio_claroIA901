"""
Diagnóstico de conectividad con Azure para el proyecto Río Claro AI-901.

Comprueba, uno por uno, cada servicio que usa el prototipo y dice con precisión
qué falta o qué está mal. Está pensado para ejecutarse ANTES de la demo, no
durante: si algo va a fallar, que falle aquí.

Uso:
    python tools/diagnostico_azure.py
    python tools/diagnostico_azure.py --factura samples/factura_limpia.pdf
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

VERDE, ROJO, AMARILLO, GRIS, CIAN, FIN = (
    "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[96m", "\033[0m",
)

_ok = 0
_fallo = 0
_omitido = 0


def titulo(texto: str) -> None:
    print(f"\n{CIAN}{'=' * 74}{FIN}")
    print(f"{CIAN}{texto}{FIN}")
    print(f"{CIAN}{'=' * 74}{FIN}")


def bien(texto: str, detalle: str = "") -> None:
    global _ok
    _ok += 1
    print(f"  {VERDE}OK{FIN}      {texto}")
    if detalle:
        print(f"          {GRIS}{detalle}{FIN}")


def mal(texto: str, detalle: str = "") -> None:
    global _fallo
    _fallo += 1
    print(f"  {ROJO}FALLA{FIN}   {texto}")
    if detalle:
        for linea in detalle.splitlines():
            print(f"          {ROJO}{linea}{FIN}")


def omitir(texto: str, detalle: str = "") -> None:
    global _omitido
    _omitido += 1
    print(f"  {AMARILLO}OMITIDO{FIN} {texto}")
    if detalle:
        print(f"          {GRIS}{detalle}{FIN}")


def info(texto: str) -> None:
    print(f"  {GRIS}{texto}{FIN}")


# ---------------------------------------------------------------------------


def cargar_entorno() -> dict[str, str]:
    """Carga .env igual que lo hace app.py."""
    ruta = RAIZ / ".env"
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, _, valor = linea.partition("=")
            os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))

    return {
        "foundry": os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip(),
        "modelo": os.environ.get("FOUNDRY_MODEL", "gpt-5-mini").strip(),
        "agente": os.environ.get("FOUNDRY_AGENT_NAME", "rio-claro-agent").strip(),
        "cu": os.environ.get("CONTENT_UNDERSTANDING_ENDPOINT", "").strip(),
        "cu_key": os.environ.get("CONTENT_UNDERSTANDING_KEY", "").strip(),
        "voz_key": os.environ.get("SPEECH_KEY", "").strip(),
        "voz_region": os.environ.get("SPEECH_REGION", "").strip(),
        "idioma": os.environ.get("LANGUAGE_ENDPOINT", "").strip(),
        "idioma_key": os.environ.get("LANGUAGE_KEY", "").strip(),
        "kv": os.environ.get("KEY_VAULT_URI", "").strip(),
    }


def revisar_dependencias() -> None:
    titulo("1. DEPENDENCIAS DE PYTHON")
    paquetes = [
        ("streamlit", "interfaz web"),
        ("pandas", "manejo de datos"),
        ("azure.identity", "autenticación (DefaultAzureCredential)"),
        ("azure.ai.projects", "Microsoft Foundry (IA generativa y agentes)"),
        ("azure.ai.contentunderstanding", "Content Understanding (extracción)"),
        ("azure.ai.textanalytics", "Azure AI Language (análisis de texto)"),
        ("azure.cognitiveservices.speech", "Azure Speech (voz)"),
        ("azure.keyvault.secrets", "Key Vault (secretos)"),
    ]
    for modulo, descripcion in paquetes:
        try:
            __import__(modulo)
            bien(f"{modulo}", descripcion)
        except ImportError as exc:
            mal(f"{modulo} no instalado", f"{descripcion}\n{exc}\n"
                f"Ejecute:  pip install -r requirements.txt")

    # versiones, para dejar constancia en la entrega
    try:
        import azure.ai.projects as p

        info(f"azure-ai-projects: {getattr(p, 'VERSION', '?')}")
    except Exception:
        pass


def revisar_configuracion(entorno: dict[str, str]) -> None:
    titulo("2. CONFIGURACIÓN (.env o App Settings)")
    esperados = [
        ("FOUNDRY_PROJECT_ENDPOINT", entorno["foundry"], "Microsoft Foundry"),
        ("CONTENT_UNDERSTANDING_ENDPOINT", entorno["cu"], "Content Understanding"),
        ("LANGUAGE_ENDPOINT", entorno["idioma"], "Azure AI Language"),
        ("LANGUAGE_KEY", entorno["idioma_key"], "Azure AI Language (clave)"),
        ("SPEECH_KEY", entorno["voz_key"], "Azure Speech (clave)"),
        ("SPEECH_REGION", entorno["voz_region"], "Azure Speech (región)"),
    ]
    for nombre, valor, descripcion in esperados:
        if valor:
            mostrado = valor if not nombre.endswith("KEY") else f"{valor[:4]}…{valor[-4:]}"
            bien(f"{nombre} definido", f"{descripcion} · {mostrado}")
        else:
            omitir(f"{nombre} sin definir", descripcion)

    if entorno["foundry"] and "/api/projects/" not in entorno["foundry"]:
        mal(
            "FOUNDRY_PROJECT_ENDPOINT no parece un endpoint de PROYECTO",
            "Debe tener la forma:\n"
            "  https://<recurso>.services.ai.azure.com/api/projects/<proyecto>\n"
            "El endpoint del recurso (sin /api/projects/...) NO sirve para el SDK.",
        )
    elif entorno["foundry"]:
        bien("El endpoint del proyecto tiene el formato correcto")

    if entorno["kv"]:
        info(f"Key Vault configurado: {entorno['kv']}")
        info("Los secretos se leerán de ahí con identidad administrada.")
    else:
        info("Key Vault no configurado: se usan variables de entorno.")


def revisar_autenticacion(entorno: dict[str, str]) -> None:
    titulo("3. AUTENTICACIÓN (Microsoft Entra ID)")

    # Si no hay ningún endpoint configurado, no tiene sentido fallar aquí:
    # el usuario todavía no ha creado los recursos (o solo quiere ver la app
    # en modo demostración). Se informa y se continúa.
    hay_algo_configurado = any(
        entorno[k] for k in ("foundry", "cu", "idioma", "voz_key", "voz_region", "kv")
    )
    if not hay_algo_configurado:
        omitir(
            "No hay ningún servicio de Azure configurado todavía",
            "Ejecute tools/provision_azure.py y complete el archivo .env.\n"
            "Mientras tanto la aplicación funciona en modo demostración.",
        )
        return

    try:
        from azure.identity import DefaultAzureCredential

        credencial = DefaultAzureCredential()
        token = credencial.get_token("https://cognitiveservices.azure.com/.default")
        if token and token.token:
            bien("DefaultAzureCredential obtuvo un token")
            if token.expires_on:
                import datetime

                restante = (
                    datetime.datetime.fromtimestamp(token.expires_on, datetime.timezone.utc)
                    - datetime.datetime.now(datetime.timezone.utc)
                )
                info(f"Válido hasta {token.expires_on} (queda {restante})")
        else:
            mal("DefaultAzureCredential no devolvió token")
    except Exception as exc:
        mal(
            "No se pudo autenticar con Entra ID",
            f"{type(exc).__name__}: {str(exc)[:400]}\n\n"
            "Soluciones:\n"
            "  * En su computadora: ejecute  az login\n"
            "  * En App Service: habilite la identidad administrada y asígnele\n"
            "    el rol 'Cognitive Services User' en el recurso de Foundry.",
        )


def revisar_foundry(entorno: dict[str, str]) -> None:
    titulo("4. MICROSOFT FOUNDRY (IA generativa y agentes)")
    if not entorno["foundry"]:
        omitir("Sin FOUNDRY_PROJECT_ENDPOINT; no se puede probar")
        return

    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        proyecto = AIProjectClient(
            endpoint=entorno["foundry"], credential=DefaultAzureCredential()
        )
        bien("Se creó el AIProjectClient")

        cliente = proyecto.get_openai_client()
        bien("Se obtuvo el cliente de OpenAI del proyecto")

        respuesta = cliente.responses.create(
            model=entorno["modelo"],
            input="Responde únicamente con la palabra: listo",
        )
        texto = (respuesta.output_text or "").strip()
        if texto:
            bien(f"El modelo '{entorno['modelo']}' respondió", f"respuesta: {texto[:80]!r}")
        else:
            mal("El modelo respondió vacío", "Revise el nombre del despliegue.")

        # El agente es opcional: si no existe, la app usa el modelo directo.
        try:
            cliente_agente = proyecto.get_openai_client(agent_name=entorno["agente"])
            conversacion = cliente_agente.conversations.create()
            r = cliente_agente.responses.create(
                conversation=conversacion.id,
                input="Di exactamente: agente activo",
            )
            bien(f"El agente '{entorno['agente']}' respondió",
                 f"respuesta: {(r.output_text or '')[:80]!r}")
        except Exception as exc:
            omitir(
                f"El agente '{entorno['agente']}' no está disponible",
                f"{type(exc).__name__}: {str(exc)[:200]}\n"
                "Créelo en https://ai.azure.com > Compilar > Agentes.\n"
                "La aplicación funciona igual usando el modelo directo.",
            )
    except Exception as exc:
        mal(
            "Error al invocar Microsoft Foundry",
            f"{type(exc).__name__}: {exc}\n\n"
            "Causas típicas:\n"
            "  * El endpoint no es el del PROYECTO (falta /api/projects/<nombre>)\n"
            "  * Falta el rol 'Cognitive Services User' (es obligatorio incluso\n"
            "    para el propietario del recurso)\n"
            "  * El modelo no está desplegado o tiene otro nombre",
        )


def revisar_content_understanding(entorno: dict[str, str], factura: Path | None) -> None:
    titulo("5. CONTENT UNDERSTANDING (extracción de información)")
    if not entorno["cu"]:
        omitir("Sin CONTENT_UNDERSTANDING_ENDPOINT; no se puede probar")
        return

    try:
        from azure.ai.contentunderstanding import ContentUnderstandingClient
        from azure.core.credentials import AzureKeyCredential
        from azure.identity import DefaultAzureCredential

        if entorno["cu_key"]:
            credencial = AzureKeyCredential(entorno["cu_key"])
            info("Usando clave de API")
        else:
            credencial = DefaultAzureCredential()
            info("Usando identidad administrada (recomendado)")

        cliente = ContentUnderstandingClient(
            endpoint=entorno["cu"], credential=credencial
        )
        bien("Se creó el ContentUnderstandingClient")

        # --------------------------------------------------------------
        # Comprobar los modelos por defecto ANTES de intentar analizar.
        # Es la causa más frecuente de fallo: sin este mapeo, los analizadores
        # preconstruidos responden "Default model deployment not configured",
        # un mensaje que no explica qué hacer ni dónde configurarlo.
        # --------------------------------------------------------------
        try:
            por_defecto = cliente.get_defaults()
            mapeo = getattr(por_defecto, "model_deployments", None) or {}
            if mapeo:
                bien(
                    f"Los modelos por defecto están configurados ({len(mapeo)} asignaciones)",
                    ", ".join(f"{k}->{v}" for k, v in list(mapeo.items())[:3]) + "…",
                )
                # Los alias son los que usan los analizadores preconstruidos.
                alias = [a for a in mapeo if a.startswith("prebuilt-analyzer-")]
                if alias:
                    bien(f"Los alias de los analizadores preconstruidos existen "
                         f"({len(alias)})")
                else:
                    mal(
                        "Faltan los alias 'prebuilt-analyzer-*'",
                        "Los analizadores preconstruidos los referencian en lugar "
                        "del nombre del modelo. Sin ellos, prebuilt-invoice falla "
                        "aunque el modelo esté desplegado.\n\n"
                        "Ejecute de nuevo:  python tools/provision_azure.py",
                    )
            else:
                mal(
                    "NO hay modelos por defecto configurados",
                    "Los analizadores preconstruidos fallarán con\n"
                    "'Default model deployment not configured'.\n\n"
                    "Ejecute:  python tools/provision_azure.py\n"
                    "Ese script los configura automáticamente.\n\n"
                    "O configúrelos a mano en:\n"
                    "  https://contentunderstanding.ai.azure.com/settings",
                )
        except Exception as exc:
            omitir(
                "No se pudieron leer los modelos por defecto",
                f"{type(exc).__name__}: {str(exc)[:200]}\n"
                "No es bloqueante para el resto del diagnóstico.",
            )

        if factura and factura.exists():
            datos = factura.read_bytes()
            tipo = "application/pdf" if factura.suffix.lower() == ".pdf" else "image/jpeg"

            # ------------------------------------------------------------------
            # Se prueba LA MISMA RUTA QUE USA LA APLICACIÓN, no el analizador
            # ideal. 'prebuilt-invoice' exige un modelo de finalización completo
            # y falla con ModelNotSupported en suscripciones que solo tienen
            # cuota para modelos mini (lo habitual en Azure for Students). La
            # aplicación cae entonces a 'prebuilt-read' con lectura
            # determinista, que sí funciona.
            #
            # Probar aquí solo 'prebuilt-invoice' daba un FALLA engañoso: el
            # diagnóstico decía que había un problema cuando la aplicación
            # extraía la factura perfectamente. Un diagnóstico que no refleja lo
            # que hace el producto no sirve.
            # ------------------------------------------------------------------
            info(f"Analizando {factura.name} ({len(datos):,} bytes)…")

            # Primero se informa de si el analizador ideal está disponible.
            prebuilt_invoice_ok = False
            motivo_invoice = ""
            try:
                p_ideal = cliente.begin_analyze_binary(
                    analyzer_id="prebuilt-invoice",
                    binary_input=datos,
                    content_type=tipo,
                )
                r_ideal = p_ideal.result()
                prebuilt_invoice_ok = bool(getattr(r_ideal, "contents", None))
                if not prebuilt_invoice_ok:
                    motivo_invoice = "no devolvió contenido"
            except Exception as exc:
                motivo_invoice = str(exc)
                # El detalle útil viene en el mensaje interno del servicio
                for fragmento in ("ModelNotSupported", "Default model",
                                  "not supported by this analyzer"):
                    if fragmento.lower() in motivo_invoice.lower():
                        motivo_invoice = "modelo de finalización no soportado"
                        break

            if prebuilt_invoice_ok:
                bien("Content Understanding extrajo la factura con prebuilt-invoice")
            else:
                omitir(
                    "'prebuilt-invoice' no está disponible en esta suscripción",
                    f"Motivo: {motivo_invoice}\n"
                    "Es habitual en suscripciones con cuota solo para modelos mini:\n"
                    "los analizadores de extracción exigen un modelo completo.\n"
                    "La aplicación usa automáticamente 'prebuilt-read' con lectura\n"
                    "determinista, que se comprueba a continuación.",
                )

            # Ahora se prueba el respaldo real: es lo que hará la aplicación.
            try:
                from app import extraer_factura

                extraido = extraer_factura(datos, factura.name)
                origen = extraido.get("origen", "?")
                proveedor = extraido.get("proveedor")
                total = extraido.get("total")

                if proveedor and total is not None:
                    bien(
                        f"La extracción de facturas funciona (vía '{origen}')"
                    )
                    info(f"  * Proveedor: {proveedor}")
                    info(f"  * Folio: {extraido.get('folio')}")
                    info(f"  * Fecha: {extraido.get('fecha')}")
                    sufijo = " (calculado como subtotal + IVA)" if extraido.get("total_calculado") else ""
                    info(f"  * Total: {total:,.2f}{sufijo}")
                    if extraido.get("total_calculado"):
                        info(
                            "El OCR descartó la línea del total, que es habitual en\n"
                            "  estas facturas; se obtiene sumando subtotal e IVA, que\n"
                            "  sí se leen. El resultado es el mismo importe."
                        )
                elif proveedor:
                    omitir(
                        "Se leyó el texto pero no el importe",
                        f"Proveedor: {proveedor}",
                    )
                else:
                    mal(
                        "La extracción de facturas no devolvió datos",
                        f"Origen probado: {origen}\n"
                        "Compruebe que el archivo sea una factura legible.",
                    )
            except ImportError:
                omitir(
                    "No se pudo importar la aplicación para probar la extracción",
                    "Ejecute el diagnóstico desde la raíz del proyecto.",
                )
            except Exception as exc:
                mal(
                    "Falló la extracción de facturas",
                    f"{type(exc).__name__}: {str(exc)[:200]}",
                )
        else:
            omitir(
                "No se analizó ningún archivo",
                "Pase --factura samples/factura_limpia.pdf para probar de verdad.",
            )
    except Exception as exc:
        mal(
            "Error en Content Understanding",
            f"{type(exc).__name__}: {exc}\n\n"
            "Causas típicas:\n"
            "  * 'Default model deployment not configured': faltan los\n"
            "    despliegues por defecto (gpt-4.1 y text-embedding-3-large)\n"
            "  * 'Access denied': falta el rol 'Cognitive Services User'\n"
            "  * La región del recurso no soporta Content Understanding",
        )


def revisar_language(entorno: dict[str, str]) -> None:
    titulo("6. AZURE AI LANGUAGE (análisis de texto)")
    if not (entorno["idioma"] and entorno["idioma_key"]):
        omitir("Sin LANGUAGE_ENDPOINT o LANGUAGE_KEY; no se puede probar")
        return
    try:
        from azure.ai.textanalytics import TextAnalyticsClient
        from azure.core.credentials import AzureKeyCredential

        cliente = TextAnalyticsClient(
            endpoint=entorno["idioma"],
            credential=AzureKeyCredential(entorno["idioma_key"]),
        )
        bien("Se creó el TextAnalyticsClient")

        prueba = "Llevo cuatro llamadas y nadie me contesta, necesito mi pedido hoy."
        sentimiento = cliente.analyze_sentiment([prueba])[0]
        bien("Análisis de sentimiento funcionando",
             f"resultado: {sentimiento.sentiment} "
             f"(neg {sentimiento.confidence_scores.negative:.0%})")

        frases = cliente.extract_key_phrases([prueba])[0]
        bien("Extracción de frases clave funcionando",
             f"{len(frases.key_phrases)} frases: {list(frases.key_phrases)[:4]}")

        entidades = cliente.recognize_entities([prueba])[0]
        bien("Reconocimiento de entidades funcionando",
             f"{len(entidades.entities)} entidades")
    except Exception as exc:
        mal("Error en Azure AI Language", f"{type(exc).__name__}: {exc}")


def revisar_voz(entorno: dict[str, str]) -> None:
    titulo("7. AZURE SPEECH (voz)")
    if not (entorno["voz_key"] and entorno["voz_region"]):
        omitir("Sin SPEECH_KEY o SPEECH_REGION; no se puede probar")
        return
    try:
        import azure.cognitiveservices.speech as speechsdk

        config = speechsdk.SpeechConfig(
            subscription=entorno["voz_key"], region=entorno["voz_region"]
        )
        config.speech_synthesis_voice_name = "es-MX-DaliaNeural"
        bien("Se creó SpeechConfig", f"región: {entorno['voz_region']}")

        sintetizador = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
        resultado = sintetizador.speak_text_async(
            "Bienvenido al portal de Distribuidora Río Claro."
        ).get()

        if resultado.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            bien("Síntesis de voz funcionando",
                 f"{len(resultado.audio_data):,} bytes de audio generados")
            info("Voz: es-MX-DaliaNeural")
        else:
            mal(
                "La síntesis de voz falló",
                f"motivo: {resultado.reason}\n"
                f"detalle: {resultado.cancellation_details.error_details if hasattr(resultado, 'cancellation_details') else ''}",
            )

        voces = speechsdk.SpeechSynthesizer(
            speech_config=config, audio_config=None
        ).get_voices_async("es-MX").get()
        if voces and voces.voices:
            bien(f"{len(voces.voices)} voces en español de México disponibles")
        else:
            omitir("No se pudo listar las voces (no es bloqueante)")
    except Exception as exc:
        mal("Error en Azure Speech", f"{type(exc).__name__}: {exc}")


def revisar_key_vault(entorno: dict[str, str]) -> None:
    titulo("8. AZURE KEY VAULT (seguridad de secretos)")
    if not entorno["kv"]:
        omitir("KEY_VAULT_URI no configurado; se usan variables de entorno")
        return
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        cliente = SecretClient(
            vault_url=entorno["kv"], credential=DefaultAzureCredential()
        )
        bien("Se creó el SecretClient")

        nombres = [s.name for s in cliente.list_properties_of_secrets()]
        if nombres:
            bien(f"{len(nombres)} secretos en el almacén", ", ".join(sorted(nombres)))
        else:
            omitir("El almacén está vacío",
                   "Cargue los secretos con tools/provision_azure.py")

        for nombre in ("foundry-project-endpoint", "speech-key", "language-key"):
            try:
                s = cliente.get_secret(nombre)
                bien(f"Secreto legible: {nombre}",
                     f"{s.value[:6]}… ({len(s.value)} caracteres)")
            except Exception:
                omitir(f"Secreto ausente: {nombre}")
    except Exception as exc:
        mal(
            "Error al leer Key Vault",
            f"{type(exc).__name__}: {exc}\n\n"
            "Verifique que su identidad tenga el rol 'Key Vault Secrets User'\n"
            "y que el almacén use control de acceso basado en roles (RBAC).",
        )


def revisar_datos_locales() -> None:
    titulo("9. FUENTE ÚNICA DE VERDAD (archivos locales)")
    archivos = [
        ("data/catalogo_unificado.csv", "catálogo unificado de las 5 sucursales"),
        ("data/politicas_y_pedidos_activos.txt", "políticas vigentes y pedidos"),
        ("data/historial_quejas.jsonl", "historial central de quejas"),
    ]
    for relativo, descripcion in archivos:
        ruta = RAIZ / relativo
        if ruta.exists():
            bien(relativo, f"{descripcion} · {ruta.stat().st_size:,} bytes")
        else:
            mal(f"Falta {relativo}", descripcion)

    try:
        import rio_claro as rc

        base = rc.cargar_base()
        bien(
            "El motor cargó la base de conocimiento",
            f"{len(base.productos)} productos · {len(base.pedidos)} pedidos · "
            f"{len(base.quejas)} quejas",
        )
        ctx, fuentes = rc.recuperar_contexto("cuánto cloro nos queda", base)
        # OJO: hay que comparar con el nombre MOSTRADO (con acentos), no con la
        # clave interna de la lista SUCURSALES ('Leon', 'Queretaro', ...), porque
        # el contexto que ve el modelo es el nombre con acento ('León', 'Querétaro').
        faltantes = [s for s in rc.SUCURSALES if rc.NOMBRE_SUCURSAL[s] not in ctx]
        if not faltantes:
            bien("La recuperación responde las 5 sucursales (Equidad)")
        else:
            mal(
                "La recuperación NO incluye las 5 sucursales",
                f"faltan: {faltantes}",
            )
    except Exception as exc:
        mal("Error al cargar el motor", f"{type(exc).__name__}: {exc}")

    samples = RAIZ / "samples"
    if samples.exists():
        pdfs = list(samples.glob("*.pdf"))
        jpgs = list(samples.glob("*.jpg"))
        if pdfs and jpgs:
            bien(
                "Facturas de prueba presentes",
                f"{len(pdfs)} PDF y {len(jpgs)} imágenes en samples/",
            )
        else:
            omitir(
                "Faltan facturas de prueba",
                "Ejecute:  python tools/generar_facturas.py",
            )
    else:
        omitir("No existe la carpeta samples/",
               "Ejecute:  python tools/generar_facturas.py")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico de Azure — Río Claro AI-901")
    parser.add_argument(
        "--factura",
        default="samples/factura_limpia.pdf",
        help="Archivo a analizar con Content Understanding",
    )
    args = parser.parse_args()

    print()
    print(f"{CIAN}╔{'═' * 72}╗{FIN}")
    print(f"{CIAN}║  DIAGNÓSTICO DE AZURE — PROYECTO AI-901 — RÍO CLARO{' ' * 22}║{FIN}")
    print(f"{CIAN}╚{'═' * 72}╝{FIN}")

    entorno = cargar_entorno()

    revisar_dependencias()
    revisar_configuracion(entorno)
    revisar_autenticacion(entorno)
    revisar_foundry(entorno)

    factura = Path(args.factura)
    if not factura.is_absolute():
        factura = RAIZ / factura
    revisar_content_understanding(entorno, factura)

    revisar_language(entorno)
    revisar_voz(entorno)
    revisar_key_vault(entorno)
    revisar_datos_locales()

    titulo("RESUMEN")
    total = _ok + _fallo + _omitido
    print(f"  {VERDE}Correctas: {_ok}{FIN}")
    print(f"  {ROJO}Fallidas:  {_fallo}{FIN}")
    print(f"  {AMARILLO}Omitidas:  {_omitido}{FIN}")
    print(f"  {GRIS}Total de comprobaciones: {total}{FIN}")

    if _fallo == 0 and _omitido == 0:
        print(f"\n{VERDE}Todo listo. Puede hacer la demo con Azure conectado.{FIN}")
    elif _fallo == 0:
        print(
            f"\n{AMARILLO}La app funcionará, pero {_omitido} servicio(s) están sin "
            f"configurar.{FIN}"
        )
        print("En la demo esos servicios aparecerán en modo ejemplo, bien etiquetados.")
        print("El enunciado puntúa más alto si funcionan de verdad.")
    else:
        print(f"\n{ROJO}Hay {_fallo} problema(s) que debe resolver antes de la demo.{FIN}")

    print()
    print(f"{GRIS}Ejecute este mismo diagnóstico en App Service desde la consola (SSH){FIN}")
    print(f"{GRIS}para confirmar que la identidad administrada también tiene permisos.{FIN}")
    print()
    return 1 if _fallo else 0


if __name__ == "__main__":
    raise SystemExit(main())
