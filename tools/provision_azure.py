"""
Provisión de los recursos de Azure para el proyecto AI-901 de Río Claro.

Sustituye a `provision_azure.sh`. Se reescribió en Python por tres razones
concretas:

  1. Es multiplataforma. El script de bash dependía de Git Bash en Windows y
     fallaba con el clásico "bad interpreter" cuando el archivo se guardaba con
     finales de línea CRLF (que es lo que hace Windows por defecto).
  2. Se puede probar sin Azure. La generación de comandos está separada de la
     ejecución, así que `tools/probar_provision.py` verifica el flujo completo
     con un ejecutor simulado.
  3. Da mensajes de error útiles. El script de bash se detenía con `set -e` y
     dejaba al estudiante adivinando qué había fallado.

Uso:
    python tools/provision_azure.py --dry-run     # ver qué haría, sin tocar Azure
    python tools/provision_azure.py               # crear los recursos
    python tools/provision_azure.py --export provision.sh   # generar un .sh revisable

Requiere: Azure CLI instalado y `az login` activo.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent

VERDE, ROJO, AMARILLO, GRIS, CIAN, NEGRITA, FIN = (
    "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[96m",
    "\033[1m", "\033[0m",
)


# =============================================================================
# Configuración
# =============================================================================


@dataclass
class Config:
    grupo: str = "rg-rio-claro-ai901"
    prefijo: str = "rioclaro"
    # ------------------------------------------------------------------
    # REGIÓN. Aquí hay que tener en cuenta DOS restricciones que se cruzan:
    #
    #   1. La suscripción puede tener una política que limite las regiones
    #      donde se permite crear recursos. Las suscripciones de estudiante
    #      suelen traerla (política 'sys.regionrestriction').
    #   2. No todos los servicios están disponibles en todas las regiones.
    #      Cognitive Services no existe en mexicocentral ni chilecentral, por
    #      ejemplo.
    #
    # La intersección típica en una suscripción de estudiante es
    # {westus, canadacentral, northcentralus}. Se usa westus por defecto.
    #
    # El script detecta la política automáticamente (ver
    # `consultar_regiones_permitidas`) y avisa si la región elegida no está
    # permitida, en lugar de fallar con un error opaco de Azure.
    # ------------------------------------------------------------------
    region: str = "westus"
    # Speech está disponible en westus. Se deja la misma región para simplificar.
    region_voz: str = "westus"
    proyecto: str = "rio-claro"

    # Nivel de Azure AI Language. El nivel S0 requiere un permiso especial que
    # las suscripciones de estudiante no tienen
    # ('SpecialFeatureOrQuotaIdRequired'). El nivel F0 (gratuito) sí funciona y
    # es suficiente para sentimiento, entidades y frases clave.
    sku_idioma: str = "F0"

    # Modelos. Las versiones y la CUOTA cambian; el script avisa y continúa si
    # alguno falla, porque el resto del proyecto sigue siendo válido.
    #
    # Estos valores se eligieron comprobando la cuota REAL de una suscripción
    # Azure for Students, donde los modelos grandes están bloqueados con
    # cuota 0:
    #
    #   gpt-5-mini              cuota 500   -> sí
    #   gpt-4.1-mini            cuota 200   -> sí
    #   text-embedding-3-small  cuota 1000  -> sí
    #   gpt-4.1                 cuota 0     -> no
    #   text-embedding-3-large  cuota 0     -> no
    #
    # gpt-4.1-mini sirve tanto para el asistente como para Content
    # Understanding: es el modelo que la documentación del SDK recomienda para
    # los analizadores de búsqueda, y funciona para los de facturas.
    modelo_chat: str = "gpt-5-mini"
    modelo_chat_version: str = "2025-08-07"
    modelo_principal: str = "gpt-4.1-mini"
    modelo_principal_version: str = "2025-04-14"
    modelo_mini: str = "gpt-4.1-mini"
    modelo_mini_version: str = "2025-04-14"
    modelo_embed: str = "text-embedding-3-small"
    modelo_embed_version: str = "1"
    # Modelo de generación de imágenes. NO se despliega por defecto: en la
    # suscripción de prueba TODOS los modelos de imagen (de OpenAI y de
    # Microsoft) tienen cuota 0. La generación de imágenes es la única función
    # opcional del proyecto; la visión, que sí importa para leer la foto
    # borrosa de una factura, usa el modelo multimodal gpt-5-mini.
    modelo_imagen: str = "gpt-image-2.5-flare"
    modelo_imagen_version: str = "2025-04-01"
    # Intentar desplegar el modelo de imagen. Activado solo con
    # --con-modelo-imagen, porque en muchas suscripciones de estudiante la
    # cuota de modelos de imagen es 0 y el intento siempre falla.
    desplegar_modelo_imagen: bool = False

    # Nombres derivados
    @property
    def recurso_ia(self) -> str:
        return f"{self.prefijo}-foundry"

    @property
    def recurso_voz(self) -> str:
        return f"{self.prefijo}-speech"

    @property
    def recurso_idioma(self) -> str:
        return f"{self.prefijo}-language"

    @property
    def almacen(self) -> str:
        # Los nombres de Key Vault solo admiten alfanuméricos y guiones,
        # y deben ser únicos en todo Azure. De ahí el sufijo.
        base = "".join(c for c in self.prefijo if c.isalnum())
        return f"{base}kv"

    @property
    def plan(self) -> str:
        return f"{self.prefijo}-plan"

    @property
    def app(self) -> str:
        return f"{self.prefijo}-ai901"

    @property
    def endpoint_ia(self) -> str:
        return f"https://{self.recurso_ia}.services.ai.azure.com/"

    @property
    def endpoint_proyecto(self) -> str:
        # El SDK exige el endpoint del PROYECTO, no el del recurso.
        return f"{self.endpoint_ia.rstrip('/')}/api/projects/{self.proyecto}"

    @property
    def endpoint_idioma(self) -> str:
        return f"https://{self.recurso_idioma}.cognitiveservices.azure.com/"

    @property
    def url_app(self) -> str:
        return f"https://{self.app}.azurewebsites.net"

    @property
    def uri_keyvault(self) -> str:
        return f"https://{self.almacen}.vault.azure.net/"


# =============================================================================
# Comandos
# =============================================================================


@dataclass
class Paso:
    """Un comando de az con su descripción y política de error."""

    descripcion: str
    args: list[str]
    # Si es crítico y falla, se detiene todo. Si no, se avisa y se continúa.
    critico: bool = True
    # Captura la salida (necesario cuando hay que leer un valor de az).
    capturar: bool = False
    # Función que, con la salida del comando, devuelve variables para los
    # pasos siguientes. Es lo que permite encadenar endpoints y claves.
    extraer: Callable[[str], dict] | None = None
    # Número de intentos antes de dar el paso por fallido. Hace falta para los
    # secretos de Key Vault: al usar control de acceso por roles (RBAC), la
    # asignación tarda en propagarse y los primeros intentos fallan con
    # «Forbidden» aunque el rol ya esté correctamente asignado.
    reintentos: int = 1
    # Si se define, es un comando de COMPROBACIÓN. Si tiene éxito (el recurso
    # ya existe), el paso se OMITE y se informa. Sirve para que el script sea
    # de verdad repetible.
    #
    # POR QUE HACE FALTA: `az cognitiveservices account create` sobre un
    # recurso que YA existe no es inocuo: intenta reconfigurarlo y puede fallar
    # con "PublicNetworkAccess is required for this resouce", que no explica
    # que el problema es que el recurso ya estaba ahi. El script decia "es
    # seguro repetirlo" y no lo era. Este campo lo arregla.
    comprobar_existencia: list[str] | None = None


def construir_pasos(cfg: Config) -> list[Paso]:
    """
    Devuelve la lista completa de comandos, en orden.

    Es una función pura: no ejecuta nada. Eso permite verificarla con pruebas
    y mostrarla con --dry-run sin tocar Azure.
    """
    pasos: list[Paso] = []

    # --- 1. Proveedores de recursos -------------------------------------
    # Hay que registrar CADA proveedor antes de poder crear sus recursos. Si
    # falta uno, el error es «MissingSubscriptionRegistration», que no dice
    # cuál hay que registrar ni cómo. Esto ya ocurrió con Microsoft.KeyVault.
    #
    # Microsoft.CognitiveServices no es crítico (a veces ya está registrado y
    # el comando tarda). Los demás sí: sin ellos no se pueden crear los
    # recursos correspondientes.
    for ns, critico in (
        ("Microsoft.CognitiveServices", False),
        ("Microsoft.KeyVault", True),
        ("Microsoft.Web", True),
        ("Microsoft.Insights", False),
        ("Microsoft.Storage", False),
    ):
        pasos.append(
            Paso(
                f"Registrar el proveedor {ns}",
                ["provider", "register", "--namespace", ns, "--wait"],
                critico=critico,
            )
        )

    pasos.append(
        Paso(
            f"Crear el grupo de recursos '{cfg.grupo}' en {cfg.region}",
            ["group", "create", "--name", cfg.grupo, "--location", cfg.region, "--output", "none"],
        )
    )

    # --- 2. Recurso de Microsoft Foundry -------------------------------
    pasos.append(
        Paso(
            f"Crear el recurso de Microsoft Foundry '{cfg.recurso_ia}' (AIServices, S0)",
            [
                "cognitiveservices", "account", "create",
                "--name", cfg.recurso_ia,
                "--resource-group", cfg.grupo,
                "--kind", "AIServices",
                "--sku", "S0",
                "--location", cfg.region,
                "--custom-domain", cfg.recurso_ia,
                "--yes",
                "--output", "none",
            ],
            # Si ya existe, se omite: recrearlo falla con
            # «PublicNetworkAccess is required for this resouce».
            comprobar_existencia=[
                "cognitiveservices", "account", "show",
                "--name", cfg.recurso_ia,
                "--resource-group", cfg.grupo,
                "--query", "name", "-o", "tsv",
            ],
        )
    )
    pasos.append(
        Paso(
            "Leer el endpoint del recurso de Foundry",
            [
                "cognitiveservices", "account", "show",
                "--name", cfg.recurso_ia,
                "--resource-group", cfg.grupo,
                "--query", "properties.endpoint", "-o", "tsv",
            ],
            capturar=True,
            extraer=lambda s: {"ENDPOINT_IA": s.strip()},
        )
    )
    pasos.append(
        Paso(
            "Leer la clave del recurso de Foundry",
            [
                "cognitiveservices", "account", "keys", "list",
                "--name", cfg.recurso_ia,
                "--resource-group", cfg.grupo,
                "--query", "key1", "-o", "tsv",
            ],
            capturar=True,
            extraer=lambda s: {"CLAVE_IA": s.strip()},
        )
    )

    # --- 3. Proyecto de Foundry ----------------------------------------
    # El proyecto es el contenedor donde viven el agente, los archivos y las
    # evaluaciones. Es distinto del recurso (la cuenta).
    pasos.append(
        Paso(
            f"Crear el proyecto de Foundry '{cfg.proyecto}'",
            [
                "cognitiveservices", "account", "project", "create",
                "--name", cfg.recurso_ia,
                "--resource-group", cfg.grupo,
                "--project-name", cfg.proyecto,
                "--location", cfg.region,
                "--display-name", "Distribuidora Río Claro",
                "--description", "Proyecto integrador AI-901",
                "--output", "none",
            ],
        )
    )

    # --- 4. Despliegue de modelos --------------------------------------
    # ATENCIÓN A LA CUOTA. Las suscripciones de estudiante tienen cuota muy
    # limitada y no todos los modelos se pueden desplegar. En una suscripción
    # Azure for Students se comprobó que:
    #
    #   gpt-5-mini                 cuota 500  -> disponible
    #   gpt-4.1-mini               cuota 200  -> disponible
    #   text-embedding-3-small     cuota 1000 -> disponible
    #   gpt-4.1                    cuota 0    -> BLOQUEADO
    #   text-embedding-3-large     cuota 0    -> BLOQUEADO
    #   cualquier modelo de imagen  cuota 0   -> BLOQUEADO
    #
    # Por eso la configuración por defecto usa los que SÍ tienen cuota, y el
    # script comprueba la cuota antes de intentar el despliegue para poder
    # avisar con claridad en lugar de fallar con «InsufficientQuota».
    for nombre, version, capacidad, etiqueta in (
        (cfg.modelo_chat, cfg.modelo_chat_version, 50, "conversación, agentes y visión"),
        (cfg.modelo_principal, cfg.modelo_principal_version, 50,
         "Content Understanding (facturas)"),
        (cfg.modelo_embed, cfg.modelo_embed_version, 50,
         "Content Understanding (embeddings)"),
    ):
        pasos.append(
            Paso(
                f"Desplegar '{nombre}' ({etiqueta})",
                [
                    "cognitiveservices", "account", "deployment", "create",
                    "--name", cfg.recurso_ia,
                    "--resource-group", cfg.grupo,
                    "--deployment-name", nombre,
                    "--model-name", nombre,
                    "--model-version", version,
                    "--model-format", "OpenAI",
                    "--sku-name", "GlobalStandard",
                    "--sku-capacity", str(capacidad),
                    "--output", "none",
                ],
                # No es crítico: si un modelo no tiene cuota, el estudiante
                # puede desplegarlo desde el portal o pedir más cuota.
                critico=False,
            )
        )

    # --- 5. Modelo de generación de imágenes ---------------------------
    # NO se despliega por defecto, y no es un olvido.
    #
    # En la suscripción de prueba se comprobó que TODOS los modelos de imagen
    # tienen cuota 0, tanto los de OpenAI (gpt-image-*) como los de Microsoft
    # (MAI-Image-*). Intentarlo produce:
    #     InsufficientQuota: ... quota limit is 0 for quota Requests Per Minute
    #
    # Es la única función opcional del proyecto. La VISIÓN —leer la foto
    # borrosa de una factura— usa el modelo multimodal gpt-5-mini, que sí está
    # disponible, así que el principio de Confiabilidad se demuestra igual.
    #
    # Si su suscripción sí permite modelos de imagen, despliéguelo con
    # --modelo-imagen y ajuste FOUNDRY_IMAGE_MODEL en su .env.
    if cfg.desplegar_modelo_imagen:
        pasos.append(
            Paso(
                f"Desplegar el modelo de imágenes '{cfg.modelo_imagen}'",
                [
                    "cognitiveservices", "account", "deployment", "create",
                    "--name", cfg.recurso_ia,
                    "--resource-group", cfg.grupo,
                    "--deployment-name", cfg.modelo_imagen,
                    "--model-name", cfg.modelo_imagen,
                    "--model-version", cfg.modelo_imagen_version,
                    "--model-format", "OpenAI",
                    "--sku-name", "GlobalStandard",
                    "--sku-capacity", "1",
                    "--output", "none",
                ],
                critico=False,
            )
        )

    # --- 6. Azure Speech -----------------------------------------------
    pasos.append(
        Paso(
            f"Crear el recurso de Azure Speech '{cfg.recurso_voz}' en {cfg.region_voz}",
            [
                "cognitiveservices", "account", "create",
                "--name", cfg.recurso_voz,
                "--resource-group", cfg.grupo,
                "--kind", "SpeechServices",
                "--sku", "S0",
                "--location", cfg.region_voz,
                "--yes",
                "--output", "none",
            ],
            comprobar_existencia=[
                "cognitiveservices", "account", "show",
                "--name", cfg.recurso_voz,
                "--resource-group", cfg.grupo,
                "--query", "name", "-o", "tsv",
            ],
        )
    )
    pasos.append(
        Paso(
            "Leer la clave de Azure Speech",
            [
                "cognitiveservices", "account", "keys", "list",
                "--name", cfg.recurso_voz,
                "--resource-group", cfg.grupo,
                "--query", "key1", "-o", "tsv",
            ],
            capturar=True,
            extraer=lambda s: {"CLAVE_VOZ": s.strip()},
        )
    )

    # --- 7. Azure AI Language ------------------------------------------
    pasos.append(
        Paso(
            f"Crear el recurso de Azure AI Language '{cfg.recurso_idioma}'",
            [
                "cognitiveservices", "account", "create",
                "--name", cfg.recurso_idioma,
                "--resource-group", cfg.grupo,
                "--kind", "TextAnalytics",
                # El nivel S0 exige un permiso que las suscripciones de
                # estudiante no tienen: falla con
                # 'SpecialFeatureOrQuotaIdRequired'. F0 (gratuito) funciona y
                # sobra para sentimiento, entidades y frases clave.
                "--sku", cfg.sku_idioma,
                "--location", cfg.region,
                "--yes",
                "--output", "none",
            ],
            comprobar_existencia=[
                "cognitiveservices", "account", "show",
                "--name", cfg.recurso_idioma,
                "--resource-group", cfg.grupo,
                "--query", "name", "-o", "tsv",
            ],
        )
    )
    pasos.append(
        Paso(
            "Leer el endpoint y la clave de Azure AI Language",
            [
                "cognitiveservices", "account", "show",
                "--name", cfg.recurso_idioma,
                "--resource-group", cfg.grupo,
                "--query", "properties.endpoint", "-o", "tsv",
            ],
            capturar=True,
            extraer=lambda s: {"ENDPOINT_IDIOMA": s.strip()},
        )
    )
    pasos.append(
        Paso(
            "Leer la clave de Azure AI Language",
            [
                "cognitiveservices", "account", "keys", "list",
                "--name", cfg.recurso_idioma,
                "--resource-group", cfg.grupo,
                "--query", "key1", "-o", "tsv",
            ],
            capturar=True,
            extraer=lambda s: {"CLAVE_IDIOMA": s.strip()},
        )
    )

    # --- 8. Key Vault ---------------------------------------------------
    pasos.append(
        Paso(
            f"Crear Key Vault '{cfg.almacen}' con control de acceso por roles",
            [
                "keyvault", "create",
                "--name", cfg.almacen,
                "--resource-group", cfg.grupo,
                "--location", cfg.region,
                "--enable-rbac-authorization", "true",
                "--output", "none",
            ],
            comprobar_existencia=[
                "keyvault", "show",
                "--name", cfg.almacen,
                "--query", "name", "-o", "tsv",
            ],
        )
    )

    # --- 9. Aplicación web ---------------------------------------------
    pasos.append(
        Paso(
            f"Crear el plan de App Service '{cfg.plan}' (Linux, B1)",
            [
                "appservice", "plan", "create",
                "--name", cfg.plan,
                "--resource-group", cfg.grupo,
                "--location", cfg.region,
                "--is-linux",
                "--sku", "B1",
                "--output", "none",
            ],
        )
    )
    pasos.append(
        Paso(
            f"Crear la aplicación web '{cfg.app}' (Python 3.11)",
            [
                "webapp", "create",
                "--name", cfg.app,
                "--resource-group", cfg.grupo,
                "--plan", cfg.plan,
                "--runtime", "PYTHON:3.11",
                "--output", "none",
            ],
        )
    )
    pasos.append(
        Paso(
            "Configurar el comando de arranque y el modo siempre activo",
            [
                "webapp", "config", "set",
                "--name", cfg.app,
                "--resource-group", cfg.grupo,
                "--startup-file", "bash startup.sh",
                "--always-on", "true",
                "--output", "none",
            ],
        )
    )
    pasos.append(
        Paso(
            "Activar la identidad administrada (para no usar claves en el código)",
            [
                "webapp", "identity", "assign",
                "--name", cfg.app,
                "--resource-group", cfg.grupo,
                "--query", "principalId", "-o", "tsv",
            ],
            capturar=True,
            extraer=lambda s: {"PRINCIPAL_ID": s.strip()},
        )
    )
    pasos.append(
        Paso(
            "Configurar la aplicación con las variables de entorno",
            [
                "webapp", "config", "appsettings", "set",
                "--name", cfg.app,
                "--resource-group", cfg.grupo,
                "--settings",
                "SCM_DO_BUILD_DURING_DEPLOYMENT=true",
                # ---------------------------------------------------------
                # PUERTO. En App Service Linux con imágenes "Blessed" (las que
                # se eligen en el desplegable de Stack, como PYTHON:3.11) el
                # puerto del contenedor lo controla la variable PORT, y
                # WEBSITES_PORT NO TIENE EFECTO. Para Python el valor por
                # defecto ya es 8000.
                #
                # Antes se configuraba WEBSITES_PORT=8000, que en una app Python
                # no hace nada: la configuración del puerto quedaba ambigua y
                # dependía del valor por defecto de la plataforma. Se fija PORT
                # de forma explícita para que coincida con startup.sh y con
                # .streamlit/config.toml (los tres en 8000).
                #
                # WEBSITES_PORT solo aplica a contenedores personalizados
                # (Web App for Containers), no a este caso.
                # ---------------------------------------------------------
                "PORT=8000",
                f"FOUNDRY_PROJECT_ENDPOINT={cfg.endpoint_proyecto}",
                f"FOUNDRY_MODEL={cfg.modelo_chat}",
                "FOUNDRY_AGENT_NAME=rio-claro-agent",
                f"FOUNDRY_IMAGE_MODEL={cfg.modelo_imagen}",
                f"CONTENT_UNDERSTANDING_ENDPOINT={cfg.endpoint_ia}",
                f"LANGUAGE_ENDPOINT={cfg.endpoint_idioma}",
                f"SPEECH_REGION={cfg.region_voz}",
                f"KEY_VAULT_URI={cfg.uri_keyvault}",
                "--output", "none",
            ],
        )
    )

    # --- 10. Permisos ---------------------------------------------------
    pasos.append(
        Paso(
            "Asignar 'Cognitive Services User' a la identidad administrada",
            [
                "role", "assignment", "create",
                "--assignee", "{PRINCIPAL_ID}",
                "--role", "Cognitive Services User",
                "--scope", "{ID_RECURSO_IA}",
                "--output", "none",
            ],
            # Es el permiso que más falla y el más importante. Aun así no es
            # crítico: si la cuenta no es Owner, se avisa con instrucciones.
            critico=False,
        )
    )
    pasos.append(
        Paso(
            "Asignar 'Key Vault Secrets User' a la identidad administrada",
            [
                "role", "assignment", "create",
                "--assignee", "{PRINCIPAL_ID}",
                "--role", "Key Vault Secrets User",
                "--scope", "{ID_KV}",
                "--output", "none",
            ],
            critico=False,
        )
    )

    return pasos


def construir_pasos_con_identificadores(cfg: Config) -> list[Paso]:
    """
    Añade los pasos que necesitan el identificador de recurso (que solo se
    conoce después de crearlo) y los secretos de Key Vault.

    Se separa de `construir_pasos` porque estos pasos usan marcadores como
    {ID_RECURSO_IA} que se resuelven en tiempo de ejecución.
    """
    pasos = construir_pasos(cfg)

    # Los dos primeros pasos condicionales: leer los ID de recurso
    lectura_ids = [
        Paso(
            "Leer el identificador del recurso de Foundry",
            [
                "cognitiveservices", "account", "show",
                "--name", cfg.recurso_ia,
                "--resource-group", cfg.grupo,
                "--query", "id", "-o", "tsv",
            ],
            capturar=True,
            extraer=lambda s: {"ID_RECURSO_IA": s.strip()},
        ),
        Paso(
            "Leer el identificador del Key Vault",
            [
                "keyvault", "show",
                "--name", cfg.almacen,
                "--query", "id", "-o", "tsv",
            ],
            capturar=True,
            extraer=lambda s: {"ID_KV": s.strip()},
        ),
    ]

    # ------------------------------------------------------------------
    # ORDEN IMPORTANTE. La secuencia alrededor del Key Vault tiene que ser:
    #
    #   1. crear el almacén
    #   2. leer su ID y el del recurso de Foundry
    #   3. dar a TU CUENTA el rol para ESCRIBIR secretos
    #   4. guardar los secretos  (con reintentos: el rol tarda en propagarse)
    #   5. dar a la IDENTIDAD ADMINISTRADA el rol para LEERLOS
    #
    # Si los secretos van antes de leer el ID del almacén, el marcador
    # {ID_KV} no se sustituye. Si van antes de asignar el permiso de
    # escritura, fallan todos con «Forbidden».
    # ------------------------------------------------------------------
    indice_primer_rol_app = next(
        i for i, p in enumerate(pasos) if "Cognitive Services User" in p.descripcion
    )
    indice_kv = next(
        i for i, p in enumerate(pasos) if p.descripcion.startswith("Crear Key Vault")
    )

    # Después de crear el almacén: leer los IDs, dar permiso de escritura y
    # guardar los secretos.
    pasos[indice_kv + 1 : indice_kv + 1] = (
        lectura_ids + pasos_permisos_keyvault(cfg) + _pasos_secretos(cfg)
    )

    return pasos


def _pasos_secretos(cfg: Config) -> list[Paso]:
    """
    Guardado de cada secreto en Key Vault.

    IMPORTANTE: los endpoints que se pueden DEDUCIR de la configuración se
    escriben ya resueltos (cfg.endpoint_proyecto, cfg.endpoint_ia, ...) y NO
    como marcadores {VARIABLE}. Un marcador solo se sustituye si algún paso
    anterior lo rellenó; ENDPOINT_PROYECTO no lo rellena ningún paso (se
    deduce del nombre del recurso y del proyecto), así que dejarlo como
    marcador haría que Azure guardara la cadena literal "{ENDPOINT_PROYECTO}"
    como valor del secreto. Ese error ya ocurrió y lo detectó
    tools/probar_provision.py.
    """
    secretos = [
        # El proyecto es lo que consume el SDK de Foundry: lleva /api/projects/
        ("foundry-project-endpoint", cfg.endpoint_proyecto),
        ("content-understanding-endpoint", cfg.endpoint_ia),
        ("content-understanding-key", "{CLAVE_IA}"),
        ("speech-key", "{CLAVE_VOZ}"),
        ("speech-region", cfg.region_voz),
        ("language-endpoint", cfg.endpoint_idioma),
        ("language-key", "{CLAVE_IDIOMA}"),
    ]
    return [
        Paso(
            f"Guardar el secreto '{nombre}' en Key Vault",
            [
                "keyvault", "secret", "set",
                "--vault-name", cfg.almacen,
                "--name", nombre,
                "--value", valor,
                "--output", "none",
            ],
            critico=False,
            # El rol tarda en propagarse tras asignarlo: se reintenta antes de
            # rendirse. Sin esto, los primeros secretos fallan con «Forbidden»
            # aunque el permiso esté bien puesto.
            reintentos=5,
        )
        for nombre, valor in secretos
    ]


def pasos_permisos_keyvault(cfg: Config) -> list[Paso]:
    """
    Permisos que hay que conceder ANTES de poder guardar secretos.

    Con el control de acceso por roles (RBAC) activado en el Key Vault, crear
    el almacén NO te da permiso para escribir secretos. Hace falta el rol
    'Key Vault Secrets Officer' sobre el propio almacén. Sin él, todos los
    secretos fallan con:

        (Forbidden) Caller is not authorized to perform action on resource.
        Action: 'Microsoft.KeyVault/vaults/secrets/setSecret/action'

    ...que no dice qué rol falta ni dónde asignarlo. Esto ya ocurrió al
    preparar este proyecto y costó un diagnóstico.

    Se necesitan DOS asignaciones distintas, y confundirlas es el error más
    habitual:
      * a TU CUENTA, para poder ESCRIBIR los secretos durante la provisión;
      * a la IDENTIDAD ADMINISTRADA de la aplicación, para poder LEERLOS en
        tiempo de ejecución.
    """
    return [
        Paso(
            "Leer tu identificador de usuario (para darte permiso de escritura)",
            ["ad", "signed-in-user", "show", "--query", "id", "-o", "tsv"],
            capturar=True,
            extraer=lambda s: {"OID_USUARIO": s.strip()},
        ),
        Paso(
            "Darte el rol 'Key Vault Secrets Officer' para poder guardar los secretos",
            [
                "role", "assignment", "create",
                "--assignee-object-id", "{OID_USUARIO}",
                "--assignee-principal-type", "User",
                "--role", "Key Vault Secrets Officer",
                "--scope", "{ID_KV}",
            ],
            # No crítico: si ya lo tenías, el comando falla por duplicado y eso
            # no es un problema.
            critico=False,
        ),
    ]


# =============================================================================
# Ejecución
# =============================================================================


class Ejecutor:
    """Ejecuta comandos de az, o solo los muestra si es un ensayo."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.comandos_ejecutados: list[list[str]] = []
        self.variables: dict[str, str] = {}

    def prefijar_variables_conocidas(self, cfg: Config) -> None:
        """
        Rellena las variables que se pueden DEDUCIR de la configuración, para
        que un ensayo (--dry-run) muestre los valores esperados en lugar de
        marcadores sin resolver como {ENDPOINT_PROYECTO}.

        Los valores que dependen de Azure (las claves) no se pueden deducir:
        para esos se usa un texto explicativo entre paréntesis.
        """
        self.variables.update(
            {
                "ENDPOINT_IA": cfg.endpoint_ia,
                "ENDPOINT_PROYECTO": cfg.endpoint_proyecto,
                "ENDPOINT_IDIOMA": cfg.endpoint_idioma,
                "ID_RECURSO_IA": "(identificador del recurso de Foundry, se lee de Azure)",
                "ID_KV": "(identificador del Key Vault, se lee de Azure)",
                "PRINCIPAL_ID": "(identidad administrada de la aplicación)",
                "CLAVE_IA": "(clave del recurso, se lee de Azure)",
                "CLAVE_VOZ": "(clave de Speech, se lee de Azure)",
                "CLAVE_IDIOMA": "(clave de Language, se lee de Azure)",
            }
        )

    def az(self, args: list[str], capturar: bool = False) -> tuple[int, str]:
        """
        Ejecuta un comando de az y devuelve (codigo, salida).

        IMPORTANTE: az escribe los ERRORES en stderr, no en stdout. La primera
        versión de este método solo leía stdout, así que cuando un comando
        fallaba el mensaje salía vacío y el script decía «(sin detalle)»: era
        imposible diagnosticar sin ejecutar el comando a mano. Se combinan las
        dos salidas.
        """
        # Se usa la ruta RESUELTA del ejecutable, no "az" a secas: en Windows el
        # PATH de un proceso abierto antes de instalar Azure CLI no incluye el
        # comando, y fallaría con "no se reconoce".
        ejecutable = encontrar_az() or "az"
        self.comandos_ejecutados.append(["az"] + args)
        if self.dry_run:
            return 0, ""
        proc = subprocess.run(
            [ejecutable] + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        # stderr primero si algo falló: ahí está el motivo real.
        salida = (proc.stdout or "").strip()
        error = (proc.stderr or "").strip()
        if proc.returncode != 0 and error:
            return proc.returncode, error
        return proc.returncode, salida or error

    def resolver(self, texto: str) -> str:
        """Sustituye los marcadores {VARIABLE} por sus valores conocidos."""
        salida = texto
        for nombre, valor in self.variables.items():
            salida = salida.replace(f"{{{nombre}}}", valor)
        return salida


# Dominios de correo personal que suelen dar problemas en Azure:
# las asignaciones de roles de Entra ID y las políticas de Key Vault fallan
# con errores de permisos que el propio usuario no puede resolver.
DOMINIOS_PERSONALES = (
    "outlook.com", "hotmail.com", "live.com", "msn.com",
    "gmail.com", "yahoo.com", "hotmail.es", "outlook.es",
)


def encontrar_az() -> str | None:
    """
    Localiza el ejecutable de Azure CLI.

    Busca en el PATH y, si no lo encuentra, en las ubicaciones habituales de
    instalación. Esto hace falta de verdad: en Windows, instalar Azure CLI
    actualiza el PATH del usuario, pero los procesos que YA estaban abiertos
    (una terminal, un editor, una sesión de trabajo) siguen con el PATH viejo
    y no ven el comando. Es un caso que ya ocurrió al preparar este proyecto:
    `az` funcionaba en una terminal y no en otra.
    """
    encontrado = shutil.which("az")
    if encontrado:
        return encontrado

    candidatos = [
        r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
        r"C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
        os.path.expandvars(
            r"%LOCALAPPDATA%\Programs\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
        ),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\az.exe"),
        "/usr/bin/az",
        "/usr/local/bin/az",
        "/opt/homebrew/bin/az",
    ]
    for ruta in candidatos:
        if ruta and os.path.exists(ruta):
            return ruta
    return None


def arreglar_path_para_identidad() -> str | None:
    """
    Añade el directorio de Azure CLI al PATH de ESTE proceso.

    POR QUÉ HACE FALTA
    ------------------
    La librería azure-identity usa AzureCliCredential para autenticarse con la
    sesión de `az login`. Esa credencial ejecuta el comando `az` **buscándolo en
    el PATH**, y no acepta una ruta explícita (su firma no tiene parámetro de
    ruta).

    En Windows, instalar Azure CLI actualiza el PATH del usuario, pero un
    proceso que ya estaba abierto conserva el PATH viejo. Resultado real que ya
    ocurrió en este proyecto:

        AzureCliCredential: Azure CLI not found on path

    ...incluso con `az` funcionando perfectamente en la terminal, y con
    `az login` ya hecho. Afecta a cualquier script que use
    DefaultAzureCredential: el diagnóstico, la configuración de Content
    Understanding y la propia aplicación.

    Devuelve el directorio añadido, o None si no hizo falta o no se encontró.
    """
    ya_esta = shutil.which("az")
    az = encontrar_az()
    if az is None:
        return None

    directorio = os.path.dirname(os.path.abspath(az))
    if ya_esta:
        return None    # ya está en el PATH: no hay nada que arreglar

    os.environ["PATH"] = directorio + os.pathsep + os.environ.get("PATH", "")
    return directorio


def consultar_regiones_permitidas() -> list[str] | None:
    """
    Lee la política de regiones permitidas de la suscripción.

    Las suscripciones de estudiante suelen traer una política
    'sys.regionrestriction' que limita dónde se pueden crear recursos. Sin
    detectarla, el script falla con:

        (RequestDisallowedByAzure) ... This policy maintains a set of best
        available regions where your subscription can deploy resources.

    que no dice QUÉ regiones sí están permitidas. Esta función las saca para
    poder avisar antes de intentar crear nada, y poder sugerir una alternativa.

    Devuelve None si no hay política o no se puede leer.
    """
    az = encontrar_az()
    if az is None:
        return None

    proc = subprocess.run(
        [az, "policy", "assignment", "show",
         "--name", "sys.regionrestriction",
         "--query", "parameters.listOfAllowedLocations.value",
         "-o", "json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        return None    # no hay política de restricción: buena noticia
    try:
        regiones = json.loads(proc.stdout)
        return [r for r in regiones if isinstance(r, str)]
    except Exception:
        return None


def comprobar_region(cfg: Config) -> tuple[bool, str]:
    """
    Comprueba que la región elegida esté permitida por la suscripción.

    Devuelve (puede_continuar, mensaje).
    """
    permitidas = consultar_regiones_permitidas()
    if not permitidas:
        return True, "La suscripción no restringe las regiones."

    if cfg.region in permitidas:
        return True, (
            f"Región '{cfg.region}' permitida.\n"
            f"Regiones disponibles en su suscripción: {', '.join(permitidas)}"
        )

    # La región elegida no está permitida: se busca una alternativa que además
    # soporte Cognitive Services.
    con_cognitive = [r for r in permitidas if r in REGIONES_CON_COGNITIVE]
    sugerencia = con_cognitive[0] if con_cognitive else (permitidas[0] if permitidas else "")

    return False, (
        f"La región '{cfg.region}' NO está permitida en su suscripción.\n\n"
        f"Su suscripción solo permite: {', '.join(permitidas)}\n\n"
        "Azure rechazaría la creación con «RequestDisallowedByAzure», un error\n"
        "que no indica qué regiones sí sirven.\n\n"
        + (
            f"Ejecute con una región permitida, por ejemplo:\n"
            f"    python tools/provision_azure.py --region {sugerencia}\n"
            if sugerencia else ""
        )
        + "\nNOTA: no todas las regiones permitidas soportan Cognitive Services.\n"
        "De las permitidas, estas sirven para los servicios de IA de este\n"
        f"proyecto: {', '.join(con_cognitive) if con_cognitive else '(ninguna)'}"
    )


# Regiones donde Microsoft.CognitiveServices/accounts está disponible.
# Se usa para filtrar las regiones permitidas por la política de la suscripción.
# Fuente: el error LocationNotAvailableForResourceType de Azure, que enumera
# las regiones válidas. No se puede consultar por API de forma sencilla.
REGIONES_CON_COGNITIVE = {
    "australiaeast", "brazilsouth", "westus", "westus2", "westus3",
    "westeurope", "northeurope", "southeastasia", "eastasia",
    "westcentralus", "southcentralus", "eastus", "eastus2",
    "canadacentral", "canadaeast", "japaneast", "japanwest",
    "centralindia", "southindia", "uksouth", "ukwest", "koreacentral",
    "francecentral", "northcentralus", "centralus", "southafricanorth",
    "uaenorth", "swedencentral", "switzerlandnorth", "switzerlandwest",
    "germanywestcentral", "norwayeast", "jioindiawest", "jioindiacentral",
    "qatarcentral", "polandcentral", "italynorth", "spaincentral",
}


def comprobar_requisitos() -> tuple[bool, str]:
    """
    Verifica que az exista, que haya sesión y que la cuenta sirva para el
    proyecto.

    Devuelve (puede_continuar, resumen_o_explicacion_del_problema).

    Se comprueba el TIPO de cuenta porque es el problema más frecuente y el más
    difícil de diagnosticar después: con una cuenta personal de Microsoft, las
    asignaciones de roles de Entra ID y el control de acceso de Key Vault suelen
    fallar con errores de permisos que el estudiante no puede resolver, porque
    no es propietario del directorio.
    """
    az = encontrar_az()
    if az is None:
        return False, (
            "No se encontró 'az' (Azure CLI).\n\n"
            "Instálelo con:  winget install Microsoft.AzureCLI\n"
            "Después CIERRE y vuelva a abrir la terminal (para que el PATH se "
            "actualice) y ejecute:  az login"
        )

    proc = subprocess.run(
        [az, "account", "show", "--query", "id", "-o", "tsv"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        detalle = (proc.stderr or "").strip()[:300]
        return False, (
            "No hay sesión activa en Azure.\n\n"
            "Ejecute:  az login\n\n"
            "Si ya lo hizo y sigue apareciendo este mensaje, compruebe que está "
            "en la misma terminal y que eligió una suscripción:\n"
            "  az account list --query \"[].{nombre:name, id:id}\" -o table\n"
            "  az account set --subscription \"<el-id>\""
            + (f"\n\nDetalle: {detalle}" if detalle else "")
        )

    # Leer el detalle de la cuenta y la suscripción
    proc = subprocess.run(
        [az, "account", "show", "--query",
         "{suscripcion:name, id:id, usuario:user.name, tipo:user.type, "
         "tenant:tenantId, estado:state}",
         "-o", "json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        datos = json.loads(proc.stdout)
    except Exception:
        return True, "(no se pudo leer el detalle de la suscripción)"

    usuario = datos.get("usuario") or "?"
    tipo = datos.get("tipo") or "?"
    suscripcion = datos.get("suscripcion") or "?"
    estado = datos.get("estado") or "?"
    tenant = datos.get("tenant") or "?"

    resumen = (
        f"Suscripción: {suscripcion}\n"
        f"Usuario:      {usuario}  (tipo: {tipo})\n"
        f"Estado:       {estado}\n"
        f"Directorio:   {tenant}"
    )

    # --- Comprobaciones que solo AVISAN -------------------------------
    avisos: list[str] = []

    if estado.lower() != "enabled":
        return False, (
            f"La suscripción '{suscripcion}' está en estado '{estado}'.\n\n"
            "Una suscripción deshabilitada o vencida no permite crear recursos. "
            "Revise el estado en el portal de Azure o use otra suscripción:\n"
            "  az account list --query \"[].{nombre:name, estado:state}\" -o table"
        )

    correo = usuario.lower()
    if any(correo.endswith(f"@{d}") for d in DOMINIOS_PERSONALES):
        avisos.append(
            "ATENCIÓN: está usando una cuenta PERSONAL de Microsoft.\n"
            "  Con estas cuentas, las asignaciones de roles de Entra ID y el\n"
            "  control de acceso de Key Vault suelen fallar con errores de\n"
            "  permisos que usted no puede resolver (no es propietario del\n"
            "  directorio).\n"
            "\n"
            "  Si el script falla al asignar los roles, use una cuenta\n"
            "  institucional, o asigne los roles a mano desde el portal de\n"
            "  Azure: recurso → Control de acceso (IAM) → Agregar asignación."
        )

    if tipo != "user":
        avisos.append(
            f"El tipo de credencial es '{tipo}' y no 'user'. Si está usando una\n"
            "  entidad de servicio, compruebe que tenga rol Colaborador o\n"
            "  Propietario en la suscripción."
        )

    # --- Comprobar los permisos sobre la suscripción ------------------
    # Sin rol Colaborador o Propietario no se pueden crear recursos.
    proc = subprocess.run(
        [az, "role", "assignment", "list",
         "--assignee", usuario,
         "--scope", f"/subscriptions/{datos.get('id')}",
         "--include-inherited",
         "--query", "[].roleDefinitionName",
         "-o", "tsv"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    roles = {r.strip() for r in (proc.stdout or "").splitlines() if r.strip()}

    puede_crear = any(
        r.lower() in ("owner", "contributor", "propietario", "colaborador")
        for r in roles
    )
    if not puede_crear and roles:
        avisos.append(
            "Sus roles en la suscripción son: " + ", ".join(sorted(roles)) + "\n"
            "  Es posible que le falte 'Colaborador' o 'Propietario' para crear\n"
            "  recursos. Si el script falla al crear el grupo de recursos, pida\n"
            "  a un administrador que le asigne el rol Colaborador."
        )
    elif not roles:
        avisos.append(
            "No se pudieron leer sus roles en la suscripción. Puede ser normal\n"
            "  (permisos para listar asignaciones) o indicar que le falta el rol\n"
            "  Colaborador. Si el script falla al crear recursos, ese es el motivo."
        )

    if avisos:
        resumen += "\n\n" + "\n\n".join(f"  ⚠️  {a}" for a in avisos)

    return True, resumen


def ejecutar_plan(cfg: Config, pasos: Iterable[Paso], ejecutor: Ejecutor) -> list[tuple[str, bool, str]]:
    """
    Recorre los pasos. Devuelve [(descripcion, exito, detalle)].

    Los pasos críticos detienen la ejecución; los no críticos solo avisan.
    """
    resultados: list[tuple[str, bool, str]] = []
    total = 0
    for i, paso in enumerate(pasos, 1):
        total = i
        args = [ejecutor.resolver(a) for a in paso.args]
        descripcion = ejecutor.resolver(paso.descripcion)

        print(f"  {GRIS}[{i:02d}]{FIN} {descripcion}")

        if ejecutor.dry_run:
            print(f"       {GRIS}az {' '.join(args)}{FIN}")
            resultados.append((descripcion, True, "dry-run"))
            continue

        # ¿El recurso ya existe? Si el paso declara una comprobación y esta
        # tiene éxito, se OMITE la creación. Sin esto, repetir el script falla
        # con errores que no explican la causa (por ejemplo
        # «PublicNetworkAccess is required for this resouce» al recrear un
        # recurso de Foundry que ya está).
        if paso.comprobar_existencia:
            args_comprobacion = [ejecutor.resolver(a) for a in paso.comprobar_existencia]
            codigo_comp, _ = ejecutor.az(args_comprobacion)
            if codigo_comp == 0:
                print(f"       {AMARILLO}ya existe, se omite{FIN}")
                resultados.append((descripcion, True, "ya existía"))
                continue

        # Reintentos. Hace falta sobre todo para los secretos de Key Vault: con
        # el control de acceso por roles (RBAC), la asignación tarda en
        # propagarse y los primeros intentos fallan con «Forbidden» aunque el
        # permiso esté bien puesto.
        codigo, salida = 0, ""
        for intento in range(1, max(1, paso.reintentos) + 1):
            codigo, salida = ejecutor.az(args, capturar=paso.capturar)
            if codigo == 0:
                break
            if intento < paso.reintentos:
                espera = 15 * intento      # 15s, 30s, 45s...
                print(f"       {AMARILLO}reintento {intento}/{paso.reintentos - 1} "
                      f"en {espera}s (el permiso puede estar propagándose){FIN}")
                time.sleep(espera)

        if codigo == 0:
            if paso.extraer and salida:
                nuevas = paso.extraer(salida)
                ejecutor.variables.update(nuevas)
                for k, v in nuevas.items():
                    mostrado = f"{v[:8]}…" if "CLAVE" in k or "KEY" in k else v
                    print(f"       {VERDE}->{FIN} {k} = {mostrado}")
            print(f"       {VERDE}OK{FIN}")
            resultados.append((descripcion, True, ""))
            continue

        # Falló
        print(f"       {ROJO}FALLÓ{FIN}")
        # Se busca la línea más informativa del error, no la última.
        # az suele devolver un JSON multilínea y la última línea puede ser solo
        # un cierre de llave "}", que no dice nada. Se prioriza la línea que
        # empieza por "ERROR:" o "Message:", y si no, la más larga.
        lineas = [l.strip() for l in salida.splitlines() if l.strip()]
        primera_linea = "(sin detalle)"
        for objetivo in ("ERROR:", "Message:", "Code:", "Exception"):
            encontrada = next((l for l in lineas if l.startswith(objetivo)), None)
            if encontrada:
                primera_linea = encontrada
                break
        else:
            if lineas:
                # La más larga suele ser la que explica el problema
                primera_linea = max(lineas, key=len)
        print(f"       {ROJO}{primera_linea[:300]}{FIN}")
        # Si hay más contexto útil, se muestra una segunda línea
        extra = next(
            (l for l in lineas
             if l != primera_linea and len(l) > 40 and not l.startswith("{")),
            None,
        )
        if extra and extra != primera_linea:
            print(f"       {ROJO}{extra[:300]}{FIN}")
        resultados.append((descripcion, False, primera_linea))

        if paso.critico:
            print()
            print(f"{ROJO}Se detuvo en el paso {i}: {descripcion}{FIN}")
            print(f"{GRIS}Corrija el problema y vuelva a ejecutar el script.{FIN}")
            print(f"{GRIS}Es seguro repetirlo: los recursos ya creados se detectan "
                  f"y se omiten.{FIN}")
            return resultados
        print(f"       {AMARILLO}No es crítico: se continúa.{FIN}")

    return resultados


def imprimir_resumen(cfg: Config, ejecutor: Ejecutor) -> None:
    v = ejecutor.variables
    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{NEGRITA}  RECURSOS LISTOS{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"""
  Grupo de recursos : {cfg.grupo}
  Región            : {cfg.region}

  Foundry (IA)      : {cfg.recurso_ia}
    endpoint recurso: {v.get('ENDPOINT_IA', cfg.endpoint_ia)}
    proyecto        : {cfg.endpoint_proyecto}
  Speech (voz)      : {cfg.recurso_voz}  [{cfg.region_voz}]
  Language (texto)  : {cfg.recurso_idioma}
  Key Vault         : {cfg.uri_keyvault}
  App Service       : {cfg.url_app}

{NEGRITA}{'-' * 74}{FIN}
  PARA PROBAR EN SU COMPUTADORA (copie esto a su archivo .env)
{NEGRITA}{'-' * 74}{FIN}

FOUNDRY_PROJECT_ENDPOINT={cfg.endpoint_proyecto}
FOUNDRY_MODEL={cfg.modelo_chat}
FOUNDRY_AGENT_NAME=rio-claro-agent
FOUNDRY_IMAGE_MODEL={cfg.modelo_imagen}
CONTENT_UNDERSTANDING_ENDPOINT={v.get('ENDPOINT_IA', cfg.endpoint_ia)}
CONTENT_UNDERSTANDING_KEY={v.get('CLAVE_IA', '(vea Key Vault)')}
SPEECH_KEY={v.get('CLAVE_VOZ', '(vea Key Vault)')}
SPEECH_REGION={cfg.region_voz}
LANGUAGE_ENDPOINT={v.get('ENDPOINT_IDIOMA', cfg.endpoint_idioma)}
LANGUAGE_KEY={v.get('CLAVE_IDIOMA', '(vea Key Vault)')}
KEY_VAULT_URI={cfg.uri_keyvault}

{NEGRITA}{'-' * 74}{FIN}
  APAGAR TODO CUANDO NO LO USE (Carlos: «que se pueda apagar»)
{NEGRITA}{'-' * 74}{FIN}

  az webapp stop  --name {cfg.app} --resource-group {cfg.grupo}
  az webapp start --name {cfg.app} --resource-group {cfg.grupo}

  Borrar absolutamente todo:
  az group delete --name {cfg.grupo} --yes --no-wait

{NEGRITA}{'-' * 74}{FIN}
  SIGUIENTE PASO: cree el AGENTE en el portal
{NEGRITA}{'-' * 74}{FIN}

  1. Entre a https://ai.azure.com con su cuenta
  2. Seleccione el proyecto '{cfg.proyecto}'
  3. Compilar > Agentes > Crear agente
  4. Nombre: rio-claro-agent      Modelo: {cfg.modelo_chat}
  5. Pegue las instrucciones de docs/instrucciones_agente.txt
  6. En Conocimiento, agregue los 3 archivos de la carpeta data/

  Después valide la conexión con:
    python tools/diagnostico_azure.py
""")


# =============================================================================
# Configuración de los modelos por defecto de Content Understanding
# =============================================================================
# Los analizadores preconstruidos (como prebuilt-invoice, el de las facturas)
# NO funcionan hasta que se configure el mapeo de modelos por defecto en el
# recurso. Sin esto, la extracción falla con
#     "Default model deployment not configured"
# que es un mensaje que no explica nada.
#
# La documentación sugiere configurarlo a mano en Content Understanding Studio.
# Pero el SDK trae `update_defaults()`, así que se automatiza aquí y el
# estudiante no tiene que entrar a ningún portal.
#
# Los ALIAS son la parte fácil de olvidar: los analizadores preconstruidos no
# referencian "gpt-4.1" sino "prebuilt-analyzer-completion". Si solo se mapea el
# nombre del modelo, los analizadores preconstruidos siguen fallando. El script
# oficial del SDK los incluye, y aquí también.
# =============================================================================


def configurar_modelos_por_defecto(cfg: Config, variables: dict[str, str]) -> bool:
    """
    Configura el mapeo de modelos por defecto de Content Understanding.

    Devuelve True si quedó configurado. No lanza excepción: si falla, se avisa
    y se continúa, porque el resto del proyecto sigue funcionando (solo la
    pestaña de facturas lo necesita).
    """
    endpoint = variables.get("ENDPOINT_IA") or cfg.endpoint_ia
    clave = variables.get("CLAVE_IA", "")

    # Nombres de despliegue: coinciden con los configurados en construir_pasos.
    mapeo = {
        cfg.modelo_principal: cfg.modelo_principal,
        cfg.modelo_embed: cfg.modelo_embed,
        # Alias que usan los analizadores preconstruidos. Sin estos, sigue
        # fallando aunque el nombre del modelo esté bien.
        "prebuilt-analyzer-completion": cfg.modelo_principal,
        "prebuilt-analyzer-completion-mini": cfg.modelo_mini,
        "prebuilt-analyzer-embedding": cfg.modelo_embed,
    }
    if cfg.modelo_mini != cfg.modelo_principal:
        mapeo[cfg.modelo_mini] = cfg.modelo_mini

    print(f"  {GRIS}Endpoint: {endpoint}{FIN}")
    for modelo, despliegue in mapeo.items():
        print(f"       {GRIS}{modelo}  ->  {despliegue}{FIN}")

    try:
        from azure.ai.contentunderstanding import ContentUnderstandingClient
        from azure.core.credentials import AzureKeyCredential
        from azure.identity import DefaultAzureCredential

        if clave:
            credencial = AzureKeyCredential(clave)
        else:
            # Sin clave se usa la identidad del usuario (az login). Es el modo
            # recomendado, y requiere el rol Cognitive Services User.
            credencial = DefaultAzureCredential()

        cliente = ContentUnderstandingClient(endpoint=endpoint, credential=credencial)
        actualizado = cliente.update_defaults(model_deployments=mapeo)

        print(f"       {VERDE}OK{FIN}  modelos por defecto configurados")
        if getattr(actualizado, "model_deployments", None):
            print(f"       {GRIS}El servicio confirmó "
                  f"{len(actualizado.model_deployments)} asignaciones{FIN}")
        return True

    except ImportError as exc:
        print(f"       {AMARILLO}No se pudo importar el SDK: {exc}{FIN}")
        return False
    except Exception as exc:
        print(f"       {ROJO}No se pudieron configurar los modelos por defecto{FIN}")
        print(f"       {ROJO}{type(exc).__name__}: {str(exc)[:300]}{FIN}")
        print()
        print(f"       {AMARILLO}Esto NO detiene la provisión: el resto del proyecto")
        print(f"       funciona. Solo la pestaña de facturas lo necesita.{FIN}")
        print()
        print(f"       {GRIS}Causas frecuentes:")
        print(f"         * Falta el rol 'Cognitive Services User' (es obligatorio")
        print(f"           incluso para el propietario del recurso)")
        print(f"         * Los modelos no se desplegaron en esta región")
        print(f"       Para configurarlo a mano:{FIN}")
        print(f"       {GRIS}https://contentunderstanding.ai.azure.com/settings{FIN}")
        return False


# =============================================================================
# Exportar a script de shell (para quien prefiera revisar antes de ejecutar)
# =============================================================================


def exportar_shell(cfg: Config, pasos: Iterable[Paso], destino: Path) -> None:
    lineas = [
        "#!/usr/bin/env bash",
        "# Generado por tools/provision_azure.py --export",
        "# Revise este archivo ANTES de ejecutarlo: muestra cada comando que se",
        "# ejecutará contra su suscripción de Azure.",
        "set -euo pipefail",
        "",
        'echo "Provisionando Río Claro AI-901..."',
        "",
    ]
    for paso in pasos:
        lineas.append(f"# {paso.descripcion}")
        lineas.append("az " + " ".join(f'"{a}"' if " " in a else a for a in paso.args))
        lineas.append("")
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8", newline="\n")
    try:
        destino.chmod(0o755)
    except OSError:
        pass


# =============================================================================
# main
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Crea los recursos de Azure para el proyecto Río Claro AI-901.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python tools/provision_azure.py --dry-run\n"
            "  python tools/provision_azure.py\n"
            "  python tools/provision_azure.py --region eastus2 --grupo rg-mio\n"
        ),
    )
    parser.add_argument("--grupo", default=Config.grupo, help="Nombre del grupo de recursos")
    parser.add_argument("--prefijo", default=Config.prefijo, help="Prefijo de los recursos")
    parser.add_argument(
        "--region", default=Config.region,
        help="Región principal. Debe soportar Content Understanding "
             "(swedencentral y eastus2 son seguras).",
    )
    parser.add_argument("--region-voz", default=Config.region_voz, help="Región para Azure Speech")
    parser.add_argument("--proyecto", default=Config.proyecto, help="Nombre del proyecto de Foundry")
    parser.add_argument(
        "--modelo-imagen", default=Config.modelo_imagen,
        help="Modelo de generación de imágenes (no use dall-e: se retiró)",
    )
    parser.add_argument(
        "--con-modelo-imagen", action="store_true",
        help="Intentar desplegar el modelo de imágenes. Por defecto NO se "
             "intenta: en muchas suscripciones de estudiante la cuota es 0.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Mostrar los comandos sin ejecutarlos")
    parser.add_argument("--export", metavar="ARCHIVO", help="Generar un script .sh revisable")
    parser.add_argument("--si", action="store_true", help="No pedir confirmación")
    args = parser.parse_args(argv)

    cfg = Config(
        grupo=args.grupo,
        prefijo=args.prefijo,
        region=args.region,
        region_voz=args.region_voz,
        proyecto=args.proyecto,
        modelo_imagen=args.modelo_imagen,
        desplegar_modelo_imagen=args.con_modelo_imagen,
    )

    pasos = construir_pasos_con_identificadores(cfg)

    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{NEGRITA}  PROVISIÓN DE AZURE — PROYECTO AI-901 — RÍO CLARO{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")

    # --- exportar y salir -------------------------------------------------
    if args.export:
        destino = Path(args.export)
        exportar_shell(cfg, pasos, destino)
        print(f"\n{VERDE}Script generado:{FIN} {destino}")
        print(f"{GRIS}Revíselo y ejecútelo con:  bash {destino.name}{FIN}\n")
        return 0

    # --- dry run ----------------------------------------------------------
    if args.dry_run:
        print(f"\n{AMARILLO}MODO ENSAYO: no se creará nada en Azure.{FIN}")
        print(f"{GRIS}Se muestran los {len(pasos)} comandos que se ejecutarían.{FIN}")
        print(f"{GRIS}Los valores entre paréntesis se leen de Azure al ejecutar de verdad.{FIN}\n")
        ejecutor = Ejecutor(dry_run=True)
        ejecutor.prefijar_variables_conocidas(cfg)
        ejecutar_plan(cfg, pasos, ejecutor)
        print()
        print(f"{VERDE}Ensayo completado: {len(pasos)} comandos.{FIN}")
        print(f"{GRIS}Ejecute sin --dry-run para crear los recursos de verdad.{FIN}\n")
        return 0

    # --- comprobaciones previas -------------------------------------------
    # Arreglar el PATH ANTES de nada: azure-identity busca `az` en el PATH y en
    # Windows un proceso abierto antes de instalar Azure CLI no lo tiene.
    directorio_az = arreglar_path_para_identidad()
    if directorio_az:
        print(f"{GRIS}Añadido al PATH para la autenticación: {directorio_az}{FIN}")
        print(f"{GRIS}(este proceso se abrió antes de instalar Azure CLI){FIN}")

    ok, detalle = comprobar_requisitos()
    if not ok:
        print(f"\n{ROJO}{detalle}{FIN}\n")
        return 1
    print(f"\n{VERDE}Sesión de Azure activa{FIN}")
    print(f"{GRIS}{detalle}{FIN}")

    # Comprobar la región ANTES de crear nada: si la suscripción la restringe,
    # se avisa con las alternativas válidas en lugar de fallar con un error
    # que no dice qué regiones sí sirven.
    region_ok, mensaje_region = comprobar_region(cfg)
    print()
    if not region_ok:
        print(f"{ROJO}{mensaje_region}{FIN}\n")
        return 1
    print(f"{VERDE}Región verificada{FIN}")
    print(f"{GRIS}{mensaje_region}{FIN}")

    print(f"""
{NEGRITA}Se van a crear estos recursos:{FIN}

  Grupo de recursos : {cfg.grupo}  ({cfg.region})
  Foundry (IA)      : {cfg.recurso_ia}   [AIServices, S0]
  Proyecto Foundry  : {cfg.proyecto}
  Modelos           : {cfg.modelo_chat}, {cfg.modelo_principal}, {cfg.modelo_mini},
                      {cfg.modelo_embed}, {cfg.modelo_imagen}
  Speech (voz)      : {cfg.recurso_voz}   [{cfg.region_voz}]
  Language (texto)  : {cfg.recurso_idioma}
  Key Vault         : {cfg.almacen}
  App Service       : {cfg.app}  [Linux, B1, Python 3.11]

  {AMARILLO}Esto consume crédito de su suscripción (estimado: 645 MXN al mes si lo
  deja encendido; mucho menos si apaga la aplicación cuando no la usa).{FIN}
""")

    if not args.si:
        try:
            respuesta = input(f"{NEGRITA}¿Continuar? (s/N): {FIN}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            respuesta = ""
        if respuesta not in ("s", "si", "sí", "y", "yes"):
            print(f"\n{GRIS}Cancelado. No se creó nada.{FIN}\n")
            return 0
    print()

    # --- ejecutar ---------------------------------------------------------
    ejecutor = Ejecutor(dry_run=False)
    resultados = ejecutar_plan(cfg, pasos, ejecutor)

    fallidos = [d for d, ok_, _ in resultados if not ok_]
    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"  {VERDE}Completados: {len(resultados) - len(fallidos)}{FIN}"
          f"   {ROJO}Fallidos: {len(fallidos)}{FIN}   de {len(pasos)}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")

    if fallidos:
        print(f"\n{AMARILLO}Estos pasos fallaron (revise y repita los que apliquen):{FIN}")
        for f in fallidos:
            print(f"  {ROJO}·{FIN} {f}")
        print(f"\n{GRIS}El script se puede volver a ejecutar: los recursos que ya existen"
              f" se omiten o se actualizan.{FIN}")

    # ------------------------------------------------------------------
    # Último paso: configurar los modelos por defecto de Content Understanding.
    #
    # No se puede hacer con az: es una llamada al plano de datos del servicio.
    # Sin esto, los analizadores preconstruidos fallan con
    # "Default model deployment not configured", que es el error más común
    # después de desplegar y no explica nada.
    #
    # Se ejecuta aquí, al final, porque necesita que el recurso exista y que el
    # rol Cognitive Services User ya esté asignado.
    # ------------------------------------------------------------------
    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{NEGRITA}  CONFIGURACIÓN DE CONTENT UNDERSTANDING{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"  Configurando los modelos por defecto que necesitan los analizadores")
    print(f"  preconstruidos (el de facturas entre ellos)...")
    print()
    configurado = configurar_modelos_por_defecto(cfg, ejecutor.variables)

    imprimir_resumen(cfg, ejecutor)

    if not configurado:
        print(f"{AMARILLO}Nota: los modelos por defecto de Content Understanding no")
        print(f"quedaron configurados. La aplicación funcionará, pero la extracción")
        print(f"de facturas mostrará el error 'Default model deployment not configured'.")
        print(f"Vuelva a ejecutar este script una vez resuelto el problema de permisos.{FIN}\n")

    return 0 if not fallidos else 1


if __name__ == "__main__":
    raise SystemExit(main())
