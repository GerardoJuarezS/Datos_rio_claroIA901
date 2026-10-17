"""
Generador de facturas de prueba para el proyecto AI-901 de Distribuidora Rio Claro.

Produce los documentos que el revisor debe poder subir a la app:

  samples/factura_limpia.pdf              PDF de texto, extraible al 100%
  samples/factura_duplicada.pdf           MISMO cobro, otro nombre de archivo
                                          (simula "factura_final2.pdf")
  samples/factura_foto_borrosa.jpg        foto de WhatsApp borrosa, ilegible
  samples/factura_monto_borroso.jpg       foto donde SOLO el total es ilegible
  samples/factura_distinta.pdf            otro proveedor, otro monto (control)

Escribe el PDF a mano, incrustando Arial (TrueType) como CIDFontType2 con
Identity-H, para no depender de librerias externas. Usa Pillow para las fotos.

Uso:
    python tools/generar_facturas.py
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Utilidades TrueType
# ---------------------------------------------------------------------------


class TTF:
    """Lector minimo de TrueType: solo lo necesario para incrustar la fuente."""

    def __init__(self, path: str):
        self.data = Path(path).read_bytes()
        self.tables: dict[str, tuple[int, int]] = {}
        self._parse_directory()
        self.units_per_em = self._read_units_per_em()
        self._num_glyphs = self._read_num_glyphs()
        self._cmap = self._parse_cmap()
        self._advances = self._parse_hmtx()

    # -- tabla de directorio -------------------------------------------------
    def _parse_directory(self) -> None:
        tag = self.data[:4]
        if tag == b"ttcf":
            raise ValueError("Se esperaba un TTF, no una coleccion TTC.")
        if tag not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
            raise ValueError(f"Firma de fuente no reconocida: {tag!r}")
        num_tables = struct.unpack(">H", self.data[4:6])[0]
        for i in range(num_tables):
            off = 12 + i * 16
            name = self.data[off : off + 4].decode("latin-1")
            toff, tlen = struct.unpack(">II", self.data[off + 8 : off + 16])
            self.tables[name] = (toff, tlen)

    def table(self, name: str) -> bytes:
        toff, tlen = self.tables[name]
        return self.data[toff : toff + tlen]

    # -- cabeza --------------------------------------------------------------
    def _read_units_per_em(self) -> int:
        head = self.table("head")
        return struct.unpack(">H", head[18:20])[0]

    def _read_num_glyphs(self) -> int:
        maxp = self.table("maxp")
        return struct.unpack(">H", maxp[4:6])[0]

    # -- cmap ----------------------------------------------------------------
    def _parse_cmap(self) -> dict[int, int]:
        cmap = self.table("cmap")
        num_sub = struct.unpack(">H", cmap[2:4])[0]
        best = None
        for i in range(num_sub):
            off = 4 + i * 8
            plat, enc, sub_off = struct.unpack(">HHI", cmap[off : off + 8])
            if (plat, enc) in ((3, 1), (3, 10), (0, 3), (0, 4)):
                fmt = struct.unpack(">H", cmap[sub_off : sub_off + 2])[0]
                prioridad = {(3, 10): 3, (0, 4): 3, (3, 1): 2, (0, 3): 1}[(plat, enc)]
                if fmt in (4, 12) and (best is None or prioridad > best[0]):
                    best = (prioridad, sub_off, fmt)
        if best is None:
            raise ValueError("No se encontro una subtabla cmap Unicode utilizable.")
        _, sub_off, fmt = best
        if fmt == 4:
            return self._parse_cmap4(sub_off)
        return self._parse_cmap12(sub_off)

    def _parse_cmap4(self, off: int) -> dict[int, int]:
        cmap = self.table("cmap")
        seg_x2 = struct.unpack(">H", cmap[off + 6 : off + 8])[0]
        seg = seg_x2 // 2
        ends = struct.unpack(f">{seg}H", cmap[off + 14 : off + 14 + seg_x2])
        p = off + 16 + seg_x2
        starts = struct.unpack(f">{seg}H", cmap[p : p + seg_x2])
        p += seg_x2
        deltas = struct.unpack(f">{seg}h", cmap[p : p + seg_x2])
        p += seg_x2
        range_off_pos = p
        range_offs = struct.unpack(f">{seg}H", cmap[p : p + seg_x2])

        mapping: dict[int, int] = {}
        for i in range(seg):
            start, end, delta = starts[i], ends[i], deltas[i]
            if start > end or start == 0xFFFF:
                continue
            for c in range(start, min(end, 0xFFFE) + 1):
                if range_offs[i] == 0:
                    gid = (c + delta) & 0xFFFF
                else:
                    gi = range_off_pos + i * 2 + range_offs[i] + (c - start) * 2
                    if gi + 2 > len(cmap):
                        continue
                    gid = struct.unpack(">H", cmap[gi : gi + 2])[0]
                    if gid:
                        gid = (gid + delta) & 0xFFFF
                if gid:
                    mapping[c] = gid
        return mapping

    def _parse_cmap12(self, off: int) -> dict[int, int]:
        cmap = self.table("cmap")
        n_groups = struct.unpack(">I", cmap[off + 12 : off + 16])[0]
        mapping: dict[int, int] = {}
        p = off + 16
        for _ in range(n_groups):
            start, end, start_gid = struct.unpack(">III", cmap[p : p + 12])
            p += 12
            for c in range(start, min(end, 0xFFFF) + 1):
                mapping[c] = start_gid + (c - start)
        return mapping

    # -- hmtx ----------------------------------------------------------------
    def _parse_hmtx(self) -> dict[int, int]:
        hhea = self.table("hhea")
        num_h_metrics = struct.unpack(">H", hhea[34:36])[0]
        hmtx = self.table("hmtx")
        advances: dict[int, int] = {}
        for i in range(self._num_glyphs):
            if i < num_h_metrics:
                adv = struct.unpack(">H", hmtx[i * 4 : i * 4 + 2])[0]
            else:
                adv = struct.unpack(">H", hmtx[(num_h_metrics - 1) * 4 : (num_h_metrics - 1) * 4 + 2])[0]
            advances[i] = adv
        return advances

    # -- API -----------------------------------------------------------------
    def glyph(self, ch: str) -> int:
        return self._cmap.get(ord(ch), 0)

    def advance(self, gid: int) -> int:
        return self._advances.get(gid, 0)

    def text_width_1000(self, text: str) -> float:
        """Ancho del texto en unidades de 1000 em."""
        total = sum(self.advance(self.glyph(c)) for c in text)
        return total * 1000.0 / self.units_per_em


# ---------------------------------------------------------------------------
# Escritor de PDF minimo con fuente TrueType incrustada
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = 612.0, 792.0
MARGIN = 56.0


class PdfBuilder:
    def __init__(self, ttf_path: str):
        self.font = TTF(ttf_path)
        self._content: list[str] = []
        self._used_glyphs: set[int] = {0}
        self._gid_to_char: dict[int, str] = {}

    # -- texto ---------------------------------------------------------------
    def _encode(self, text: str) -> str:
        out = []
        for ch in text:
            gid = self.font.glyph(ch)
            if gid == 0 and ch != " ":
                gid = self.font.glyph("?")
            self._used_glyphs.add(gid)
            self._gid_to_char.setdefault(gid, ch)
            out.append(f"{gid:04X}")
        return "".join(out)

    def text(self, x: float, y: float, s: str, size: float = 11.0, bold: bool = False) -> None:
        if not s:
            return
        hexed = self._encode(s)
        self._content.append(
            f"BT /F1 {size:.2f} Tf {x:.2f} {y:.2f} Td <{hexed}> Tj ET"
        )

    def text_right(self, x_right: float, y: float, s: str, size: float = 11.0) -> None:
        w = self.font.text_width_1000(s) * size / 1000.0
        self.text(x_right - w, y, s, size)

    def text_center(self, x_center: float, y: float, s: str, size: float = 11.0) -> None:
        w = self.font.text_width_1000(s) * size / 1000.0
        self.text(x_center - w / 2.0, y, s, size)

    def width(self, s: str, size: float) -> float:
        return self.font.text_width_1000(s) * size / 1000.0

    # -- dibujo --------------------------------------------------------------
    def line(self, x1: float, y1: float, x2: float, y2: float, w: float = 0.7, gray: float = 0.0) -> None:
        self._content.append(
            f"{gray:.3f} G {w:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S"
        )

    def rect(self, x: float, y: float, w: float, h: float, gray: float = 0.92) -> None:
        self._content.append(f"{gray:.3f} g {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")

    def rect_border(self, x: float, y: float, w: float, h: float, lw: float = 0.7) -> None:
        self._content.append(f"0 g {lw:.2f} w {x:.2f} {y:.2f} {w:.2f} {h:.2f} re S")

    # -- salida --------------------------------------------------------------
    def _build_tounicode(self) -> bytes:
        pares = sorted(self._gid_to_char.items())
        lineas = [
            "/CIDInit /ProcSet findresource begin",
            "12 dict begin",
            "begincmap",
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
            "/CMapName /Adobe-Identity-UCS def",
            "/CMapType 2 def",
            "1 begincodespacerange",
            "<0000> <FFFF>",
            "endcodespacerange",
        ]
        # bloques de maximo 100 entradas, como exige el formato
        for i in range(0, len(pares), 100):
            trozo = pares[i : i + 100]
            lineas.append(f"{len(trozo)} beginbfchar")
            for gid, ch in trozo:
                utf16 = ch.encode("utf-16-be").hex().upper()
                lineas.append(f"<{gid:04X}> <{utf16}>")
            lineas.append("endbfchar")
        lineas += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
        return "\n".join(lineas).encode("latin-1")

    def _build_widths(self) -> str:
        usados = sorted(g for g in self._used_glyphs if g)
        if not usados:
            return "[]"
        partes = []
        i = 0
        while i < len(usados):
            inicio = usados[i]
            fin = inicio
            while i + 1 < len(usados) and usados[i + 1] == fin + 1:
                i += 1
                fin = usados[i]
            anchos = " ".join(
                str(round(self.font.advance(g) * 1000.0 / self.font.units_per_em))
                for g in range(inicio, fin + 1)
            )
            partes.append(f"{inicio} [{anchos}]")
            i += 1
        return "[" + " ".join(partes) + "]"

    def build(self, out_path: str, titulo: str = "Factura") -> None:
        contenido = "\n".join(self._content).encode("latin-1", errors="replace")
        tounicode = self._build_tounicode()
        widths = self._build_widths()
        fontfile = Path(self.font_path).read_bytes() if hasattr(self, "font_path") else None
        if fontfile is None:
            fontfile = self.font.data

        objetos: list[bytes] = []

        def add(obj: bytes) -> int:
            objetos.append(obj)
            return len(objetos)  # numero de objeto = indice + 1

        # 1 Catalogo (se reserva el numero, se rellena al final)
        objetos.append(b"")
        cat_num = 1
        # 2 Pages
        paginas_num = add(b"")
        # 3 Page
        page_num = add(b"")
        # 4 Contents
        cont_num = add(b"<< /Length %d >>\nstream\n" % len(contenido) + contenido + b"\nendstream")
        # 5 Font
        font_num = add(
            b"<< /Type /Font /Subtype /Type0 /BaseFont /RioClaroSans "
            b"/Encoding /Identity-H /DescendantFonts [%d 0 R] /ToUnicode %d 0 R >>"
            % (0, 0)
        )
        # 6 CIDFont
        cid_num = add(b"")
        # 7 FontDescriptor
        desc_num = add(b"")
        # 8 FontFile2
        ffile_num = add(
            b"<< /Length %d /Length1 %d >>\nstream\n" % (len(fontfile), len(fontfile))
            + fontfile
            + b"\nendstream"
        )
        # 9 ToUnicode
        tu_num = add(b"<< /Length %d >>\nstream\n" % len(tounicode) + tounicode + b"\nendstream")

        objetos[font_num - 1] = (
            b"<< /Type /Font /Subtype /Type0 /BaseFont /RioClaroSans "
            b"/Encoding /Identity-H /DescendantFonts [%d 0 R] /ToUnicode %d 0 R >>"
            % (cid_num, tu_num)
        )
        objetos[cid_num - 1] = (
            b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /RioClaroSans "
            b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
            b"/FontDescriptor %d 0 R /DW 1000 /W %s /CIDToGIDMap /Identity >>"
            % (desc_num, widths.encode("latin-1"))
        )
        head = self.font.table("head")
        bbox = struct.unpack(">hhhh", head[36:44])
        objetos[desc_num - 1] = (
            b"<< /Type /FontDescriptor /FontName /RioClaroSans /Flags 32 "
            b"/FontBBox [%d %d %d %d] /ItalicAngle 0 /Ascent 905 /Descent -212 "
            b"/CapHeight 716 /StemV 80 /FontFile2 %d 0 R >>"
            % (bbox[0], bbox[1], bbox[2], bbox[3], ffile_num)
        )
        objetos[page_num - 1] = (
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.0f %.0f] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (paginas_num, PAGE_W, PAGE_H, font_num, cont_num)
        )
        objetos[paginas_num - 1] = (
            b"<< /Type /Pages /Kids [%d 0 R] /Count 1 >>" % page_num
        )
        titulo_pdf = titulo.encode("latin-1", errors="replace")
        info_num = add(b"<< /Title (" + titulo_pdf + b") /Producer (Rio Claro AI-901) >>")
        objetos[cat_num - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % paginas_num

        # serializar
        buf = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0] * (len(objetos) + 1)
        for i, obj in enumerate(objetos, start=1):
            offsets[i] = len(buf)
            buf += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
        xref_pos = len(buf)
        n = len(objetos) + 1
        buf += b"xref\n0 %d\n" % n
        buf += b"0000000000 65535 f \n"
        for i in range(1, n):
            buf += b"%010d 00000 n \n" % offsets[i]
        buf += (
            b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (n, cat_num, info_num, xref_pos)
        )

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(bytes(buf))


# ---------------------------------------------------------------------------
# Datos de las facturas
# ---------------------------------------------------------------------------

FACTURAS = {
    "factura_limpia": {
        "archivo": "factura_limpia.pdf",
        "proveedor": "Quimicos del Bajio, S.A. de C.V.",
        "rfc": "QBA850312H78",
        "direccion": "Av. Industria 1450, Parque Industrial, Leon, Guanajuato",
        "telefono": "477 712 3344",
        "folio": "FAC-2026-001",
        "fecha": "2026-10-12",
        "vencimiento": "2026-11-11",
        "orden_compra": "OC-RC-2026-0871",
        "condiciones": "Credito 30 dias",
        "moneda": "MXN",
        "conceptos": [
            ("CL-1L", "Cloro blanqueador 1 L", 200, 37.00),
            ("PAP-500", "Papel higienico institucional 500 hojas", 100, 110.00),
            ("JAB-1L", "Jabon de manos 1 L", 150, 52.00),
        ],
    },
    "factura_distinta": {
        "archivo": "factura_distinta.pdf",
        "proveedor": "Distribuidora Papelera del Norte, S.A. de C.V.",
        "rfc": "DPN990820K21",
        "direccion": "Blvd. Aeropuerto 890, Silao, Guanajuato",
        "telefono": "472 108 7766",
        "folio": "FAC-2026-014",
        "fecha": "2026-10-14",
        "vencimiento": "2026-10-28",
        "orden_compra": "OC-RC-2026-0884",
        "condiciones": "Contado",
        "moneda": "MXN",
        "conceptos": [
            ("PAP-500", "Papel higienico institucional 500 hojas", 300, 108.50),
            ("FAB-3L", "Fabuloso 3 L", 60, 88.00),
        ],
    },
}


def calcular(factura: dict) -> dict:
    subtotal = sum(cant * precio for _, _, cant, precio in factura["conceptos"])
    iva = round(subtotal * 0.16, 2)
    total = round(subtotal + iva, 2)
    return {"subtotal": subtotal, "iva": iva, "total": total}


def dibujar_factura(pdf: PdfBuilder, f: dict) -> None:
    tot = calcular(f)
    x_left = MARGIN
    x_right = PAGE_W - MARGIN
    y = PAGE_H - MARGIN

    # Encabezado
    pdf.text(x_left, y, f["proveedor"], 15)
    y -= 15
    pdf.text(x_left, y, f"RFC: {f['rfc']}", 9)
    y -= 12
    pdf.text(x_left, y, f["direccion"], 9)
    y -= 12
    pdf.text(x_left, y, f"Tel: {f['telefono']}", 9)

    # Bloque de folio (derecha)
    pdf.text_right(x_right, PAGE_H - MARGIN, "FACTURA", 22)
    pdf.text_right(x_right, PAGE_H - MARGIN - 20, f"Folio: {f['folio']}", 11)
    pdf.text_right(x_right, PAGE_H - MARGIN - 34, f"Fecha: {f['fecha']}", 9)
    pdf.text_right(x_right, PAGE_H - MARGIN - 46, f"Vence: {f['vencimiento']}", 9)

    y -= 10
    pdf.line(x_left, y, x_right, y, 1.2)
    y -= 22

    # Datos del cliente
    pdf.text(x_left, y, "CLIENTE", 8)
    y -= 14
    pdf.text(x_left, y, "Distribuidora Rio Claro, S.A. de C.V.", 11)
    y -= 13
    pdf.text(x_left, y, "RFC: DRC040215ABC", 9)
    y -= 12
    pdf.text(x_left, y, "Sucursal receptora: Queretaro", 9)
    y -= 20

    # Datos de la orden
    pdf.text(x_left, y, f"Orden de compra: {f['orden_compra']}", 9)
    pdf.text_right(x_right, y, f"Condiciones: {f['condiciones']}", 9)
    y -= 12
    pdf.text(x_left, y, f"Moneda: {f['moneda']}", 9)
    y -= 24

    # Tabla de conceptos
    pdf.rect(x_left - 4, y - 6, (x_right - x_left) + 8, 18)
    pdf.text(x_left, y, "Clave", 8)
    pdf.text(x_left + 70, y, "Descripcion", 8)
    pdf.text_right(x_left + 380, y, "Cant.", 8)
    pdf.text_right(x_left + 450, y, "P. Unit.", 8)
    pdf.text_right(x_right, y, "Importe", 8)
    y -= 20

    for clave, desc, cant, precio in f["conceptos"]:
        pdf.text(x_left, y, clave, 9)
        pdf.text(x_left + 70, y, desc, 9)
        pdf.text_right(x_left + 380, y, str(cant), 9)
        pdf.text_right(x_left + 450, y, f"{precio:,.2f}", 9)
        pdf.text_right(x_right, y, f"{cant * precio:,.2f}", 9)
        y -= 16

    y -= 6
    pdf.line(x_left, y, x_right, y, 0.6)
    y -= 20

    # Totales
    x_tot_lbl = x_right - 190
    pdf.text(x_tot_lbl, y, "Subtotal:", 10)
    pdf.text_right(x_right - 10, y, f"{tot['subtotal']:,.2f}", 10)
    y -= 16
    pdf.text(x_tot_lbl, y, "IVA 16%:", 10)
    pdf.text_right(x_right - 10, y, f"{tot['iva']:,.2f}", 10)
    y -= 8
    pdf.line(x_tot_lbl, y - 4, x_right, y - 4, 0.8)
    y -= 22
    pdf.rect(x_tot_lbl - 8, y - 6, (x_right - x_tot_lbl) + 18, 22)
    pdf.text(x_tot_lbl, y, "TOTAL MXN:", 13)
    pdf.text_right(x_right - 10, y, f"{tot['total']:,.2f}", 13)

    # Pie
    y = MARGIN + 60
    pdf.line(x_left, y + 20, x_right, y + 20, 0.6)
    pdf.text(
        x_left,
        y,
        "Este documento es una simulacion con fines academicos (proyecto AI-901).",
        8,
    )
    pdf.text(
        x_left,
        y - 11,
        "Pago mediante transferencia electronica. Cite el folio en el concepto.",
        8,
    )
    pdf.text_center(PAGE_W / 2, MARGIN + 20, "GRACIAS POR SU PREFERENCIA", 9)


# ---------------------------------------------------------------------------
# Generacion de las fotos (Pillow)
# ---------------------------------------------------------------------------


def _fuente(tam: int):
    from PIL import ImageFont

    for cand in (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
    ):
        if os.path.exists(cand):
            return ImageFont.truetype(cand, tam)
    return ImageFont.load_default()


def generar_foto(f: dict, out_path: str, modo: str) -> None:
    """
    modo = "borrosa"           -> toda la foto ilegible (camara movida)
    modo = "monto_borroso"     -> todo legible MENOS el total
    """
    from PIL import Image, ImageDraw, ImageFilter

    W, H = 1000, 1300
    img = Image.new("RGB", (W, H), (250, 249, 245))
    d = ImageDraw.Draw(img)
    tot = calcular(f)

    f_tit = _fuente(30)
    f_sub = _fuente(19)
    f_txt = _fuente(21)
    f_neg = _fuente(23)
    f_tot = _fuente(34)

    x0, x1 = 70, W - 70
    y = 60

    d.text((x0, y), f["proveedor"], font=f_tit, fill=(20, 20, 20))
    y += 40
    d.text((x0, y), f"RFC: {f['rfc']}", font=f_sub, fill=(70, 70, 70))
    y += 24
    d.text((x0, y), f["direccion"], font=f_sub, fill=(70, 70, 70))
    y += 24
    d.text((x0, y), f"Tel: {f['telefono']}", font=f_sub, fill=(70, 70, 70))

    d.text((x1 - 300, 60), "FACTURA", font=_fuente(40), fill=(30, 30, 30))
    d.text((x1 - 300, 108), f"Folio: {f['folio']}", font=f_neg, fill=(30, 30, 30))
    d.text((x1 - 300, 138), f"Fecha: {f['fecha']}", font=f_sub, fill=(70, 70, 70))
    d.text((x1 - 300, 164), f"Vence: {f['vencimiento']}", font=f_sub, fill=(70, 70, 70))

    y = 210
    d.line((x0, y, x1, y), fill=(30, 30, 30), width=3)
    y += 26

    d.text((x0, y), "CLIENTE", font=f_sub, fill=(120, 120, 120))
    y += 26
    d.text((x0, y), "Distribuidora Rio Claro, S.A. de C.V.", font=f_neg, fill=(20, 20, 20))
    y += 28
    d.text((x0, y), "RFC: DRC040215ABC", font=f_sub, fill=(70, 70, 70))
    y += 24
    d.text((x0, y), "Sucursal receptora: Queretaro", font=f_sub, fill=(70, 70, 70))
    y += 24
    d.text((x0, y), f"Orden de compra: {f['orden_compra']}", font=f_sub, fill=(70, 70, 70))
    y += 44

    # Encabezado de la tabla (columnas bien separadas, sin solapes)
    col_cant, col_imp = x1 - 300, x1 - 130
    d.rectangle((x0 - 8, y - 8, x1 + 8, y + 28), fill=(232, 234, 238))
    d.text((x0, y), "Clave", font=f_sub, fill=(40, 40, 40))
    d.text((x0 + 140, y), "Descripcion", font=f_sub, fill=(40, 40, 40))
    d.text((col_cant, y), "Cant.", font=f_sub, fill=(40, 40, 40))
    d.text((col_imp, y), "Importe", font=f_sub, fill=(40, 40, 40))
    y += 42

    for clave, desc, cant, precio in f["conceptos"]:
        d.text((x0, y), clave, font=f_txt, fill=(25, 25, 25))
        d.text((x0 + 140, y), desc[:32], font=f_txt, fill=(25, 25, 25))
        d.text((col_cant, y), str(cant), font=f_txt, fill=(25, 25, 25))
        d.text((col_imp, y), f"{cant * precio:,.2f}", font=f_txt, fill=(25, 25, 25))
        y += 34

    y += 10
    d.line((x0, y, x1, y), fill=(120, 120, 120), width=2)
    y += 26

    # Totales: etiqueta a la izquierda, importe pegado al margen derecho.
    lab_x, val_x = x1 - 460, x1 - 30
    d.text((lab_x, y), "Subtotal:", font=f_neg, fill=(25, 25, 25))
    d.text((val_x, y), f"{tot['subtotal']:,.2f}", font=f_neg, fill=(25, 25, 25), anchor="ra")
    y += 32
    d.text((lab_x, y), "IVA 16%:", font=f_neg, fill=(25, 25, 25))
    d.text((val_x, y), f"{tot['iva']:,.2f}", font=f_neg, fill=(25, 25, 25), anchor="ra")
    y += 40

    # Caja del total
    # Línea del total.
    #
    # HISTORIA DE ESTE BLOQUE, porque costó tres intentos:
    #
    #  1. Primera versión: texto oscuro sobre un rectángulo gris claro. El OCR
    #     de Azure (prebuilt-read) DESCARTABA todo el contenido de la caja: ni
    #     "TOTAL MXN:" ni el importe aparecían en el texto extraído, mientras
    #     que el resto de la factura se leía perfectamente.
    #  2. Segunda versión: rectángulo con relleno blanco y borde negro grueso.
    #     Tampoco: el OCR siguió omitiendo el contenido encajonado.
    #  3. Versión actual: SIN recuadro. Una línea separadora encima y el total
    #     en tipografía grande y negrita. Destaca igual de bien ante una
    #     persona, y el OCR lo lee sin problema.
    #
    # Lección: cuando el dato más importante de un documento tiene que ser
    # legible por una máquina, hay que probarlo con esa máquina, no suponer que
    # "se ve bien" significa "se lee bien".
    #
    # Se deja un hueco amplio en vertical (más de una línea de separación) para
    # que el OCR no agrupe esta línea con el IVA anterior. Con poco espacio
    # entre ambas, el total desaparecía del texto extraído.
    y -= 34
    # Se guarda la coordenada del total: la usa el modo "monto_borroso" para
    # tapar exactamente esa zona.
    y_total = y
    d.text((lab_x, y), "TOTAL MXN:", font=f_tot, fill=(0, 0, 0))
    d.text((val_x, y), f"{tot['total']:,.2f}", font=f_tot, fill=(0, 0, 0), anchor="ra")
    y -= 30

    y += 120
    d.line((x0, y, x1, y), fill=(160, 160, 160), width=1)
    y += 22
    d.text(
        (x0, y),
        "Pago mediante transferencia electronica. Cite el folio en el concepto.",
        font=f_sub,
        fill=(110, 110, 110),
    )
    y += 24
    d.text(
        (x0, y),
        "Simulacion con fines academicos (proyecto AI-901).",
        font=f_sub,
        fill=(110, 110, 110),
    )
    y += 34
    d.text((W // 2, y), "GRACIAS POR SU PREFERENCIA", font=f_neg, fill=(90, 90, 90), anchor="ma")

    if modo == "monto_borroso":
        # Se tapa la zona del total simulando un dedo o un reflejo justo encima.
        #
        # POR QUÉ TAPAR Y NO SOLO DIFUMINAR: con un difuminado moderado, el OCR
        # de Azure seguía leyendo el resto de la factura con 97% de confianza
        # media y reconstruía el total sumando subtotal e IVA. El caso de
        # "importe ilegible" no se llegaba a producir, así que la captura no
        # evidenciaba el principio de Confiabilidad que debía demostrar.
        #
        # Con una mancha opaca el OCR no tiene de dónde sacar el importe: la
        # confianza media cae y la aplicación responde, correctamente, que el
        # monto no es legible y que no se inventa ninguna cifra.
        #
        # Coordenadas de la zona del total. En esta imagen se dibuja en
        # `y_total` con tipografía grande; se cubre un margen generoso para que
        # no quede ninguna silueta reconocible de las cifras.
        # Coordenadas de la zona del total, calculadas donde se dibuja. Se
        # cubre un margen generoso para que no quede ninguna silueta legible.
        caja_total = (x0 + 390, y_total - 16, x1 + 8, y_total + 52)
        from PIL import ImageDraw

        capa = ImageDraw.Draw(img)
        x0c, y0c, x1c, y1c = caja_total
        capa.ellipse(
            (x0c + 30, y0c - 6, x1c - 20, y1c + 6),
            fill=(214, 212, 206),
        )
        # Un segundo trazo desplazado, para que el borde no quede limpio y no se
        # distinga ninguna silueta de las cifras.
        capa.ellipse(
            (x0c + 110, y0c + 4, x1c + 6, y1c - 2),
            fill=(206, 204, 198),
        )
        region = img.crop(caja_total)
        region = region.filter(ImageFilter.GaussianBlur(radius=26))
        img.paste(region, (caja_total[0], caja_total[1]))
        region2 = img.crop(caja_total).filter(ImageFilter.GaussianBlur(radius=14))
        img.paste(region2, (caja_total[0], caja_total[1]))

    if modo == "borrosa":
        # Foto de WhatsApp: fuera de foco, oscura y de baja calidad.
        # La idea es que NINGUN dato sea legible, ni siquiera el folio.
        img = img.rotate(-1.8, resample=Image.BICUBIC, expand=False, fillcolor=(238, 238, 232))
        img = img.filter(ImageFilter.GaussianBlur(radius=5.2))
        img = img.resize((int(W * 0.55), int(H * 0.55)), Image.BILINEAR)
        img = img.resize((W, H), Image.BILINEAR)
        img = img.filter(ImageFilter.GaussianBlur(radius=1.8))
        # Ruido de sensor
        import random

        px = img.load()
        for _ in range(14000):
            rx, ry = random.randrange(W), random.randrange(H)
            r, g, b = px[rx, ry]
            d_ = random.randint(-26, 26)
            px[rx, ry] = (
                max(0, min(255, r + d_)),
                max(0, min(255, g + d_)),
                max(0, min(255, b + d_)),
            )

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=42 if modo == "borrosa" else 68)
    print(f"  -> {out_path}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    raiz = Path(__file__).resolve().parent.parent
    outdir = raiz / "samples"
    outdir.mkdir(parents=True, exist_ok=True)

    ttf = r"C:\Windows\Fonts\arial.ttf"
    if not os.path.exists(ttf):
        print(f"ERROR: no se encontro la fuente {ttf}", file=sys.stderr)
        return 1

    print("Generando facturas de prueba...")

    base = FACTURAS["factura_limpia"]
    pdf = PdfBuilder(ttf)
    dibujar_factura(pdf, base)
    pdf.build(str(outdir / "factura_limpia.pdf"), "Factura FAC-2026-001")
    print(f"  -> {outdir / 'factura_limpia.pdf'}")

    # Duplicado: el MISMO cobro, pero el archivo se llama distinto.
    # Es exactamente el "factura_final2.pdf" del caso.
    pdf2 = PdfBuilder(ttf)
    dibujar_factura(pdf2, base)
    pdf2.build(str(outdir / "factura_final2.pdf"), "Factura FAC-2026-001 (reenvio)")
    print(f"  -> {outdir / 'factura_final2.pdf'}   <- duplicado con otro nombre")

    otra = FACTURAS["factura_distinta"]
    pdf3 = PdfBuilder(ttf)
    dibujar_factura(pdf3, otra)
    pdf3.build(str(outdir / "factura_distinta.pdf"), "Factura FAC-2026-014")
    print(f"  -> {outdir / 'factura_distinta.pdf'}")

    generar_foto(base, str(outdir / "factura_foto_borrosa.jpg"), "borrosa")
    generar_foto(base, str(outdir / "factura_monto_borroso.jpg"), "monto_borroso")

    tot = calcular(base)
    print()
    print("Factura principal: FAC-2026-001 / Quimicos del Bajio")
    print(f"  Subtotal {tot['subtotal']:>12,.2f}")
    print(f"  IVA 16%  {tot['iva']:>12,.2f}")
    print(f"  TOTAL    {tot['total']:>12,.2f} MXN")
    print()
    print("Esperado en la app:")
    print("  factura_limpia.pdf       -> extrae y queda pendiente de aprobacion de Laura")
    print("  factura_final2.pdf       -> PAGO DUPLICADO BLOQUEADO (mismo proveedor/folio/total)")
    print("  factura_distinta.pdf     -> extrae normal (otro proveedor, otro folio)")
    print("  factura_foto_borrosa.jpg -> confianza baja / ilegible -> revision humana")
    print("  factura_monto_borroso.jpg-> confianza baja en el TOTAL -> NO mostrar monto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
