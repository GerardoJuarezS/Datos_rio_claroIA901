"""
Verifica que las facturas generadas tengan una capa de texto extraible.
Es el mismo principio que aplica Azure Content Understanding: si no hay
texto extraible, el documento necesita OCR.

Uso:
    python tools/verificar_facturas.py
"""

from __future__ import annotations

import re
import sys
import zlib
from pathlib import Path

# La consola de Windows usa cp1252 por defecto y no admite algunos simbolos.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent


def extraer_texto(pdf_path: Path) -> str:
    data = pdf_path.read_bytes()
    objs: dict[int, bytes] = {}
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", data):
        n = int(m.group(1))
        s = m.end()
        e = data.find(b"endobj", s)
        objs[n] = data[s : e if e > 0 else len(data)]

    def stream(body: bytes):
        m = re.search(rb"stream\r?\n", body)
        if not m:
            return None
        raw = body[m.end() : body.rfind(b"endstream")]
        if b"FlateDecode" in body[: m.start()]:
            try:
                raw = zlib.decompress(raw)
            except Exception:
                return None
        return raw

    # Mapa inverso desde ToUnicode
    gid_a_char: dict[int, str] = {}
    for n, b in sorted(objs.items()):
        if b"/CMapType" not in b:
            continue
        raw = stream(b)
        if not raw:
            continue
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", raw):
            try:
                gid_a_char[int(src, 16)] = bytes.fromhex(dst.decode()).decode("utf-16-be")
            except Exception:
                pass

    partes: list[str] = []
    for n, b in sorted(objs.items()):
        raw = stream(b)
        if not raw or b"Tj" not in raw:
            continue
        for m in re.finditer(rb"<([0-9A-Fa-f]+)>\s*Tj|([-\d.]+)\s+([-\d.]+)\s+Td|(ET)", raw):
            if m.group(1):
                hx = m.group(1).decode()
                s = ""
                for i in range(0, len(hx), 4):
                    s += gid_a_char.get(int(hx[i : i + 4], 16), "")
                partes.append(s)
            elif m.group(4):
                partes.append("\n")
    return "".join(partes)


ESPERADO = [
    "FAC-2026-001",
    "Quimicos del Bajio",
    "2026-10-12",
    "30,392.00",
    "Cloro blanqueador 1 L",
    "Papel higienico institucional 500 hojas",
    "RFC: QBA850312H78",
]


def main() -> int:
    print("=" * 68)
    print("VERIFICACION DE LA CAPA DE TEXTO DE LAS FACTURAS")
    print("=" * 68)

    fallos = 0
    pdfs = sorted((RAIZ / "samples").glob("*.pdf"))
    if not pdfs:
        print("ERROR: no hay PDF en samples/. Ejecute tools/generar_facturas.py")
        return 1

    for pdf in pdfs:
        texto = extraer_texto(pdf)
        plano = re.sub(r"\s+", " ", texto)
        print(f"\n{pdf.name}  ({pdf.stat().st_size:,} bytes)")
        print(f"  caracteres extraidos: {len(texto)}")
        if len(texto) < 200:
            print("  ❌ MUY POCO TEXTO: el PDF probablemente no es extraible")
            fallos += 1
            continue

        if pdf.name.startswith("factura_distinta"):
            continue

        faltantes = [e for e in ESPERADO if e not in plano]
        if faltantes:
            print(f"  ⚠️  no se encontraron: {faltantes}")
            fallos += 1
        else:
            print("  ✅ todos los datos clave son extraibles")

        print("  --- primeras 3 lineas ---")
        for linea in [l for l in texto.splitlines() if l.strip()][:3]:
            print(f"    {linea[:88]}")

    print()
    print("=" * 68)
    imagenes = sorted((RAIZ / "samples").glob("*.jpg"))
    for img in imagenes:
        print(f"Imagen: {img.name}  ({img.stat().st_size:,} bytes)")
    print("  (las imagenes NO tienen capa de texto: por eso requieren vision/OCR)")

    print()
    if fallos:
        print(f"RESULTADO: {fallos} problema(s) encontrado(s).")
        return 1
    print("RESULTADO: las facturas PDF tienen capa de texto correcta.")
    print("Content Understanding podra extraer los campos con alta confianza.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
