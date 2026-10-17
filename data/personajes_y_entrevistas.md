# PERSONAJES DEL CASO — RÍO CLARO
# Guion para las entrevistas iniciales y para la demo final.
# El docente (u otros estudiantes) interpreta a estos personajes.
# Cada uno tiene una preocupación distinta y la solución debe atenderlos TODOS.

---

## Don Ernesto — Director General
**Qué le preocupa:** perder clientes grandes y no saber cuánto vende cada sucursal.
**Éxito para él:** un reporte de ventas en el que las 5 sucursales coincidan, y un
piloto que cueste lo previsto.

**Preguntas que hace en la entrevista:**
1. ¿Cuánto vendimos este mes por sucursal? Quiero un solo número, no cinco.
2. ¿Cuánto me va a costar esto al mes?
3. Si esto falla, ¿la operación se detiene?

**Qué debe demostrar tu prototipo:**
- Pestaña 5: reporte unificado con total del grupo.
- Una cifra de costo mensual real de Azure (no "es barato").

---

## Laura — Cuentas por Pagar  ⭐ el personaje clave del caso
**Qué le preocupa:** que la IA se equivoque con dinero o que la reemplace.
**Éxito para ella:** pasar de ~12 horas semanales de captura a menos de 2, revisando
solo los casos que la IA marque como dudosos, y **cero pagos duplicados**.

**Preguntas que hace en la entrevista:**
1. ¿Y si la factura está borrosa? ¿Se inventa el monto?
2. ¿Cómo sé que no va a pagar dos veces la misma factura?
3. ¿La IA va a decidir sola a quién le pago?
4. ¿Qué pasa si se equivoca? ¿Quién responde?

**Qué debe demostrar tu prototipo:**
- Pestaña 2 con una factura PDF real → extrae proveedor, folio, fecha, total.
- La MISMA factura subida como foto → **bloquea el pago** como duplicado.
- Una factura borrosa → confianza < 80% → **no muestra el total**, va a revisión.
- Frase textual: "el sistema nunca paga solo; tú apruebas cada pago".
- **Nunca decir la palabra "reemplazar" sin decir "apoyar".**

---

## Mariana — Gerente de Sucursal León
**Qué le preocupa:** clientes molestos que llaman y nadie les da seguimiento.
**Éxito para ella:** responder a cualquier cliente en menos de 15 minutos, sin
importar de qué sucursal salió el pedido.

**Preguntas que hace en la entrevista:**
1. Un cliente llama por un pedido que salió de Querétaro. ¿Me lo puede resolver
   sin que yo busque en el Excel de Querétaro?
2. ¿Cómo sabe el sistema que ese cliente ya llamó 4 veces?
3. ¿Puedo ver todas las quejas de la sucursal en un solo lugar?

**Qué debe demostrar tu prototipo:**
- Pestaña 1: preguntar por PED-501 (salió de Querétaro) desde la vista de León.
- Pestaña 3: el historial muestra que el Hotel Gran Plaza León tiene 4 incidencias.
- Clasificación automática por prioridad según el SLA de 15 minutos.

---

## Toño — Jefe de Bodega  ⭐ el más fácil de olvidar
**Qué le preocupa:** no usa computadora; todo lo resuelve por teléfono.
**Éxito para él:** preguntar por voz desde el celular "¿cuánto cloro de litro nos
queda?" y obtener una respuesta correcta.

**Preguntas que hace en la entrevista:**
1. ¿Esto lo puedo usar desde mi celular?
2. Yo no sé escribir rápido. ¿Puedo nada más hablarle?
3. ¿Me va a contestar con la cantidad exacta o me va a decir "revise el sistema"?

**Qué debe demostrar tu prototipo:**
- Pestaña 4: grabar la pregunta **con la voz** desde el celular y obtener la
  transcripción y la respuesta correcta (180 en León, 450 en Guadalajara...).
- Que la respuesta se **escuche** en audio.
- Probar en un celular de verdad, no en la computadora. Si puedes, en modo incógnito.

---

## Carlos — Soporte y Sistemas
**Qué le preocupa:** ser el único responsable de algo que no conoce.
**Éxito para él:** accesos por persona (no contraseñas compartidas), secretos
guardados, y un sistema que pueda apagar si algo falla.

**Preguntas que hace en la entrevista:**
1. ¿Dónde están las llaves del servicio? ¿Hay contraseñas compartidas?
2. Si algo se rompe, ¿cómo lo apago?
3. ¿Puedo ver quién hizo qué y cuándo?
4. ¿Qué datos salen de la empresa hacia el modelo?

**Qué debe demostrar tu prototipo:**
- Key Vault con los secretos (captura de pantalla).
- Código con **cero** claves escritas (muestra que no hay `grep` con resultados).
- Identidad administrada habilitada en App Service.
- Bitácora de auditoría con hora UTC.
- Botón/instrucción de apagado desde el portal de Azure.

---

# PREGUNTAS DE CIERRE (las hace el evaluador a todos)

1. **Equidad:** "¿El agente trata igual a clientes de todas las sucursales, o
   favorece a la que tenía más y mejores datos?"
2. **Confiabilidad y seguridad:** "¿Qué pasa si una factura está borrosa? ¿La
   marca para revisión humana en lugar de inventar un total?"
3. **Privacidad y seguridad:** "¿Las nóminas, precios y datos de clientes quedan
   protegidos con Entra ID y Key Vault? ¿Se evita enviar datos sensibles
   innecesarios al modelo?"
4. **Inclusión:** "¿El asistente funciona por voz y desde el celular para el
   personal de bodega?"
5. **Transparencia:** "¿El usuario sabe que habla con una IA y de qué documento
   salió cada respuesta?"
6. **Rendición de cuentas:** "¿Quién en la empresa revisa y aprueba lo que sugiere
   la IA, por ejemplo, antes de pagar una factura?"

> Regla de oro en tus respuestas: **evidencia, no definición.**
> Mal: "Aplicamos el principio de transparencia."
> Bien: "Aquí está la captura: la respuesta dice '[Fuente: catalogo_unificado.csv]'.
> Y aquí el código, línea 412, que arma esa cita."
