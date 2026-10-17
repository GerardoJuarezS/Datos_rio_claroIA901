"""
Rio Claro — motor del negocio (sin dependencias de interfaz).

Todo lo que aqui vive es logica pura y verificable:

  * Lectura de la fuente unica de verdad (catalogo unificado, politicas, quejas).
  * Recuperacion de contexto con trazabilidad de fuentes.
  * Deteccion de pagos duplicados por contenido (no por nombre de archivo).
  * Reglas de decision: umbral de confianza, revision humana, aprobacion.

Al no depender de Streamlit ni de Azure, este modulo se puede probar en
segundos con `python tools/autotest.py`, que es justo lo que hace.

Mapeo a las aptitudes del examen AI-901:
  - Equidad            -> buscar_producto() devuelve las 5 sucursales
  - Transparencia      -> cada fragmento de contexto lleva su fuente
  - Confiabilidad      -> decidir_factura() y UMBRAL_CONFIANZA
  - Rendicion de cuentas -> ESTADOS_FACTURA exige aprobacion humana
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DIR_DATOS = RAIZ / "data"

SUCURSALES = ["Guadalajara", "Zapopan", "Leon", "Queretaro", "Aguascalientes"]

NOMBRE_SUCURSAL = {
    "Guadalajara": "Guadalajara",
    "Zapopan": "Zapopan",
    "Leon": "León",
    "Queretaro": "Querétaro",
    "Aguascalientes": "Aguascalientes",
}

# Umbral por debajo del cual la extraccion NO es confiable y exige revision
# humana. Elegido de forma conservadora: es preferible molestar a Laura que
# arriesgar un pago con un monto inventado.
UMBRAL_CONFIANZA = 0.80

# Estados posibles de una factura. Ninguno implica pago automatico.
ESTADOS_FACTURA = {
    "duplicado": "Bloqueada por duplicado",
    "revision": "Revisión humana obligatoria (confianza baja)",
    "pendiente": "Pendiente de aprobación de Laura",
    "aprobada": "Aprobada por Laura",
    "rechazada": "Rechazada por Laura",
}


def normalizar(texto: str) -> str:
    """Minusculas, sin acentos, sin signos, espacios colapsados."""
    if texto is None:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------
# Fuente unica de verdad
# ---------------------------------------------------------------------------


@dataclass
class Producto:
    producto_id: str
    nombre_oficial: str
    claves_historicas: list[str]
    unidad: str
    precio_lista_oficial: float
    existencias: dict[str, int]
    fuente: str

    @property
    def total_red(self) -> int:
        return sum(self.existencias.values())

    def como_contexto(self, sucursales: list[str] | None = None) -> str:
        objetivo = sucursales or SUCURSALES
        detalle = ", ".join(
            f"{NOMBRE_SUCURSAL[s]}: {self.existencias.get(s, 0)} u." for s in objetivo
        )
        return (
            f"{self.nombre_oficial} ({self.unidad}) — precio de lista único "
            f"${self.precio_lista_oficial:,.2f} MXN — existencias: {detalle}"
        )


@dataclass
class Pedido:
    folio: str
    cliente: str
    sucursal_origen: str
    contenido: str
    estatus: str
    fecha_promesa: str = ""

    def como_contexto(self) -> str:
        extra = f" Fecha prometida: {self.fecha_promesa}." if self.fecha_promesa else ""
        return (
            f"Pedido {self.folio} — cliente {self.cliente} — salió de la sucursal "
            f"{NOMBRE_SUCURSAL.get(self.sucursal_origen, self.sucursal_origen)} con "
            f"{self.contenido}. Estatus: {self.estatus}.{extra}"
        )


def _campo_entre_comillas(linea: str) -> bool:
    """
    Determina si la linea TERMINA dentro de un campo entre comillas.

    No basta con contar comillas: la linea
        FAB-3L,...,"FB-3L | Fabuloso 3 litros | Fabuloso 3L",garrafa 3 L,...,"Guadalajara.csv | ..."
    tiene un numero PAR de comillas pero NO es el inicio de un campo multilinea.
    La regla estructural correcta es: la linea termina dentro de comillas si y
    solo si el ultimo caracter no esta cerrado, es decir si el numero de
    comillas es IMPAR.
    """
    return linea.count('"') % 2 == 1


def _leer_csv_con_comentarios(ruta: Path) -> list[dict]:
    """
    Lee un CSV ignorando las lineas que empiezan con '#' pero respetando los
    campos entre comillas que contienen comas y saltos de linea.

    Un filtro ingenuo linea-por-linea rompe los campos multilinea: es
    exactamente el tipo de "dato sucio" que el caso Rio Claro describe.
    """
    utiles: list[str] = []
    dentro_de_comillas = False
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not dentro_de_comillas and linea.lstrip().startswith("#"):
            continue
        utiles.append(linea)
        dentro_de_comillas = _campo_entre_comillas(linea)

    # Se construye el lector EXPLICITAMENTE en lugar de usar csv.DictReader
    # sobre texto: DictReader llama internamente a csv.Sniffer, que puede
    # adivinar mal el delimitador cuando los datos contienen '|' y ';'
    # (que es justo el caso de este catalogo, porque las claves historicas
    # vienen separadas por '|'). Ese fallo silencioso devolvia filas con
    # clave None y el catalogo quedaba vacio.
    lector = csv.reader(utiles, delimiter=",", quotechar='"', strict=False)
    filas_crudas = [f for f in lector if f and any(c.strip() for c in f)]
    if not filas_crudas:
        return []
    encabezado = [c.strip() for c in filas_crudas[0]]
    resultado: list[dict] = []
    for fila in filas_crudas[1:]:
        if len(fila) < len(encabezado):
            fila = fila + [""] * (len(encabezado) - len(fila))
        resultado.append(dict(zip(encabezado, fila)))
    return resultado


@dataclass
class BaseConocimiento:
    productos: list[Producto] = field(default_factory=list)
    pedidos: list[Pedido] = field(default_factory=list)
    politicas: dict[str, str] = field(default_factory=dict)
    politicas_obsoletas: list[str] = field(default_factory=list)
    quejas: list[dict] = field(default_factory=list)

    # -- busqueda -----------------------------------------------------------
    def buscar_producto(self, consulta: str) -> Producto | None:
        """Encuentra un producto por nombre oficial, clave o clave historica."""
        q = normalizar(consulta)
        if not q:
            return None
        mejor: tuple[int, Producto] | None = None
        for p in self.productos:
            candidatos = [p.producto_id, p.nombre_oficial, *p.claves_historicas]
            for c in candidatos:
                cn = normalizar(c)
                if not cn:
                    continue
                puntaje = 0
                if cn == q:
                    puntaje = 100
                elif cn in q:
                    puntaje = 60 + len(cn)
                elif q in cn:
                    puntaje = 40 + len(q)
                else:
                    # coincidencia por palabras significativas
                    palabras = [w for w in cn.split() if len(w) > 3]
                    comunes = [w for w in palabras if w in q.split()]
                    if comunes:
                        puntaje = 20 + 5 * len(comunes)
                if puntaje and (mejor is None or puntaje > mejor[0]):
                    mejor = (puntaje, p)
        return mejor[1] if mejor else None

    def buscar_pedidos(self, consulta: str) -> list[Pedido]:
        q = normalizar(consulta)
        encontrados = []
        for ped in self.pedidos:
            if normalizar(ped.folio) in q:
                encontrados.append(ped)
        return encontrados

    def sucursales_mencionadas(self, consulta: str) -> list[str]:
        q = normalizar(consulta)
        return [s for s in SUCURSALES if normalizar(NOMBRE_SUCURSAL[s]) in q]

    def quejas_de_cliente(self, consulta: str) -> list[dict]:
        q = normalizar(consulta)
        for queja in self.quejas:
            cliente = normalizar(queja.get("cliente", ""))
            # se compara por las palabras significativas del nombre del cliente
            palabras = [w for w in cliente.split() if len(w) > 4]
            if palabras and all(w in q for w in palabras[:2]):
                return [x for x in self.quejas if normalizar(x.get("cliente", "")) == cliente]
        return []


def cargar_base(datos: Path = DIR_DATOS) -> BaseConocimiento:
    base = BaseConocimiento()

    # --- catalogo unificado -------------------------------------------------
    # OJO: el CSV tiene campos entre comillas que contienen comas y ademas
    # lineas de comentario que empiezan con '#'. No se puede filtrar linea por
    # linea antes de parsear, porque eso rompe los campos multilinea.
    ruta_cat = datos / "catalogo_unificado.csv"
    if ruta_cat.exists():
        filas = _leer_csv_con_comentarios(ruta_cat)
        for fila in filas:
            if not fila.get("producto_id"):
                continue
            claves = [
                c.strip()
                for c in (fila.get("claves_historicas") or "").split("|")
                if c.strip()
            ]
            existencias = {}
            for s in SUCURSALES:
                valor = (fila.get(f"existencia_{s}") or "0").strip()
                try:
                    existencias[s] = int(float(valor))
                except ValueError:
                    existencias[s] = 0
            try:
                precio = float(fila.get("precio_lista_oficial") or 0)
            except ValueError:
                precio = 0.0
            base.productos.append(
                Producto(
                    producto_id=fila["producto_id"].strip(),
                    nombre_oficial=(fila.get("nombre_oficial") or "").strip(),
                    claves_historicas=claves,
                    unidad=(fila.get("unidad") or "").strip(),
                    precio_lista_oficial=precio,
                    existencias=existencias,
                    fuente="catalogo_unificado.csv",
                )
            )

    # --- politicas y pedidos ------------------------------------------------
    ruta_pol = datos / "politicas_y_pedidos_activos.txt"
    if ruta_pol.exists():
        texto = ruta_pol.read_text(encoding="utf-8")
        # separar el bloque de pedidos
        if "# PEDIDOS ACTIVOS" in texto:
            bloque_pol, bloque_ped = texto.split("# PEDIDOS ACTIVOS", 1)
        else:
            bloque_pol, bloque_ped = texto, ""

        # politicas: seccion "## NOMBRE" hasta el siguiente "##"
        actual = None
        buffer: list[str] = []
        for linea in bloque_pol.splitlines():
            if linea.startswith("## "):
                if actual and buffer:
                    base.politicas[actual] = "\n".join(buffer).strip()
                actual = linea[3:].strip()
                buffer = []
            elif actual is not None:
                buffer.append(linea)
        if actual and buffer:
            base.politicas[actual] = "\n".join(buffer).strip()

        # versiones obsoletas: quedan registradas para poder demostrar que el
        # agente NO las cita (evidencia de Confiabilidad y seguridad)
        for bloque in base.politicas.values():
            for m in re.finditer(r"Version:\s*(\d+)(.*?)(?=\n---|\Z)", bloque, re.S):
                if "OBSOLETA" in m.group(2).upper():
                    base.politicas_obsoletas.append(f"v{m.group(1)}")

        # pedidos
        for linea in bloque_ped.splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            partes = [p.strip().strip('"') for p in linea.split(",")]
            if len(partes) >= 5 and partes[0].startswith("PED-"):
                base.pedidos.append(
                    Pedido(
                        folio=partes[0],
                        cliente=partes[1],
                        sucursal_origen=partes[2].replace("Sucursal ", ""),
                        contenido=partes[3],
                        estatus=partes[4],
                        fecha_promesa=partes[5] if len(partes) > 5 else "",
                    )
                )

    # --- historial de quejas ------------------------------------------------
    ruta_q = datos / "historial_quejas.jsonl"
    if ruta_q.exists():
        for linea in ruta_q.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            try:
                base.quejas.append(json.loads(linea))
            except json.JSONDecodeError:
                continue

    return base


# ---------------------------------------------------------------------------
# Recuperacion con trazabilidad (Transparencia)
# ---------------------------------------------------------------------------


def recuperar_contexto(consulta: str, base: BaseConocimiento) -> tuple[str, list[str]]:
    """
    Devuelve (contexto, fuentes). El contexto es lo unico que se le permite
    al modelo usar. Cada bloque cita su archivo de origen.
    """
    fragmentos: list[str] = []
    fuentes: list[str] = []

    producto = base.buscar_producto(consulta)
    if producto:
        mencionadas = base.sucursales_mencionadas(consulta)
        # EQUIDAD: si el usuario no nombra sucursal, se responden LAS CINCO.
        # Nunca se responde solo por la sucursal con mejores datos.
        objetivo = mencionadas or SUCURSALES
        fragmentos.append(producto.como_contexto(objetivo))
        fuentes.append(producto.fuente)
        if not mencionadas:
            fragmentos.append(
                "Nota: la consulta no especificaba sucursal, por lo que se informan "
                "las 5 sucursales por igual."
            )

    for ped in base.buscar_pedidos(consulta):
        fragmentos.append(ped.como_contexto())
        fuentes.append("politicas_y_pedidos_activos.txt")

    q = normalizar(consulta)
    if any(t in q for t in ("devolucion", "devolver", "politica", "garantia", "credito")):
        texto = base.politicas.get("POLÍTICA DE DEVOLUCIONES", "")
        if texto:
            # se recorta a la parte VIGENTE: las versiones obsoletas nunca entran
            vigente = re.split(r"\n---\n", texto)[0].strip()
            fragmentos.append("POLÍTICA DE DEVOLUCIONES (VIGENTE):\n" + vigente)
            fuentes.append("politicas_y_pedidos_activos.txt")

    if any(t in q for t in ("precio", "cobrar", "costo", "cuanto cuesta")):
        if "POLÍTICA DE PRECIOS" in base.politicas:
            fragmentos.append(
                "POLÍTICA DE PRECIOS (VIGENTE):\n"
                + base.politicas["POLÍTICA DE PRECIOS"].split("---")[0].strip()
            )
            fuentes.append("politicas_y_pedidos_activos.txt")

    if any(t in q for t in ("pago", "pagar", "factura", "aprobar", "autoriza")):
        if "POLÍTICA DE AUTORIZACIÓN DE PAGOS" in base.politicas:
            fragmentos.append(
                "POLÍTICA DE AUTORIZACIÓN DE PAGOS (VIGENTE):\n"
                + base.politicas["POLÍTICA DE AUTORIZACIÓN DE PAGOS"].split("---")[0].strip()
            )
            fuentes.append("politicas_y_pedidos_activos.txt")

    if any(t in q for t in ("queja", "reclamo", "cliente", "molesto", "llamada")):
        quejas = base.quejas_de_cliente(consulta)
        if quejas:
            cerradas = sum(1 for x in quejas if x.get("resuelto"))
            fragmentos.append(
                f"Historial del cliente {quejas[0]['cliente']}: "
                f"{len(quejas)} incidencias registradas, "
                f"{len(quejas) - cerradas} sin resolver. "
                f"Canales: {', '.join(sorted({x.get('canal', '?') for x in quejas}))}."
            )
            fuentes.append("historial_quejas.jsonl")

    return "\n".join(fragmentos), sorted(set(fuentes))


# ---------------------------------------------------------------------------
# Deteccion de duplicados y decision (Confiabilidad y Rendicion de cuentas)
# ---------------------------------------------------------------------------


# Sufijos societarios que el OCR lee de forma inconsistente (con puntos, sin
# puntos, abreviados). Se eliminan antes de comparar nombres de proveedor.
_SUFIJOS_SOCIETARIOS = (
    "sadecv", "sadcv", "sadec", "sapi", "saderl", "sas", "sa", "sc", "srl",
    "ltda", "inc", "corp", "cv",
)


def _clave_proveedor(proveedor: str | None) -> str:
    """
    Normaliza el nombre del proveedor para poder compararlo entre un PDF y una
    foto. Debe tratar como iguales estas dos formas del MISMO proveedor:

        "Quimicos del Bajio, S.A. de C.V."   (como viene en el PDF)
        "QUIMICOS DEL BAJIO SA DE CV"        (como lo lee el OCR de la foto)

    Por eso se quitan TODOS los caracteres no alfanumericos y despues se
    recortan los sufijos societarios ('sa de cv', 'sapi', 'sas', ...), que son
    justamente los que el OCR de una foto borrosa suele deformar.
    """
    base = re.sub(r"[^a-z0-9]", "", normalizar(proveedor or ""))
    cambio = True
    while cambio:
        cambio = False
        for sufijo in _SUFIJOS_SOCIETARIOS:
            if base.endswith(sufijo) and len(base) > len(sufijo) + 2:
                base = base[: -len(sufijo)]
                cambio = True
                break
    return base


def _clave_folio(folio: str | None) -> str:
    """Normaliza el folio: 'FAC-2026-001', 'fac 2026 001' y 'FAC2026001' son iguales."""
    return re.sub(r"[^a-z0-9]", "", normalizar(folio or ""))


def huella_factura(
    proveedor: str | None, folio: str | None, total: float | None
) -> str:
    """
    Huella deterministica del COBRO, no del archivo.

    Es lo que permite detectar que la misma factura llego dos veces: una como
    PDF llamado 'factura_limpia.pdf' y otra como foto de WhatsApp. Comparar
    nombres de archivo no habria detectado nada.
    """
    partes = [
        _clave_proveedor(proveedor),
        _clave_folio(folio),
        f"{round(float(total), 2):.2f}" if isinstance(total, (int, float)) else "",
    ]
    return hashlib.sha256("|".join(partes).encode()).hexdigest()


def huella_aproximada(proveedor: str | None, total: float | None) -> str:
    """
    Huella secundaria sin folio. Sirve para avisar "posible duplicado" cuando
    el folio no se pudo leer pero el monto y el proveedor coinciden.
    """
    partes = [
        _clave_proveedor(proveedor),
        f"{round(float(total), 2):.2f}" if isinstance(total, (int, float)) else "",
    ]
    return hashlib.sha256("|".join(partes).encode()).hexdigest()


@dataclass
class Decision:
    estado: str
    motivo: str
    mostrar_monto: bool
    requiere_humano: bool
    aviso: str = ""


def decidir_factura(
    extraccion: dict,
    huellas_registradas: dict[str, dict],
    huellas_aprox: dict[str, dict] | None = None,
    umbral: float = UMBRAL_CONFIANZA,
) -> Decision:
    """
    Aplica las reglas del negocio en orden de prioridad.

    1. Duplicado exacto  -> bloquear siempre, sin importar la confianza.
    2. Duplicado probable -> pedir revision (mismo proveedor y monto, folio ilegible).
    3. Confianza baja     -> revision humana y NO mostrar el monto.
    4. Caso normal        -> pendiente de aprobacion de LAURA (nunca pago automatico).
    """
    proveedor = extraccion.get("proveedor")
    folio = extraccion.get("folio")
    total = extraccion.get("total")
    confianza = extraccion.get("confianza_total")
    legible = extraccion.get("monto_legible", True)

    if not legible or total is None:
        return Decision(
            estado=ESTADOS_FACTURA["revision"],
            motivo=(
                "El monto no se pudo leer con suficiente certeza. El sistema NO inventa "
                "una cifra: detiene el flujo y lo manda a revisión humana."
            ),
            mostrar_monto=False,
            requiere_humano=True,
            aviso="⚠️ El importe no es legible. No se muestra ningún monto.",
        )

    huella = huella_factura(proveedor, folio, total)
    if huella in huellas_registradas:
        previo = huellas_registradas[huella]
        return Decision(
            estado=ESTADOS_FACTURA["duplicado"],
            motivo=(
                f"Ya existe un registro idéntico: folio {previo.get('folio')}, "
                f"mismo proveedor y mismo monto (${float(total):,.2f} MXN). "
                "El pago se bloquea automáticamente y se escala a la gerencia."
            ),
            mostrar_monto=True,
            requiere_humano=True,
            aviso="🚨 PAGO DUPLICADO DETECTADO — bloqueado automáticamente.",
        )

    if huellas_aprox:
        ha = huella_aproximada(proveedor, total)
        if ha in huellas_aprox and not folio:
            previo = huellas_aprox[ha]
            return Decision(
                estado=ESTADOS_FACTURA["revision"],
                motivo=(
                    f"El folio no se pudo leer y existen coincidencias de proveedor y "
                    f"monto con el registro {previo.get('folio')}. Se marca como posible "
                    "duplicado para revisión."
                ),
                mostrar_monto=True,
                requiere_humano=True,
                aviso="⚠️ Posible duplicado: folio ilegible con proveedor y monto coincidentes.",
            )

    if confianza is not None and confianza < umbral:
        return Decision(
            estado=ESTADOS_FACTURA["revision"],
            motivo=(
                f"La confianza de extracción fue {confianza:.0%}, por debajo del umbral "
                f"de {umbral:.0%}. Se envía a revisión humana obligatoria."
            ),
            mostrar_monto=True,
            requiere_humano=True,
            aviso=f"⚠️ Confiabilidad baja ({confianza:.0%}). Requiere revisión de Laura.",
        )

    return Decision(
        estado=ESTADOS_FACTURA["pendiente"],
        motivo=(
            "Extracción confiable. El sistema sugiere el registro, pero el pago queda "
            "pendiente de la aprobación explícita de Laura (cuentas por pagar). "
            "La IA nunca paga sola."
        ),
        mostrar_monto=True,
        requiere_humano=True,
        aviso="✅ Extracción confiable. Pendiente de aprobación humana.",
    )


# ---------------------------------------------------------------------------
# Diagnóstico de errores de Azure (traducción a instrucciones accionables)
# ---------------------------------------------------------------------------
# Un error crudo de Azure es inútil para quien está presentando el proyecto. El
# caso peor: DefaultAzureCredential, cuando no encuentra credenciales, imprime
# PÁRRAFOS enumerando cada método que intentó. Si eso aparece durante la
# demostración, parece que el proyecto está roto cuando lo único que falta es
# un `az login`.
#
# Estas correspondencias se probaron contra los mensajes REALES de los SDK
# (por ejemplo, el texto de DefaultAzureCredential se copió de una ejecución
# real, no se supuso).
#
# EL ORDEN IMPORTA: se usa la primera coincidencia. Por eso las claves inválidas
# y los permisos van en patrones separados: si se mezclan en una misma entrada,
# un patrón genérico como "401" se traga el caso específico y el mensaje que ve
# el usuario no corresponde al problema real.
# ---------------------------------------------------------------------------

GUIA_DE_ERRORES: list[tuple[tuple[str, ...], str]] = [
    (
        # Mensaje real de azure-identity cuando no hay ninguna credencial.
        ("DefaultAzureCredential failed to retrieve a token",
         "EnvironmentCredential authentication unavailable",
         "ManagedIdentityCredential authentication unavailable",
         "AzureCliCredential"),
        "**No se pudo autenticar con Azure.**\n\n"
        "En su computadora: abra una terminal, ejecute `az login` y vuelva a "
        "intentarlo.\n\n"
        "En App Service: compruebe que la identidad administrada esté activada y "
        "que tenga el rol **Cognitive Services User** sobre el recurso de Foundry. "
        "Ese rol es obligatorio incluso para el propietario del recurso.",
    ),
    (
        ("Default model deployment not configured",
         "model deployment not configured"),
        "**Content Understanding no tiene modelos predeterminados.**\n\n"
        "Los analizadores preconstruidos los necesitan. Configúrelos en "
        "https://contentunderstanding.ai.azure.com/settings → *Agregar recurso* → "
        "seleccione su recurso de Foundry y marque *Enable autodeployment for "
        "required models*.\n\n"
        "Se requieren los despliegues `gpt-4.1`, `gpt-4.1-mini` y "
        "`text-embedding-3-large`.",
    ),
    (
        ("invalid subscription key", "invalid API key", "API key is invalid",
         "Access denied due to invalid subscription key", "401 Unauthorized"),
        "**La clave del servicio no es válida.**\n\n"
        "Si usa Key Vault, compruebe que el secreto esté actualizado. Si usa "
        "variables de entorno, vuelva a copiar la clave desde *Claves y punto de "
        "conexión* del recurso en el portal de Azure.",
    ),
    (
        ("Access denied", "PermissionDenied", "does not have permission",
         "AuthorizationFailed", "403 Forbidden"),
        "**Acceso denegado.**\n\n"
        "Casi siempre falta el rol **Cognitive Services User** sobre el recurso "
        "de Foundry. Asígnelo en el portal: recurso → *Control de acceso (IAM)* → "
        "*Agregar asignación de roles*.\n\n"
        "Si la aplicación corre en App Service, asígnelo a la **identidad "
        "administrada** de la aplicación, no a su cuenta de usuario.",
    ),
    (
        ("DeploymentNotFound", "deployment not found", "ModelNotFound",
         "does not exist"),
        "**El modelo o despliegue no existe.**\n\n"
        "Verifique que el nombre en `FOUNDRY_MODEL` coincida EXACTAMENTE con el "
        "nombre del despliegue (no con el del modelo) en "
        "https://ai.azure.com → Implementaciones.",
    ),
    (
        ("Name or service not known", "Failed to resolve", "getaddrinfo",
         "nodename nor servname", "SSLError", "certificate verify failed"),
        "**No se pudo resolver el nombre del servicio.**\n\n"
        "El endpoint tiene un error de escritura o el recurso ya no existe. "
        "Revise las variables `*_ENDPOINT` en su `.env` o en los App Settings. "
        "El endpoint del PROYECTO debe incluir `/api/projects/<nombre>`.",
    ),
    (
        ("Quota exceeded", "quota", "429", "RateLimit", "Too Many Requests"),
        "**Se agotó la cuota o se superó el límite de peticiones.**\n\n"
        "Espere un minuto y reintente, o reduzca la capacidad del despliegue. "
        "Los planes gratuitos tienen límites mensuales por servicio.",
    ),
    (
        ("contentFilter", "content_policy_violation", "content filter"),
        "**El filtro de contenido bloqueó la operación.**\n\n"
        "Pruebe con otra descripción. Los modelos de Azure aplican moderación de "
        "contenido y pueden rechazar una petición legítima.",
    ),
    (
        ("Connection refused", "Connection reset", "timed out", "Timeout",
         "ReadTimeout", "ConnectTimeout"),
        "**El servicio no respondió.**\n\n"
        "Suele ser temporal. Compruebe su conexión a internet y vuelva a "
        "intentarlo. Si persiste, revise el estado del servicio en el portal de "
        "Azure.",
    ),
]


def explicar_error(exc: BaseException) -> str | None:
    """
    Devuelve una explicación accionable si reconoce el error, o None.

    Se compara contra el texto de la excepción y de toda su cadena de causas,
    porque los SDK de Azure anidan el motivo real en `__cause__` y el mensaje
    de la excepción externa suele ser genérico.
    """
    partes = [str(exc), type(exc).__name__]
    causa = exc.__cause__
    profundidad = 0
    while causa is not None and profundidad < 5:
        partes.append(str(causa))
        partes.append(type(causa).__name__)
        causa = causa.__cause__
        profundidad += 1

    texto = " ".join(partes).lower()
    for patrones, explicacion in GUIA_DE_ERRORES:
        if any(p.lower() in texto for p in patrones):
            return explicacion
    return None


# ---------------------------------------------------------------------------
# Datos de ejemplo para el modo demostración
# ---------------------------------------------------------------------------

# Extracciones simuladas para las facturas de la carpeta samples/. Se usan
# cuando la aplicación se ejecuta en modo demo (sin Azure configurado), y el
# resultado se muestra SIEMPRE con el aviso de que no proviene de Azure.
#
# Esta función existe separada de la interfaz para poder probarla. El motivo es
# concreto: aquí hubo un error real que solo se detectó al manejar la aplicación
# con un navegador. La condición era `"borrosa" in nombre`, pero el archivo se
# llama `factura_monto_borroso.jpg` (con O). La comprobación fallaba y el
# archivo caía en la rama final, que representa una factura limpia con total
# confiable: el caso que debe demostrar que el sistema NO inventa montos
# mostraba un monto seguro de sí mismo.
#
# La lección: cuando la clave de una decisión es un nombre de archivo, hay que
# probar TODOS los nombres reales, no el que uno recuerda.
_FACTURAS_DEMO: list[tuple[tuple[str, ...], dict]] = [
    # El total es ilegible (Confiabilidad y seguridad).
    # Se comparan tallos sin la vocal final para cubrir borroso/borrosa.
    (
        ("monto_borros", "monto borros", "monto_ilegible", "importe_ilegible"),
        {
            "proveedor": "Quimicos del Bajio, S.A. de C.V.",
            "folio": "FAC-2026-001",
            "fecha": "2026-10-12",
            "total": None,
            "confianza_total": 0.41,
            "monto_legible": False,
        },
    ),
    # Toda la foto es ilegible: ni siquiera el proveedor.
    (
        ("borros", "ilegible", "movida", "desenfocad"),
        {
            "proveedor": None, "folio": None, "fecha": None,
            "total": None, "confianza_total": 0.28, "monto_legible": False,
        },
    ),
    # MISMO cobro que factura_limpia.pdf, con otro nombre de archivo.
    (
        ("final2", "duplicad", "reenvio", "reenvío"),
        {
            "proveedor": "Quimicos del Bajio, S.A. de C.V.",
            "folio": "FAC-2026-001", "fecha": "2026-10-12",
            "total": 30392.00, "confianza_total": 0.94, "monto_legible": True,
        },
    ),
    # Otro proveedor, otro folio: no debe marcarse como duplicado.
    (
        ("distinta", "papelera", "norte", "fac-2026-014"),
        {
            "proveedor": "Distribuidora Papelera del Norte, S.A. de C.V.",
            "folio": "FAC-2026-014", "fecha": "2026-10-14",
            "total": 24165.20, "confianza_total": 0.95, "monto_legible": True,
        },
    ),
    # La factura limpia de referencia.
    (
        ("limpia", "factura"),
        {
            "proveedor": "Quimicos del Bajio, S.A. de C.V.",
            "folio": "FAC-2026-001", "fecha": "2026-10-12",
            "total": 30392.00, "confianza_total": 0.94, "monto_legible": True,
        },
    ),
]


def extraccion_demo(nombre_archivo: str) -> tuple[dict, bool]:
    """
    Devuelve (extracción, reconocido) para una factura del modo demostración.

    Si el nombre no coincide con ninguna factura conocida, `reconocido` es
    False y la extracción sale NO legible. Es deliberado: ante un archivo
    desconocido, lo prudente cuando se habla de dinero es no suponer sus datos,
    no presentarlos como una lectura confiable.
    """
    nombre = (nombre_archivo or "").lower()
    for tallos, datos in _FACTURAS_DEMO:
        if any(t in nombre for t in tallos):
            return dict(datos), True

    return (
        {
            "proveedor": None, "folio": None, "fecha": None,
            "total": None, "confianza_total": None, "monto_legible": False,
        },
        False,
    )


# ---------------------------------------------------------------------------
# Priorizacion de quejas (SLA de 15 minutos de Mariana)
# ---------------------------------------------------------------------------


def priorizar(sentimiento: str, mensaje: str = "") -> tuple[str, str]:
    """Devuelve (prioridad, justificacion)."""
    m = normalizar(mensaje)
    # Señales de premura. Incluye el patron del caso: el cliente que ya llamo
    # varias veces y nadie le contesta (SLA de 15 minutos de Mariana).
    senales = (
        "urgente", "hoy", "ya ", "inmediato", "cuarta vez", "cuatro vez",
        "tercera vez", "varias veces", "otra vez", "de nuevo",
        "nadie contesta", "nadie me contesta", "no contesta", "nadie responde",
        "evento", "manana", "hoy mismo", "llevo",
    )
    urgente = any(s in m for s in senales)
    s = normalizar(sentimiento)

    if s == "negative" and urgente:
        return (
            "🔥 Urgente (<15 min)",
            "Sentimiento negativo y el mensaje indica premura o reincidencia.",
        )
    if s == "negative":
        return (
            "🟠 Alta (<1 h)",
            "Sentimiento negativo: entra en el SLA de atención de 15 minutos.",
        )
    if s in ("mixed", "neutral"):
        return "🟡 Media (<4 h)", "Sentimiento neutro o mixto."
    if s == "positive":
        return "🟢 Normal (<24 h)", "Sentimiento positivo: no requiere acción inmediata."
    return "🟡 Media (<4 h)", "Sentimiento no determinado."


# ---------------------------------------------------------------------------
# Reporte directivo (Don Ernesto)
# ---------------------------------------------------------------------------

VENTAS_MENSUALES = {
    "Guadalajara": 145200,
    "Zapopan": 187000,
    "Leon": 193000,
    "Queretaro": 226000,
    "Aguascalientes": 166500,
}

# Costo estimado del piloto en Azure (MXN/mes). Cifras a ajustar con la
# factura real: Don Ernesto pide "un piloto que cueste lo previsto".
COSTO_PILOTO = {
    "App Service B1 (Linux, Python)": 235.00,
    "Microsoft Foundry — modelos (consumo)": 180.00,
    "Content Understanding (documentos)": 90.00,
    "Azure Speech (voz)": 60.00,
    "Azure AI Language (texto)": 45.00,
    "Key Vault + Application Insights": 35.00,
}


def reporte_ventas() -> dict:
    total = sum(VENTAS_MENSUALES.values())
    return {
        "por_sucursal": dict(VENTAS_MENSUALES),
        "total": total,
        "promedio": total / len(VENTAS_MENSUALES),
        "costo_piloto": sum(COSTO_PILOTO.values()),
        "detalle_costo": dict(COSTO_PILOTO),
    }
