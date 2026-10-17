#!/bin/bash
# Comando de arranque para Azure App Service (Linux, Python).
#
# App Service inyecta el puerto en la variable PORT. En App Service Linux con
# las imagenes "Blessed" (las del desplegable Stack, como PYTHON:3.11) PORT es
# la variable que controla el puerto del contenedor, y para Python su valor por
# defecto es 8000.
#
# WEBSITES_PORT NO TIENE EFECTO en imagenes Blessed: solo aplica a contenedores
# personalizados. Se deja como ultimo recurso por si alguien despliega este
# proyecto como contenedor propio; no estorba.
#
# El puerto debe coincidir en TRES sitios: esta variable, la App Setting PORT y
# .streamlit/config.toml. Los tres estan en 8000.
# Streamlit debe escuchar en 0.0.0.0 y en ese puerto exacto, o el contenedor
# se marcara como no saludable y el sitio no respondera.
#
# Configurar en App Service > Configuracion > Comando de inicio:
#     bash startup.sh
#
# OJO CON DOS COSAS:
#
# 1. Este archivo DEBE tener finales de linea LF, no CRLF. Si Windows lo
#    convierte, App Service falla con un error confuso del tipo
#    "bad interpreter: No such file or directory". Hay una comprobacion
#    automatica en tools/verificar_todo.py.
#
# 2. NO se pasa --server.enableCORS. Lo correcto vive en
#    .streamlit/config.toml, donde enableCORS = true va acompanado de
#    corsAllowedOrigins (lista blanca). Pasar --server.enableCORS false aqui
#    ANULARIA esa configuracion y aceptaria conexiones WebSocket desde
#    cualquier origen, que es un agujero de seguridad real.
#
# 3. El texto va sin acentos ni guiones largos: el entorno de arranque de
#    App Service puede tener una codificacion distinta y el script fallaria
#    antes de llegar a Streamlit.

set -e

# Cambiar al directorio donde vive este script.
#
# App Service ejecuta el comando de arranque con /home/site/wwwroot como
# directorio de trabajo, asi que en la practica coinciden. Pero si alguien
# lanza el script desde otro sitio (bash /ruta/startup.sh), la ruta relativa
# "app.py" no se encontraria y el arranque fallaria con un error confuso.
#
# Ademas, Streamlit busca .streamlit/config.toml en el DIRECTORIO DE TRABAJO,
# no junto al script: sin este cd, la configuracion de seguridad y el tema no
# se aplicarian.
cd "$(dirname "$0")"

PUERTO="${PORT:-${WEBSITES_PORT:-8000}}"

echo "Rio Claro AI-901 - arrancando Streamlit en el puerto ${PUERTO}"
echo "Directorio de trabajo: $(pwd)"

exec python -m streamlit run app.py \
    --server.port "${PUERTO}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
