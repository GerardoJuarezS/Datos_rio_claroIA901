import os
import streamlit as st
import pandas as pd
from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.ai.textanalytics import TextAnalyticsClient
import azure.cognitiveservices.speech as speechsdk

# Configuración de página
st.set_page_config(page_title="Río Claro - Portal IA (AI-901)", page_icon="💧", layout="wide")

# Banner Superior de Transparencia (IA Responsable)
st.title("💧 Distribuidora Río Claro - Plataforma IA Unificada")
st.info(
    "🛡️ **IA Responsable Activa (AI-901):** "
    "**Transparencia:** Asistente conectado a Microsoft Foundry con citas oficiales. | "
    "**Privacidad:** Control de accesos y cifrado en Azure. | "
    "**Rendición de cuentas:** Laura supervisa las facturas antes de aprobar pagos."
)

# Memoria de facturas y quejas simuladas para la demo
if "facturas" not in st.session_state:
    st.session_state.facturas = [
        {"Folio": "FAC-2026-001", "Proveedor": "Químicos del Bajío", "Fecha": "2026-10-12", "Total": "$14,500.00", "Estado": "✅ Aprobada por Laura"}
    ]

if "quejas" not in st.session_state:
    st.session_state.quejas = [
        {"Cliente": "Hotel Gran Plaza León", "Sucursal": "León", "Mensaje": "Llevo 4 llamadas preguntando por las cajas de papel higiénico.", "Sentimiento": "NEGATIVO", "Prioridad": "🔥 Urgente (<15 min)"}
    ]

tab1, tab2, tab3, tab4 = st.tabs([
    "🗣️ 1. Asistente y Catálogo (Toño y Mariana)",
    "🧾 2. Lector de Facturas Anti-Duplicados (Laura)",
    "📢 3. Central de Quejas (Mariana)",
    "📈 4. Reporte Directivo y Seguridad (Don Ernesto y Carlos)"
])

with tab1:
    st.subheader("Asistente Inteligente (Conectado a Foundry y Catálogo Maestro)")
    pregunta = st.text_input("Escribe tu consulta (Ej. ¿Cuánto cloro de litro nos queda y estatus del pedido 501?):")
    if st.button("Consultar al Agente") and pregunta:
        st.success("🤖 **Respuesta del Agente de Río Claro:**")
        st.write("Cantidad de Cloro Blanqueador 1 Litro disponible: Guadalajara: 450 u., Zapopan: 320 u., León: 180 u., Querétaro: 290 u., Aguascalientes: 410 u.")
        st.write("Pedido #PED-501 (Cliente: Hotel Gran Plaza León): Salió de la sucursal Querétaro con 50 cajas de Papel Higiénico. Estatus: En tránsito, llega hoy a las 16:00 hrs.")
        st.markdown("*[Fuente: catalogo_y_pedidos_unificados.txt; politicas_y_pedidos_activos.txt]*")

with tab2:
    st.subheader("Procesamiento de Facturas (Azure AI Document Intelligence)")
    st.write("Evita captura manual, previene pagos duplicados y marca fotos borrosas para revisión de Laura.")
    if st.button("1️⃣ Probar Detección de Factura Duplicada"):
        st.error("🚨 **ALERTA DE DUPLICIDAD:** La factura `FAC-2026-001` de *Químicos del Bajío* por `$14,500.00` ya fue registrada. **Pago bloqueado automáticamente.**")
    if st.button("2️⃣ Probar Foto Borrosa de WhatsApp (Confiabilidad y Seguridad)"):
        st.warning("⚠️ **CONFIABILIDAD BAJA (62%):** Foto borrosa. Por principio de seguridad, la IA NO inventa montos y la envía a revisión humana obligatoria de Laura.")
    st.markdown("#### 📋 Bandeja de Cuentas por Pagar")
    st.dataframe(pd.DataFrame(st.session_state.facturas), use_container_width=True)

with tab3:
    st.subheader("Análisis de Sentimiento y Quejas (Azure AI Language)")
    cliente = st.text_input("Cliente:", "Restaurante Los Arcos")
    msg = st.text_area("Mensaje de queja:", "Nadie contesta en la sucursal Guadalajara sobre nuestro pedido.")
    if st.button("Analizar y Clasificar"):
        st.session_state.quejas.append({"Cliente": cliente, "Sucursal": "Guadalajara", "Mensaje": msg, "Sentimiento": "NEGATIVO (96%)", "Prioridad": "🔥 Urgente (<15 min)"})
        st.success("Queja registrada y priorizada bajo el SLA de Mariana.")
    st.dataframe(pd.DataFrame(st.session_state.quejas), use_container_width=True)

with tab4:
    st.subheader("📈 Reporte de Ventas Unificadas (Don Ernesto) y Seguridad (Carlos)")
    df_v = pd.DataFrame({
        "Sucursal": ["Guadalajara", "Zapopan", "León", "Querétaro", "Aguascalientes"],
        "Ventas Totales Mes (MXN)": ["$145,200", "$187,000", "$193,000", "$226,000", "$166,500"],
        "Estatus Inventario": ["Sincronizado", "Sincronizado", "Sincronizado", "Sincronizado", "Sincronizado"]
    })
    st.dataframe(df_v, use_container_width=True)
    st.markdown("---")
    st.markdown("🔐 **Seguridad (Carlos):** Accesos individuales mediante Entra ID, secretos resguardados y opción de apagado rápido desde el portal de Azure.")