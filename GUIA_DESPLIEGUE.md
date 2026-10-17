# Guía de despliegue — Río Claro AI-901

Esta guía lleva el proyecto desde su computadora hasta una **liga pública en
Azure**, en el orden exacto en que conviene hacerlo. Siga los pasos sin saltarse
ninguno: cada uno depende del anterior.

**Tiempo total estimado:** 2 a 3 horas la primera vez (la mayor parte esperando
que Azure aprovisione recursos).

---

## Antes de empezar: dos advertencias

### 1. Cuenta personal de Microsoft

Si entra a Azure con una cuenta **personal** (outlook.com, hotmail.com,
live.com), es probable que las asignaciones de roles de Entra ID y las políticas
de Key Vault le fallen con errores de permisos que no puede resolver usted
mismo. **Solución:** use su cuenta institucional, o cree una cuenta de trabajo
gratuita. Verifíquelo antes de gastar tiempo:

```bash
az account show --query "{cuenta:user.name, tipo:user.type, suscripcion:name}" -o table
```

Si `tipo` dice `user` y el correo es personal, prepárese para problemas. Si dice
`user` con dominio institucional, está bien.

### 2. Región

Content Understanding **no está en todas las regiones**. Si elige mal, los
analizadores de facturas fallarán con errores confusos.

**Regiones recomendadas:** `swedencentral` o `eastus2`.

---

## Paso 0 — Instalar las herramientas

```bash
# Azure CLI (una sola vez)
#   Windows:  winget install Microsoft.AzureCLI
#   macOS:    brew install azure-cli
#   Linux:    curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

az version          # confirme que responde
az login            # inicie sesión en el navegador
az account show     # confirme la suscripción correcta
```

Si tiene varias suscripciones, elija la que va a usar:

```bash
az account list --query "[].{nombre:name, id:id, estado:state}" -o table
az account set --subscription "<el-id-elegido>"
```

> **Importante:** una suscripción de **Azure for Students** funciona bien y no
> requiere tarjeta. Si tiene crédito gratuito, úselo.

---

## Paso 1 — Instalar las dependencias de Python

```bash
cd Datos_rio_claro
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Verifique que todo quedó bien **sin necesidad de Azure**:

```bash
python tools/autotest.py
```

Debe terminar con:

```
RESULTADO: 41/41 pruebas pasaron.
El motor está listo para conectarse a Azure.
```

Si esto falla, no siga: hay un problema con los datos o con Python.

---

## Paso 2 — Crear los recursos en Azure

Este es el paso largo. El provisionador crea **todo** de una vez y al final
imprime los valores para su archivo `.env`.

### Primero: revise qué va a pasar, sin crear nada

```bash
python tools/provision_azure.py --dry-run
```

Esto le muestra **los 33 comandos** que se ejecutarían contra su suscripción,
con los valores ya resueltos, y no toca Azure. Es la forma de tener confianza
antes de gastar crédito.

Si lo prefiere en formato script de shell para revisarlo con calma:

```bash
python tools/provision_azure.py --export provision_revisable.sh
```

### Después: cree los recursos

```bash
python tools/provision_azure.py
```

Le pedirá confirmación antes de empezar y le mostrará el costo estimado.
Para saltarse la confirmación (por ejemplo en un guion): `--si`.

Para cambiar nombres o región:

```bash
python tools/provision_azure.py --grupo rg-rio-claro --region eastus2
python tools/provision_azure.py --help          # ver todas las opciones
```

> **Es seguro repetirlo.** Si un paso falla a mitad, corríjalo y vuelva a
> ejecutar el mismo comando: los recursos que ya existen se detectan y no se
> duplican.

**Qué crea:**

| Recurso | Para qué |
|---|---|
| Grupo de recursos | Contenedor de todo |
| Recurso de Microsoft Foundry (AIServices, S0) | Modelos, agente, Content Understanding y Speech |
| Proyecto de Foundry | Donde vive el agente |
| 5 despliegues de modelos | `gpt-5-mini`, `gpt-4.1`, `gpt-4.1-mini`, `text-embedding-3-large`, `gpt-image-2.5-flare` |
| Recurso de Azure Speech | Voz a texto y texto a voz |
| Recurso de Azure AI Language | Análisis de sentimiento y entidades |
| Key Vault | Secretos, con los 7 secretos ya cargados |
| Plan de App Service + aplicación web | La liga pública |
| Identidad administrada + 2 roles | Para no usar claves en el código |

> **Si algún modelo no se despliega** en su región (el script lo avisa), no se
> detenga: despliéguelo a mano desde https://ai.azure.com en
> **Implementaciones → Implementar modelo** y ajuste el nombre en `.env`.

### Sobre el modelo de generación de imágenes

`dall-e-3` **se retiró el 4 de marzo de 2026** y ya no se puede desplegar. La
serie vigente es `gpt-image-*`, pero **no todos son accesibles sin trámite**:

| Modelo | Disponibilidad |
|---|---|
| `gpt-image-2.5-flare`, `gpt-image-2.5-sunburst` | General, **sin trámite** |
| `gpt-image-2` | General, sin trámite |
| `gpt-image-1`, `gpt-image-1.5`, `gpt-image-1-mini` | **Acceso limitado**: hay que solicitar acceso |

El script intenta desplegar `gpt-image-2.5-flare` (sin trámite). Si su región no
lo tiene, **el resto de la aplicación funciona igual**: la generación de imágenes
es la única función opcional del proyecto, y el módulo de visión (leer la foto
borrosa) es independiente y sí es imprescindible.

Si desea usar un modelo de acceso limitado, solicítelo en
https://aka.ms/oai/gptimage1access y ajuste `FOUNDRY_IMAGE_MODEL` con el nombre
de su **despliegue** (no el del modelo).

### Verificar el provisionador antes de ejecutarlo

El proyecto incluye 50 pruebas del provisionador que **no tocan Azure**: usan un
ejecutor simulado para verificar la lista de comandos, el orden de los pasos y el
manejo de errores.

```bash
python tools/probar_provision.py
# -> RESULTADO: 50/50 pruebas pasaron.
```

Comprueban, entre otras cosas, que:

- El endpoint del proyecto incluya `/api/projects/` y no el del recurso.
- Los 7 secretos se guarden con **valores reales** y no con marcadores sin
  resolver (este error ya se detectó una vez: Azure habría guardado la cadena
  literal `{ENDPOINT_PROYECTO}` como si fuera un secreto).
- Un fallo al desplegar un modelo **no** detenga la provisión, pero un fallo al
  crear el grupo de recursos **sí**.
- No se use `dall-e`, que se retiró el 4 de marzo de 2026.

Es más rápido que descubrir un error a mitad del aprovisionamiento.

### Verificar que el rol quedó asignado

Esto es lo que más falla. Compruébelo:

```bash
# Reemplace con los valores que imprimió el script
PRINCIPAL_ID=$(az webapp identity show --name rioclaro-ai901 --resource-group rg-rio-claro-ai901 --query principalId -o tsv)

az role assignment list --assignee $PRINCIPAL_ID --all \
  --query "[].{rol:roleDefinitionName, alcance:scope}" -o table
```

Debe aparecer **Cognitive Services User** y **Key Vault Secrets User**.

> El rol `Cognitive Services User` es obligatorio **incluso para el propietario
> del recurso**. Sin él, Content Understanding responde «Access denied» y no hay
> forma de saberlo hasta que se prueba.

---

## Paso 3 — Crear el archivo `.env` y probar en local

El script de provisión imprime un bloque al final. Cópielo:

```bash
cp .env.example .env
notepad .env        # o nano .env, o su editor favorito
```

Pegue los valores. El bloque se ve así:

```env
FOUNDRY_PROJECT_ENDPOINT=https://rioclaro-foundry.services.ai.azure.com/api/projects/rio-claro
FOUNDRY_MODEL=gpt-5-mini
FOUNDRY_AGENT_NAME=rio-claro-agent
CONTENT_UNDERSTANDING_ENDPOINT=https://rioclaro-foundry.services.ai.azure.com/
CONTENT_UNDERSTANDING_KEY=<secreto>
SPEECH_KEY=<secreto>
SPEECH_REGION=eastus2
LANGUAGE_ENDPOINT=https://rioclaro-language.cognitiveservices.azure.com/
LANGUAGE_KEY=<secreto>
KEY_VAULT_URI=https://rioclaro-kv.vault.azure.net/
```

> **Verifique el endpoint del proyecto.** Debe terminar en
> `/api/projects/rio-claro`. El endpoint del *recurso* (sin `/api/projects/...`)
> **no funciona** con el SDK y da un error que no explica nada.

Ahora ejecute el diagnóstico:

```bash
python tools/diagnostico_azure.py
```

Lo que debe ver:

- ✅ Dependencias de Python
- ✅ Configuración
- ✅ Autenticación (si `az login` está activo)
- ✅ Microsoft Foundry (el modelo responde)
- ⚠️ El agente puede salir OMITIDO: se crea en el portal (paso 4)
- ✅ Content Understanding (extrae datos de `samples/factura_limpia.pdf`)
- ✅ Azure AI Language
- ✅ Azure Speech (genera audio)
- ✅ Key Vault (lee los secretos)

**Sobre los modelos por defecto de Content Understanding.** Los analizadores
preconstruidos (el de facturas entre ellos) no funcionan hasta que se configure
el mapeo de modelos por defecto en el recurso. Sin eso fallan con
«Default model deployment not configured», que no explica nada.

**El script de provisión ya lo configura automáticamente** al terminar, con una
llamada a `update_defaults()` del SDK. Incluye los tres alias que necesitan los
analizadores preconstruidos (`prebuilt-analyzer-completion`,
`-completion-mini` y `-embedding`), que son la parte fácil de olvidar.

Al final de la provisión verá:

```
  CONFIGURACIÓN DE CONTENT UNDERSTANDING
  Configurando los modelos por defecto que necesitan los analizadores
  preconstruidos (el de facturas entre ellos)...

  Endpoint: https://rioclaro-foundry.services.ai.azure.com/
       gpt-4.1  ->  gpt-4.1
       text-embedding-3-large  ->  text-embedding-3-large
       prebuilt-analyzer-completion  ->  gpt-4.1
       prebuilt-analyzer-completion-mini  ->  gpt-4.1-mini
       prebuilt-analyzer-embedding  ->  text-embedding-3-large
       OK  modelos por defecto configurados
```

**Si esa parte falla**, no detiene la provisión: el resto del proyecto funciona
y solo la pestaña de facturas lo necesita. La causa más frecuente es que falte el
rol **Cognitive Services User**. Vuelva a ejecutar el script cuando lo resuelva,
o configúrelo a mano en
https://contentunderstanding.ai.azure.com/settings → **+ Agregar recurso** →
seleccione su recurso de Foundry → marque **Enable autodeployment for required
models**.

Para comprobarlo en cualquier momento:

```bash
python tools/diagnostico_azure.py
```

El diagnóstico informa cuántas asignaciones hay y si los alias de los
analizadores preconstruidos existen.

---

## Paso 4 — Crear el agente en el portal de Foundry

1. Entre a **https://ai.azure.com** con la misma cuenta.
2. Seleccione el proyecto `rio-claro`.
3. En **Compilar → Agentes**, elija **Crear agente**.
4. Nombre: `rio-claro-agent`
5. Modelo: `gpt-5-mini`
6. **Instrucciones:** abra `docs/instrucciones_agente.txt`, copie el bloque
   completo entre las tres comillas y péguelo.
7. En **Conocimiento**, agregue los tres archivos de la carpeta `data/`:
   - `catalogo_unificado.csv`
   - `politicas_y_pedidos_activos.txt`
   - `historial_quejas.jsonl`
8. Guarde y **pruebe en el área de juegos** con estas cinco preguntas:

| Pregunta | Respuesta esperada |
|---|---|
| ¿Cuánto cloro de litro nos queda? | Las **5** sucursales |
| ¿Cuánto cloro queda en León? | Solo León: 180 unidades |
| ¿Cuál es la política de devoluciones? | 30 días, versión 3 |
| ¿Puedo pagar una factura borrosa? | No: revisión humana de Laura |
| ¿Cuánto vendimos el año pasado? | «No tengo ese dato…» |

Si la primera respuesta menciona una sola sucursal, el agente está favoreciendo
una: **corrija las instrucciones antes de seguir**, porque es exactamente la
pregunta de Equidad del enunciado.

Si la última inventa una cifra, refuerce la Regla 1.

Ahora ejecute de nuevo el diagnóstico: el agente debe aparecer en verde.

---

## Paso 5 — Probar la aplicación en su computadora

```bash
streamlit run app.py
```

Ábralo en http://localhost:8501. En la barra lateral los cuatro servicios deben
aparecer en ✅.

**Recorra el guion completo:**

1. Pestaña 1: consulte «¿Cuánto cloro de litro nos queda?» → las 5 sucursales.
2. Pestaña 2: suba `samples/factura_limpia.pdf` → pendiente de Laura.
3. Pestaña 2: suba `samples/factura_final2.pdf` → **bloqueado por duplicado**.
4. Pestaña 2: suba `samples/factura_monto_borroso.jpg` → **sin monto**.
5. Pestaña 4: grabe con el micrófono → transcripción y audio de respuesta.
6. Pestaña 5: la bitácora registró todo.
7. Pestaña 6: los seis principios con su evidencia.

Solo cuando **todo** funcione en local, pase a desplegar.

---

## Paso 6 — Desplegar en Azure App Service

### Opción A — Desde su computadora con un archivo ZIP (la más simple)

```bash
# Empaquete sin basura local
zip -r app.zip . \
  -x ".venv/*" ".git/*" ".libs/*" ".pipcache/*" "__pycache__/*" \
     "*.pyc" ".env" "docs/capturas/*"

# Despliegue
az webapp deploy \
  --name rioclaro-ai901 \
  --resource-group rg-rio-claro-ai901 \
  --src-path app.zip \
  --type zip
```

> **Nunca incluya el archivo `.env` en el ZIP.** Los secretos van en App
> Settings o en Key Vault. Si se filtra un `.env` a un repositorio público,
> alguien puede gastar su crédito de Azure en horas.

### Opción B — Desde GitHub (despliegue continuo)

1. Suba el proyecto a un repositorio de GitHub (sin el `.env`: ya está en
   `.gitignore`).
2. En el portal de Azure, **App Service → Centro de implementación → GitHub**.
3. Seleccione repositorio y rama `main`.
4. Descargue el perfil de publicación y guárdelo como el secreto
   `AZURE_WEBAPP_PUBLISH_PROFILE` en GitHub.
5. El flujo `.github/workflows/deploy.yml` ya está listo y ejecuta el autotest
   antes de desplegar.

---

## Paso 7 — Configurar la aplicación desplegada

El script de provisión ya dejó casi todo listo. Verifique:

```bash
RG=rg-rio-claro-ai901
APP=rioclaro-ai901

# Comando de arranque
az webapp config show --name $APP --resource-group $RG \
  --query "appCommandLine" -o tsv
# Debe decir:  bash startup.sh

# Variables de entorno
az webapp config appsettings list --name $APP --resource-group $RG \
  --query "[].{nombre:name}" -o table

# Estado de la identidad administrada
az webapp identity show --name $APP --resource-group $RG --query principalId -o tsv
```

Asegúrese de que **no** haya ninguna clave en App Settings. Si está
`KEY_VAULT_URI`, la app lee los secretos de ahí y las claves no hacen falta.

### El puerto: la causa número uno de «Application Error»

Este proyecto usa una **imagen "Blessed"** de App Service (la del desplegable
*Stack*, `PYTHON:3.11`). En ese caso:

| Variable | ¿Sirve? | Para qué |
|---|---|---|
| **`PORT`** | ✅ **Sí** | Controla el puerto del contenedor. Para Python el valor por defecto ya es **8000** |
| `WEBSITES_PORT` | ❌ **No tiene efecto** | Solo aplica a contenedores personalizados (Web App for Containers) |

Si el puerto de Streamlit no coincide con el que espera la plataforma, la
aplicación **no arranca** y el navegador muestra «Application Error» sin más
explicación. Es el fallo más común al desplegar Streamlit en App Service.

El puerto debe coincidir en **tres sitios**, y en este proyecto los tres están
en `8000`:

1. La App Setting `PORT=8000` (la fija el script de provisión).
2. `startup.sh`, que pasa `--server.port ${PORT}` a Streamlit.
3. `.streamlit/config.toml`, que declara `port = 8000`.

Compruébelo:

```bash
az webapp config appsettings list --name $APP --resource-group $RG \
  --query "[?name=='PORT'].value" -o tsv
# Debe imprimir: 8000
```

> **Si su aplicación no arranca y sospecha del puerto**, la prueba rápida es
> añadir `WEBSITES_PORT` con el mismo valor. No hace daño y cubre el caso de
> que el plan se haya creado como contenedor personalizado:
> ```bash
> az webapp config appsettings set --name $APP --resource-group $RG \
>   --settings WEBSITES_PORT=8000
> ```

---

## Paso 8 — Verificar la liga pública

```bash
# Estado de la app
az webapp show --name rioclaro-ai901 --resource-group rg-rio-claro-ai901 \
  --query "{estado:state, url:defaultHostName, https:httpsOnly}" -o table

# Ver los registros en vivo mientras carga (la primera carga tarda 1-2 min)
az webapp log tail --name rioclaro-ai901 --resource-group rg-rio-claro-ai901
```

Abra **https://rioclaro-ai901.azurewebsites.net** y compruebe:

- [ ] La página carga (la primera vez tarda 1–2 minutos).
- [ ] La barra lateral muestra los cuatro servicios en ✅.
- [ ] **Ábrala desde un celular**, no solo desde la computadora. El enunciado
      exige acceso como usuario normal desde fuera del curso.
- [ ] El módulo de voz funciona desde el celular.

### Si no carga

| Síntoma | Causa probable | Solución |
|---|---|---|
| Página en blanco, error 500 | Comando de arranque mal | `az webapp config set --startup-file "bash startup.sh"` |
| «Application Error» | Faltan dependencias | `SCM_DO_BUILD_DURING_DEPLOYMENT=true` y redespliegue |
| «Application Error», sin más detalle | **El puerto no coincide** | Vea la sección del puerto arriba. Verifique que `PORT=8000` y añada `WEBSITES_PORT=8000` como red de seguridad |
| «Failed to find attribute 'app' in 'app'» | App Service usó Gunicorn en vez de Streamlit | Falta el comando de arranque: `bash startup.sh` |
| Servicios en ⚠️ en la barra lateral | Falta la variable de entorno | `az webapp config appsettings set ...` |
| «Access denied» en Content Understanding | Falta el rol | Asigne **Cognitive Services User** a la identidad administrada |
| Timeout al cargar | El plan B1 estaba dormido | Espere 2 minutos; active `--always-on true` |

Para ver los errores reales, entre a la consola SSH:

```bash
az webapp ssh --name rioclaro-ai901 --resource-group rg-rio-claro-ai901
```

---

## Paso 9 — Capturas y entrega

### Capturas automáticas

Con la app corriendo (local o en Azure):

```bash
python tools/capturar_pantallas.py --url https://rioclaro-ai901.azurewebsites.net
```

Se guardan en `docs/capturas/`. **Revíselas y vuelva a capturar** las que
necesiten mostrar resultados reales de Azure (no del modo demo):

- Factura extraída con confianza real
- Pago duplicado bloqueado
- Monto ilegible → «NO LEGIBLE»
- Su propia voz transcrita
- Key Vault con los secretos
- Costo real del piloto

### Completar el documento de entrega

Abra `ENTREGA.md` y reemplace:

- `<!-- SU NOMBRE COMPLETO -->`
- `<!-- https://SU-APP.azurewebsites.net -->` (dos veces)
- Descomente los bloques `<!-- CAPTURA N: ... -->` y guarde las capturas con los
  nombres indicados
- Actualice la tabla de costo del piloto con cifras reales

### Verificación final antes de subir

```bash
# 1. La lógica pasa
python tools/autotest.py

# 2. Azure responde
python tools/diagnostico_azure.py

# 3. Ninguna clave en el código
grep -rniE "(api[_-]?key|password|secret)\s*=\s*[\"'][A-Za-z0-9]{16,}" . \
  --include="*.py" --include="*.md" --include="*.sh"
# Debe salir vacío

# 4. El .env no se va a entregar
cat .gitignore | grep -i env
```

- [ ] El documento de entrega está en **formato Markdown** (`.md`), no PDF ni docx
- [ ] Incluye imágenes y capturas
- [ ] Explica la solución **y** el problema resuelto
- [ ] Responde las 6 preguntas de IA responsable **con evidencia**
- [ ] La liga pública funciona desde otro dispositivo
- [ ] Entregado antes del **viernes 6 de noviembre de 2026, 23:45 h (GMT-6)**

---

## Apagar y limpiar (para no gastar crédito)

```bash
RG=rg-rio-claro-ai901

# Apagar la aplicación (deja de cobrar el App Service)
az webapp stop --name rioclaro-ai901 --resource-group $RG

# Volver a encenderla
az webapp start --name rioclaro-ai901 --resource-group $RG

# Borrar TODO cuando termine el curso (irreversible)
az group delete --name $RG --yes --no-wait
```

> **Antes de borrar el grupo de recursos**, descargue las capturas y el
> documento de entrega. Si borra primero, pierde la liga que va a entregar.

---

## Resumen de comandos útiles

```bash
# Estado general
az webapp show -n rioclaro-ai901 -g rg-rio-claro-ai901 --query "{estado:state,url:defaultHostName}" -o table

# Ver registros en vivo
az webapp log tail -n rioclaro-ai901 -g rg-rio-claro-ai901

# Reiniciar
az webapp restart -n rioclaro-ai901 -g rg-rio-claro-ai901

# Ver los modelos desplegados
az cognitiveservices account deployment list -n rioclaro-foundry -g rg-rio-claro-ai901 -o table

# Ver los secretos guardados
az keyvault secret list --vault-name rioclaro-kv --query "[].name" -o table

# Costos del mes
az consumption usage list --query "[].{recurso:instanceName, costo:pretaxCost}" -o table
```
