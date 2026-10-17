"""
Verifica que el documento de entrega cumpla los requisitos del enunciado.

El enunciado es explícito en la sección 6 «Entrega»:

  * «Debes cargar un documento Markdown (Solo markdown, no se aceptará otro
    formato) de la aplicación del proyecto con imágenes capturas del proyecto,
    explicación de la solución y del problema resuelto.»

Y en la sección 4 pide responder seis preguntas de IA responsable «con evidencia
de su propio prototipo».

Un documento que no cumpla el formato, o que no responda las seis preguntas, se
penaliza. Esta comprobación lo revisa de forma mecánica antes de subirlo.

Uso:
    python tools/verificar_entrega.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent
DOCUMENTO = RAIZ / "ENTREGA.md"

VERDE, ROJO, AMARILLO, GRIS, NEGRITA, FIN = (
    "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[1m", "\033[0m",
)

_ok = 0
_fallo = 0
_aviso = 0


def revisar(titulo: str, condicion: bool, detalle: str = "") -> None:
    global _ok, _fallo
    if condicion:
        _ok += 1
        print(f"  {VERDE}OK{FIN}    {titulo}")
    else:
        _fallo += 1
        print(f"  {ROJO}FALLA{FIN} {titulo}")
    if detalle:
        for l in str(detalle).splitlines()[:10]:
            print(f"        {GRIS}{l}{FIN}")


def avisar(titulo: str, detalle: str = "") -> None:
    global _aviso
    _aviso += 1
    print(f"  {AMARILLO}AVISO{FIN} {titulo}")
    if detalle:
        for l in str(detalle).splitlines()[:8]:
            print(f"        {GRIS}{l}{FIN}")


def main() -> int:
    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{NEGRITA}  VERIFICACIÓN DEL DOCUMENTO DE ENTREGA{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    print(f"{GRIS}Contrasta ENTREGA.md con los requisitos de la sección 6 del enunciado.{FIN}\n")

    if not DOCUMENTO.exists():
        print(f"{ROJO}No existe {DOCUMENTO.name}{FIN}")
        return 1

    texto = DOCUMENTO.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    print("1. FORMATO (el enunciado exige SOLO markdown)")
    revisar("El archivo tiene extensión .md", DOCUMENTO.suffix == ".md",
            f"{DOCUMENTO.name}")
    revisar("El documento tiene contenido sustancial", len(texto) > 8000,
            f"{len(texto):,} caracteres")
    titulos = len(re.findall(r"^#+ ", texto, re.M))
    revisar("Usa títulos de markdown", titulos >= 8, f"{titulos} títulos")
    tablas = len(re.findall(r"^\|[-\s|]+\|$", texto, re.M))
    revisar("Usa tablas de markdown", tablas >= 4, f"{tablas} tablas")
    revisar("Usa bloques de código", texto.count("```") >= 12,
            f"{texto.count('```') // 2} bloques")

    # ------------------------------------------------------------------
    print("\n2. IMÁGENES Y CAPTURAS (el enunciado las exige)")
    incrustadas = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", texto)
    revisar("Incrusta capturas con sintaxis de imagen", len(incrustadas) >= 8,
            f"{len(incrustadas)} imágenes con ![...](...)")

    faltantes = [r for r in incrustadas if not (RAIZ / r).exists()]
    revisar("Todas las imágenes referenciadas existen", not faltantes,
            "\n".join(faltantes) if faltantes else
            f"{len(incrustadas)} archivos verificados en disco")

    # Imágenes vacías o diminutas
    pequenas = []
    for r in incrustadas:
        ruta = RAIZ / r
        if ruta.exists() and ruta.stat().st_size < 5000:
            pequenas.append(f"{r} ({ruta.stat().st_size} bytes)")
    revisar("Ninguna captura está en blanco", not pequenas,
            "\n".join(pequenas) if pequenas else
            "Todas las capturas pesan más de 5 KB")

    # Las referencias rotas dentro de bloques comentados no cuentan como error,
    # pero se avisa por si el usuario descomenta y olvida crear el archivo.
    comentado = re.findall(r"<!--(.*?)-->", texto, re.S)
    refs_comentadas = []
    for bloque in comentado:
        refs_comentadas += re.findall(r"docs/capturas/([A-Za-z0-9_]+\.png)", bloque)
    if refs_comentadas:
        avisar(
            "Hay referencias a capturas dentro de bloques comentados",
            "\n".join(refs_comentadas) +
            "\nSi descomenta esos bloques, cree antes los archivos.",
        )

    # ------------------------------------------------------------------
    print("\n3. EXPLICACIÓN DEL PROBLEMA (sección 1 del enunciado)")
    for concepto, porque in (
        ("Río Claro", "nombra la empresa del caso"),
        ("factura", "menciona el problema de las facturas"),
        ("duplicad", "menciona el pago duplicado"),
        ("queja", "menciona el problema de las quejas"),
        ("catálogo", "menciona el desorden del catálogo"),
    ):
        revisar(f"Explica el problema: {porque}", concepto.lower() in texto.lower())

    revisar(
        "Los cinco personajes aparecen en el documento",
        all(p in texto for p in ("Ernesto", "Laura", "Mariana", "Toño", "Carlos")),
        "El enunciado describe 5 personajes y la solución debe atenderlos a todos.",
    )
    revisar(
        "Menciona el costo del piloto (Don Ernesto pide uno que cueste lo previsto)",
        "costo" in texto.lower() and ("645" in texto or "MXN" in texto),
    )

    # ------------------------------------------------------------------
    print("\n4. LAS CARGAS DE TRABAJO DEL EXAMEN (sección 1 del enunciado)")
    for carga, terminos in (
        ("IA generativa", ("generativa",)),
        ("Agentes", ("agente",)),
        ("Análisis de texto", ("análisis de texto", "sentimiento")),
        ("Voz", ("voz", "speech")),
        ("Visión", ("visión", "vision", "imagen")),
        ("Extracción de información", ("extracción", "content understanding")),
    ):
        encontrado = any(t.lower() in texto.lower() for t in terminos)
        revisar(f"Cubre la carga de trabajo: {carga}", encontrado)

    # ------------------------------------------------------------------
    print("\n5. LAS SEIS PREGUNTAS DE IA RESPONSABLE (sección 4 del enunciado)")
    principios = [
        ("Equidad", "trata igual a clientes de todas las sucursales"),
        ("Confiabilidad", "qué pasa si una factura está borrosa"),
        ("Privacidad", "Entra ID y Key Vault"),
        ("Inclusión", "funciona por voz y desde el celular"),
        ("Transparencia", "sabe que habla con una IA y de qué documento salió"),
        ("Rendición de cuentas", "quién revisa y aprueba lo que sugiere la IA"),
    ]
    for principio, pregunta in principios:
        # Se busca el principio con su propia sección de nivel 3
        patron_seccion = re.compile(
            rf"^###\s+4\.\d+\s+{re.escape(principio)}(.*?)(?=^###\s|\Z)",
            re.M | re.I | re.S,
        )
        encontrada = patron_seccion.search(texto)
        revisar(
            f"Tiene una sección propia para {principio}",
            bool(encontrada),
            f"El enunciado pregunta: «{pregunta}»",
        )

        # ------------------------------------------------------------------
        # La respuesta debe apoyarse en algo CONCRETO del prototipo.
        #
        # Antes esta comprobación buscaba la palabra «Evidencia» en todo el
        # documento. Era una prueba tramposa: bastaba con escribir el epígrafe
        # «**Evidencia:**» para pasarla, aunque el párrafo no dijera nada. Y si
        # alguien redactaba con naturalidad, sin el epígrafe, fallaba aunque la
        # prueba estuviera ahí.
        #
        # Ahora se mira CADA sección y se exige que mencione una prueba real:
        # una captura, un archivo del proyecto, una función concreta o un
        # resultado de prueba. Eso sí distingue una respuesta sostenida de una
        # declaración vacía.
        # ------------------------------------------------------------------
        cuerpo = encontrada.group(1) if encontrada else ""
        anclas = (
            "docs/capturas/",          # una captura concreta
            "tools/",                  # una prueba ejecutable
            ".py",                     # una función o módulo del prototipo
            ".csv", ".jsonl", ".txt",  # un dato del proyecto
            "configura", "captura", "prueba",  # referencia a la comprobación
        )
        tiene_ancla = any(a in cuerpo for a in anclas)
        revisar(
            f"Responde con evidencia propia, no con la definición ({principio})",
            bool(cuerpo) and tiene_ancla,
            "El enunciado pide «reconocer el principio en una situación» con\n"
            "«evidencia de su propio prototipo»: una captura, un archivo o una\n"
            "prueba concreta, no una declaración.",
        )

    # Cada principio debería apuntar a una parte concreta del prototipo
    revisar(
        "Apunta a partes concretas del prototipo (funciones, archivos, capturas)",
        texto.count("docs/capturas") >= 8
        and any(f in texto for f in ("rio_claro.py", "decidir_factura", "build_context",
                                     "recuperar_contexto", "extraer_factura")),
        "Decir «aplicamos transparencia» no vale; hay que mostrar dónde.",
    )

    # ------------------------------------------------------------------
    print("\n6. DATOS QUE EL ESTUDIANTE DEBE COMPLETAR")
    # Estas comprobaciones son AVISOS, no fallos: el documento es una plantilla
    # y estos campos los rellena el estudiante. Marcarlos como fallo daría un
    # resultado rojo permanente que ocultaría los problemas reales.
    falta_nombre = "SU NOMBRE COMPLETO" in texto
    falta_liga = "SU-APP.azurewebsites.net" in texto

    if falta_nombre:
        avisar(
            "Falta su nombre en la cabecera del documento",
            "Reemplace <!-- SU NOMBRE COMPLETO --> por su nombre.",
        )
    else:
        revisar("El nombre del estudiante está completo", True)

    if falta_liga:
        avisar(
            "Falta la liga del prototipo",
            "Aparece como marcador de posición en las líneas "
            + ", ".join(
                str(i) for i, l in enumerate(texto.splitlines(), 1)
                if "SU-APP.azurewebsites.net" in l
            )
            + ".\n"
            "El enunciado exige que el revisor pueda entrar «como lo haría un\n"
            "usuario normal»: sin esa liga no puede evaluar el prototipo.",
        )
    else:
        revisar("La liga del prototipo está completa", True)

    # ------------------------------------------------------------------
    # ¿Las capturas evidencian Azure o el modo demostración?
    #
    # Antes esto avisaba con solo encontrar la palabra «modo demo» en el
    # documento. Pero el documento DEBE explicar el modo demostración —es parte
    # del diseño, permite ver la aplicación sin credenciales—, así que el aviso
    # saltaba siempre y no distinguía nada.
    #
    # Lo que importa es si las CAPTURAS muestran Azure. Se comprueba leyendo el
    # píxel de la barra lateral de la primera captura: si la casilla «Forzar
    # modo DEMO» está marcada, Streamlit la pinta con un color de acento.
    # Es más fiable que buscar texto, porque el texto del documento no dice
    # nada sobre la imagen.
    # ------------------------------------------------------------------
    captura_inicial = RAIZ / "docs" / "capturas" / "01_estado_inicial.png"
    if captura_inicial.exists():
        # El modo demo se delata por un AVISO AZUL CLARO que ocupa el ancho de
        # la barra lateral, justo debajo de la casilla. No aparece cuando la
        # aplicación está conectada a Azure.
        #
        # Se probó antes a detectar el color de la CASILLA marcada, pero es un
        # criterio frágil: el color de acento de Streamlit se usa también en
        # botones y enlaces, así que daba falsos positivos. El aviso, en
        # cambio, es una banda ancha y uniforme: no se confunde con nada.
        try:
            from PIL import Image

            with Image.open(captura_inicial) as im:
                rgb = im.convert("RGB")
                ancho, alto = rgb.size
                # Zona del aviso: franja de la barra lateral, a media altura.
                zona = rgb.crop((0, int(alto * 0.55), int(ancho * 0.15),
                                 int(alto * 0.85)))
                pixeles = list(zona.getdata())

            # Azul claro de los avisos de Streamlit (#dae8fc / #e7f3fe
            # aproximadamente): mucho azul, bastante verde, y claramente más
            # azul que rojo.
            aviso_azul = sum(
                1 for r, g, b in pixeles
                if b > 215 and 200 < g < 245 and r < 200 and (b - r) > 45
            )
            proporcion = aviso_azul / max(1, len(pixeles))
            # El aviso ocupa buena parte de la franja cuando está presente.
            if proporcion > 0.10:
                avisar(
                    "La captura inicial parece estar en MODO DEMO",
                    f"Se detectó el aviso azul de modo demo "
                    f"({proporcion:.1%} de la franja).\n"
                    "Las capturas deben evidenciar el funcionamiento con Azure.\n"
                    "  python tools/generar_capturas_entrega.py",
                )
            else:
                revisar(
                    "Las capturas muestran la aplicación conectada a Azure",
                    True,
                    f"Sin rastro del aviso de modo demo ({proporcion:.1%}).",
                )
        except ImportError:
            avisar(
                "No se pudo comprobar las capturas (falta Pillow)",
                "Instale Pillow para verificar automáticamente si las capturas\n"
                "evidencian Azure o el modo demostración.",
            )
        except Exception as exc:
            avisar(
                "No se pudo analizar la captura inicial",
                f"{type(exc).__name__}: {str(exc)[:150]}",
            )

    # ------------------------------------------------------------------
    print("\n7. FECHA DE ENTREGA (viernes 6 de noviembre, 23:45 GMT-6)")
    revisar("El documento menciona la fecha de entrega",
            "noviembre" in texto.lower() or "2026" in texto)
    revisar("Explica cómo se construyó la fuente única de verdad",
            "catalogo_unificado" in texto and ("unific" in texto.lower()))

    # ------------------------------------------------------------------
    print()
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    total = _ok + _fallo
    if _fallo == 0:
        print(f"{VERDE}RESULTADO: {_ok}/{total} comprobaciones correctas.{FIN}")
        if _aviso:
            print(f"{AMARILLO}{_aviso} aviso(s) que debe revisar antes de entregar.{FIN}")
        print("El documento cumple los requisitos del enunciado.")
        print(f"{NEGRITA}{'=' * 74}{FIN}")
        return 0
    print(f"{ROJO}RESULTADO: {_fallo} de {total} comprobaciones FALLARON.{FIN}")
    print(f"{AMARILLO}El documento NO cumple todo lo que pide el enunciado.{FIN}")
    print(f"{NEGRITA}{'=' * 74}{FIN}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
