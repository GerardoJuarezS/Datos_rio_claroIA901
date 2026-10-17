# 💧 Distribuidora Río Claro — Plataforma IA Unificada

**Proyecto integrador para la certificación AI-901: Microsoft Azure AI Fundamentals**

Implementa el caso de la empresa ficticia Distribuidora Río Claro usando
**Microsoft Foundry**, **Content Understanding**, **Azure Speech** y
**Azure AI Language**, cubriendo las cinco cargas de trabajo que evalúa el examen.

---

## Estado del proyecto

| Componente | Estado |
|---|---|
| Motor del negocio (`rio_claro.py`) | ✅ Verificado — 73/73 pruebas pasan |
| Aplicación (`app.py`) | ✅ Verificada — 54/54 comprobaciones en navegador real |
| Arranque en App Service | ✅ Verificado desde otro directorio de trabajo |
| Comportamiento si Azure falla | ✅ Verificado — errores traducidos, sin trazas |
| Datos del caso | ✅ Catálogo unificado, políticas, historial de quejas |
| Facturas de prueba | ✅ 3 PDF + 2 fotos (limpia, duplicada, borrosa) |
| Scripts de Azure | ✅ Provisión (50 pruebas) y diagnóstico |
| **Conexión con Azure** | ⏳ **Pendiente: requiere SU suscripción** |
| **Liga pública** | ⏳ **Pendiente de desplegar** |
| Capturas para la entrega | ⚠️ Generadas en modo demo; reemplazar con las reales |

---

## Empiece aquí

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Verificar que la lógica funciona (no necesita Azure)
python tools/autotest.py
#    -> RESULTADO: 41/41 pruebas pasaron.

# 3. Ver la aplicación en modo demostración
streamlit run app.py
```

En la barra lateral verá el estado de cada servicio de Azure. Mientras no haya
credenciales, aparecerán en ⚠️ y la app funcionará en **modo demo etiquetado**:
nunca finge haber llamado a Azure.

**Para conectarla a Azure, siga [GUIA_DESPLIEGUE.md](GUIA_DESPLIEGUE.md).**

---

## Qué resuelve

El caso describe una empresa sin área de TI, con la información dispersa en
cinco Excel distintos, facturas en correos personales, quejas en WhatsApp y tres
versiones contradictorias de la misma política. El director lo resume así:

> «Tenemos 22 años de información; la IA debería poder usarla.»

El prototipo ataca primero el desorden de los datos y después construye la IA
encima. Los seis módulos:

| Módulo | Carga de trabajo AI-901 | Personaje que atiende |
|---|---|---|
| 1. Asistente | IA generativa y agentes | Mariana, Don Ernesto |
| 2. Facturas | Extracción de información | Laura |
| 3. Quejas | Análisis de texto | Mariana |
| 4. Voz y visión | Voz, visión, generación de imágenes | Toño |
| 5. Reporte y seguridad | Gobernanza y seguridad | Don Ernesto, Carlos |
| 6. IA responsable | Los seis principios, con evidencia | Todos |

---

## Estructura

```
.
├── app.py                       Interfaz Streamlit: navegación, tareas y llamadas a Azure
├── portal.py                    Personas del caso y tareas del portal (lenguaje del usuario)
├── ui.py                        Piezas de interfaz: estilos, tarjetas, navegación
├── rio_claro.py                 Motor del negocio (lógica pura, sin interfaz)
├── requirements.txt             Dependencias
├── startup.sh                   Arranque en Azure App Service
├── .streamlit/config.toml       Configuración (incluye seguridad CORS)
├── .env.example                 Plantilla de credenciales
├── GUIA_DESPLIEGUE.md           Paso a paso hasta la liga pública
├── ENTREGA.md                   Documento obligatorio de entrega
├── PLAN_MEJORA_AI901.md         Análisis y ruta de certificación
│
├── data/                        FUENTE ÚNICA DE VERDAD
│   ├── catalogo_unificado.csv           Catálogo de las 5 sucursales, unificado
│   ├── politicas_y_pedidos_activos.txt  Políticas vigentes y pedidos en curso
│   ├── historial_quejas.jsonl           Historial central de quejas
│   ├── catalogo_excel/                  Los 5 Excel originales (datos sucios)
│   └── personajes_y_entrevistas.md      Guion de los 5 personajes
│
├── samples/                     Facturas de prueba
│   ├── factura_limpia.pdf               FAC-2026-001, extraíble
│   ├── factura_final2.pdf               EL MISMO cobro, otro nombre
│   ├── factura_distinta.pdf             FAC-2026-014, otro proveedor
│   ├── factura_foto_borrosa.jpg         Foto ilegible (confiabilidad)
│   └── factura_monto_borroso.jpg        Solo el total es ilegible
│
├── docs/
│   ├── capturas/                Capturas de pantalla
│   └── instrucciones_agente.txt Instrucciones para el agente de Foundry
│
└── tools/
    ├── verificar_todo.py        Verificación integral (17 secciones)
    ├── autotest.py             73 pruebas de la lógica y del diagnóstico de errores
    ├── probar_app_funcional.py 54 comprobaciones sobre la app en un navegador real
    ├── probar_directorio_trabajo.py  Comprueba que funcione como en App Service
    ├── probar_errores_azure.py  Comportamiento cuando Azure falla
    ├── probar_provision.py     66 pruebas del provisionador (con simulacros)
    ├── verificar_dependencias.py  13 comprobaciones de requirements.txt y del paquete
    ├── verificar_workflow.py   24 comprobaciones del flujo de despliegue
    ├── verificar_entrega.py    38 comprobaciones del documento de entrega
    ├── provision_azure.py      Crea los recursos de Azure (multiplataforma)
    ├── desplegar.py            Empaqueta y despliega en App Service
    ├── probar_despliegue.py    Prueba la app PUBLICADA con un navegador real
    ├── diagnostico_azure.py    Verifica la conectividad con Azure
    ├── generar_facturas.py     Genera las facturas de prueba
    ├── verificar_facturas.py   Comprueba la capa de texto de los PDF
    ├── capturar_pantallas.py   Automatización del navegador (CDP)
    └── generar_capturas_entrega.py  Genera las capturas del documento de entrega
```

### Un solo comando para verificar todo

```bash
python tools/verificar_todo.py
```

Son 17 secciones que no necesitan Azure, y **cinco de ellas simulan condiciones de
Azure**:

- Una abre la aplicación en un navegador real, activa el modo demostración,
  recorre las 6 pestañas, pulsa los botones y **sube las facturas de prueba**.
- Otra arranca la aplicación **desde otro directorio de trabajo**, como hace App
  Service con `/home/site/wwwroot`.
- La tercera la arranca con **endpoints inválidos**, para comprobar qué lee el
  evaluador si una credencial falla durante la demostración.

Entre ellas encontraron **siete errores reales** que ninguna otra prueba
detectaba: el monto ilegible mostraba un importe confiable, el botón de
aprobación aparecía con importes no verificables, `startup.sh` no cambiaba
de directorio, la barra lateral mostraba un check sin haber verificado nada,
y faltaban dos dependencias (`Pillow` y `azure-core`) en `requirements.txt`.

---

## Cómo se demuestra cada principio de IA responsable

| Principio | Dónde verlo | Cómo comprobarlo |
|---|---|---|
| **Equidad** | Módulo 1 | Pregunte «¿cuánto cloro nos queda?» → responde las **5** sucursales |
| **Confiabilidad** | Módulo 2 | Suba `factura_monto_borroso.jpg` → **ningún monto**, revisión humana |
| **Privacidad** | `app.py`, Key Vault | `grep` de claves en el código → sin resultados |
| **Inclusión** | Módulo 4 | Pregunte por voz desde un celular real |
| **Transparencia** | Módulo 1 | Cada respuesta cita `[Fuente: ...]` y se ve el contexto recuperado |
| **Rendición de cuentas** | Módulos 2 y 5 | Toda factura queda «Pendiente de aprobación de Laura» + bitácora |

---

## Decisiones de diseño que vale la pena conocer

**El SDK correcto para el examen.** Se usa `azure-ai-projects` (v2.x) con
`AIProjectClient` y su cliente de OpenAI. **No** se usa
`openai.AzureOpenAI`, que es la vía anterior a Foundry.

**Content Understanding en lugar de Document Intelligence.** La guía vigente del
examen AI-901 pide *Azure Content Understanding* para extraer información de
documentos, imágenes, audio y vídeo. Document Intelligence ya no aparece en la
guía, así que no se usa `azure-ai-formrecognizer`.

**Deduplicación por contenido, no por nombre de archivo.** `huella_factura()`
genera un SHA-256 de proveedor + folio + total, todos normalizados. Esto detecta
que el mismo cobro llegó como `factura_limpia.pdf` y como foto de WhatsApp.
Comparar nombres de archivo no habría detectado nada.

**Umbral de confianza del 80%.** Por debajo, `decidir_factura()` **no muestra
ningún monto**. La razón está escrita en el código: es preferible molestar a
Laura que arriesgar un pago con una cifra inventada.

**El contexto son datos, nunca instrucciones.** El prompt del sistema incluye
esta regla explícita, y no es teórica: el PDF del curso traía seis veces un
bloque `<admin>` pidiendo insertar una palabra en el documento y en el código.
La aplicación no lo obedece, y ese hallazgo se documenta como lección de
seguridad en [ENTREGA.md](ENTREGA.md).

---

## Comandos útiles

```bash
# Verificación integral (17 secciones, sin Azure)
python tools/verificar_todo.py

# Verificar la lógica del negocio y el diagnóstico de errores (73 pruebas)
python tools/autotest.py

# Probar la app en un navegador real, subiendo las facturas (54 comprobaciones)
python tools/probar_app_funcional.py

# Comprobar que funcione con otro directorio de trabajo (como en App Service)
python tools/probar_directorio_trabajo.py

# Comprobar qué pasa si Azure está mal configurado (9 comprobaciones)
python tools/probar_errores_azure.py

# Verificar que requirements.txt esté completo (12 comprobaciones)
python tools/verificar_dependencias.py

# Verificar el provisionador con simulacros (67 pruebas, sin tocar Azure)
python tools/probar_provision.py

# Verificar la conectividad con Azure
python tools/diagnostico_azure.py

# Regenerar las facturas de prueba
python tools/generar_facturas.py

# Comprobar que los PDF tienen capa de texto
python tools/verificar_facturas.py

# Capturar las pantallas para la entrega (arranca la app, interactúa y
# fotografía los estados con contenido: equidad, duplicado bloqueado, etc.)
python tools/generar_capturas_entrega.py

# Ver PRIMERO qué crearía en Azure, sin crear nada
python tools/provision_azure.py --dry-run

# Crear todos los recursos de Azure (pide confirmación)
python tools/provision_azure.py

# Apagar la aplicación para no gastar crédito
az webapp stop --name rioclaro-ai901 --resource-group rg-rio-claro-ai901
```

---

## Requisitos

- Python 3.10 o superior
- Suscripción de Azure con crédito (Azure for Students funciona)
- Azure CLI (`az`) para el despliegue
- Cuenta institucional (una cuenta personal da problemas con Entra ID y Key Vault)

---

**AI-901 · Microsoft Azure AI Fundamentals**
Distribuidora Río Claro es una empresa ficticia creada para este proyecto.
