"""
Capturador de pantallas del portal Río Claro usando el protocolo CDP de Edge.

Streamlit no es una página estática: la interfaz se dibuja cuando el WebSocket
se conecta. Por eso una captura con --screenshot simple sale en blanco. Este
script:

  1. Arranca Edge en modo headless con depuración remota.
  2. Se conecta por WebSocket al protocolo DevTools (CDP).
  3. Navega a la URL y espera a que el DOM tenga contenido real.
  4. Recorre las pestañas haciendo clic y captura cada una.

Usa solo la biblioteca estándar (urllib + websocket-client si está, o un
cliente WebSocket mínimo propio).

Uso:
    python tools/capturar_pantallas.py --url http://127.0.0.1:8899
    python tools/capturar_pantallas.py --url https://mi-app.azurewebsites.net
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "docs" / "capturas"

RUTAS_EDGE = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def encontrar_navegador() -> str:
    for ruta in RUTAS_EDGE:
        if os.path.exists(ruta):
            return ruta
    for nombre in ("msedge", "google-chrome", "chromium", "chrome"):
        encontrado = shutil.which(nombre)
        if encontrado:
            return encontrado
    raise SystemExit(
        "ERROR: no se encontró ningún navegador basado en Chromium.\n"
        "Instale Microsoft Edge o Google Chrome, o capture las pantallas a mano."
    )


# ---------------------------------------------------------------------------
# Cliente WebSocket mínimo (RFC 6455), sin dependencias externas
# ---------------------------------------------------------------------------


class WebSocket:
    def __init__(self, url: str, timeout: float = 30.0):
        # ws://host:puerto/ruta
        resto = url.split("://", 1)[1]
        hostpuerto, _, ruta = resto.partition("/")
        host, _, puerto = hostpuerto.partition(":")
        self.host = host
        self.puerto = int(puerto or 80)
        self.ruta = "/" + ruta
        self.sock = socket.create_connection((self.host, self.puerto), timeout=timeout)
        self.sock.settimeout(timeout)
        self._handshake()

    def _handshake(self) -> None:
        clave = base64.b64encode(os.urandom(16)).decode()
        peticion = (
            f"GET {self.ruta} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.puerto}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {clave}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.sock.sendall(peticion.encode())
        respuesta = b""
        while b"\r\n\r\n" not in respuesta:
            trozo = self.sock.recv(4096)
            if not trozo:
                raise ConnectionError("El navegador cerró la conexión en el handshake.")
            respuesta += trozo
            if len(respuesta) > 65536:
                raise ConnectionError("Respuesta de handshake demasiado grande.")
        if b"101" not in respuesta.split(b"\r\n")[0]:
            raise ConnectionError(f"Handshake rechazado: {respuesta[:200]!r}")

    def _enviar_frame(self, datos: bytes, opcode: int = 0x1) -> None:
        """Envía un frame de texto, enmascarado como exige el protocolo."""
        cabecera = bytearray()
        cabecera.append(0x80 | opcode)
        n = len(datos)
        mascara = os.urandom(4)
        if n < 126:
            cabecera.append(0x80 | n)
        elif n < 65536:
            cabecera.append(0x80 | 126)
            cabecera += struct.pack(">H", n)
        else:
            cabecera.append(0x80 | 127)
            cabecera += struct.pack(">Q", n)
        cabecera += mascara
        enmascarado = bytes(b ^ mascara[i % 4] for i, b in enumerate(datos))
        self.sock.sendall(bytes(cabecera) + enmascarado)

    def _leer_exacto(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            trozo = self.sock.recv(n - len(buf))
            if not trozo:
                raise ConnectionError("Conexión cerrada mientras se leía.")
            buf += trozo
        return buf

    def _leer_frame(self) -> tuple[int, bytes]:
        b1, b2 = self._leer_exacto(2)
        opcode = b1 & 0x0F
        enmascarado = bool(b2 & 0x80)
        longitud = b2 & 0x7F
        if longitud == 126:
            longitud = struct.unpack(">H", self._leer_exacto(2))[0]
        elif longitud == 127:
            longitud = struct.unpack(">Q", self._leer_exacto(8))[0]
        mascara = self._leer_exacto(4) if enmascarado else b""
        carga = self._leer_exacto(longitud)
        if enmascarado:
            carga = bytes(b ^ mascara[i % 4] for i, b in enumerate(carga))
        return opcode, carga

    def enviar(self, mensaje: dict) -> None:
        self._enviar_frame(json.dumps(mensaje).encode())

    def recibir(self, timeout: float | None = None) -> dict:
        if timeout is not None:
            self.sock.settimeout(timeout)
        while True:
            opcode, carga = self._leer_frame()
            if opcode == 0x1:  # texto
                return json.loads(carga.decode())
            if opcode == 0x8:  # cierre
                raise ConnectionError("El navegador cerró el WebSocket.")
            # 0x9 ping -> responder pong; 0xA pong; 0x0 continuación: se ignora

    def cerrar(self) -> None:
        try:
            self._enviar_frame(b"", opcode=0x8)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Controlador CDP
# ---------------------------------------------------------------------------


class Navegador:
    def __init__(self, ejecutable: str, ancho: int = 1500, alto: int = 1500):
        self.perfil = tempfile.mkdtemp(prefix="rio-claro-edge-")
        self.ancho = ancho
        self.alto = alto
        self.proceso = subprocess.Popen(
            [
                ejecutable,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                f"--window-size={ancho},{alto}",
                "--remote-debugging-port=0",
                f"--user-data-dir={self.perfil}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.puerto = self._esperar_puerto()
        self.ws = self._conectar_pagina()
        self._contador = 0

    def _esperar_puerto(self, limite: float = 40.0) -> int:
        archivo = Path(self.perfil) / "DevToolsActivePort"
        inicio = time.time()
        while time.time() - inicio < limite:
            if archivo.exists():
                lineas = archivo.read_text().splitlines()
                if lineas and lineas[0].strip().isdigit():
                    return int(lineas[0].strip())
            if self.proceso.poll() is not None:
                raise SystemExit("El navegador terminó antes de abrir el puerto de depuración.")
            time.sleep(0.3)
        raise SystemExit("No se pudo abrir el puerto de depuración de DevTools.")

    def _conectar_pagina(self) -> WebSocket:
        """Se conecta al destino de tipo 'page'."""
        inicio = time.time()
        while time.time() - inicio < 30:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.puerto}/json/list", timeout=5
                ) as r:
                    destinos = json.loads(r.read().decode())
                paginas = [d for d in destinos if d.get("type") == "page"]
                if paginas:
                    return WebSocket(paginas[0]["webSocketDebuggerUrl"])
            except Exception:
                pass
            time.sleep(0.4)
        raise SystemExit("No se encontró ninguna página a la que conectarse.")

    def enviar(self, metodo: str, **params):
        self._contador += 1
        ident = self._contador
        self.ws.enviar({"id": ident, "method": metodo, "params": params})
        while True:
            mensaje = self.ws.recibir(timeout=60)
            if mensaje.get("id") == ident:
                if "error" in mensaje:
                    raise RuntimeError(f"{metodo}: {mensaje['error']}")
                return mensaje.get("result", {})

    def evaluar(self, expresion: str):
        resultado = self.enviar(
            "Runtime.evaluate",
            expression=expresion,
            returnByValue=True,
            awaitPromise=True,
        )
        return resultado.get("result", {}).get("value")

    def navegar(self, url: str) -> None:
        self.enviar("Page.enable")
        self.enviar("Runtime.enable")
        self.enviar("Page.navigate", url=url)

    def esperar_texto(self, timeout: float = 45.0) -> bool:
        """Espera a que Streamlit haya dibujado contenido real."""
        inicio = time.time()
        while time.time() - inicio < timeout:
            try:
                texto = self.evaluar(
                    "document.body ? document.body.innerText.length : 0"
                )
                if texto and texto > 400:
                    # además, que no queden esqueletos de carga
                    ocupado = self.evaluar(
                        "document.querySelectorAll('[data-testid=\"stSkeleton\"]').length"
                    )
                    if not ocupado:
                        return True
            except Exception:
                pass
            time.sleep(0.6)
        return False

    def capturar(self, ruta: Path, espera: float = 1.5) -> None:
        """
        Captura SOLO el viewport.

        Importante: captureBeyondViewport=True desplaza el recorte cuando hay
        un contenedor con overflow (Streamlit usa uno para el área principal),
        y el resultado sale desalineado: la barra lateral queda cortada y
        aparece una franja vacía. Por eso se captura el viewport tal cual y se
        usa una ventana alta para que quepa el contenido.
        """
        time.sleep(espera)
        resultado = self.enviar(
            "Page.captureScreenshot",
            format="png",
            captureBeyondViewport=False,
            fromSurface=True,
        )
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(base64.b64decode(resultado["data"]))

    def clic_por_texto(self, texto: str) -> bool:
        """
        Hace clic en la pestaña cuyo texto coincida.

        Streamlit usa botones con role='tab'. Se busca por texto exacto
        contenido, que es lo más estable entre versiones.
        """
        expresion = """
        (() => {
          const buscar = %s;
          const nodos = Array.from(document.querySelectorAll('button[role="tab"], [role="tab"], button'));
          const objetivo = nodos.find(n => (n.innerText || '').replace(/\\s+/g,' ').trim().includes(buscar));
          if (!objetivo) return false;
          objetivo.click();
          return true;
        })()
        """ % json.dumps(texto)
        return bool(self.evaluar(expresion))

    def cerrar(self) -> None:
        try:
            self.ws.cerrar()
        except Exception:
            pass
        try:
            self.proceso.terminate()
            self.proceso.wait(timeout=10)
        except Exception:
            try:
                self.proceso.kill()
            except Exception:
                pass
        shutil.rmtree(self.perfil, ignore_errors=True)


# ---------------------------------------------------------------------------
# Guion de capturas
# ---------------------------------------------------------------------------

PESTANAS = [
    ("1_asistente", "1. Asistente"),
    ("2_facturas", "2. Facturas"),
    ("3_quejas", "3. Quejas"),
    ("4_voz_vision", "4. Voz y visión"),
    ("5_reporte", "5. Reporte y seguridad"),
    ("6_ia_responsable", "6. IA responsable"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Captura de pantallas del portal")
    parser.add_argument("--url", default="http://127.0.0.1:8899", help="URL de la app")
    parser.add_argument("--ancho", type=int, default=1500)
    parser.add_argument("--alto", type=int, default=1500)
    args = parser.parse_args()

    ejecutable = encontrar_navegador()
    print(f"Navegador: {ejecutable}")
    print(f"URL: {args.url}")
    print(f"Destino: {DESTINO}")
    print()

    navegador = Navegador(ejecutable, args.ancho, args.alto)
    try:
        n = 0
        print("Navegando y esperando a que la interfaz se dibuje…")
        navegador.navegar(args.url)
        if not navegador.esperar_texto():
            print("AVISO: la interfaz no terminó de dibujarse en el tiempo previsto.")
            print("       Puede que la app no esté corriendo o tarde en responder.")

        titulo = navegador.evaluar("document.title")
        print(f"Título de la página: {titulo!r}")

        for indice, (archivo, etiqueta) in enumerate(PESTANAS):
            if indice > 0:
                if not navegador.clic_por_texto(etiqueta):
                    print(f"  AVISO: no se encontró la pestaña '{etiqueta}'")
                    continue
                time.sleep(2.0)
            destino = DESTINO / f"{indice + 1:02d}_{archivo}.png"
            navegador.capturar(destino)
            n += 1
            print(f"  capturada: {destino.name}")

        print()
        print(f"Listo: {n} capturas en {DESTINO}")
        print("Revíselas y reemplácelas por las de su propia ejecución con Azure")
        print("conectado antes de subirlas al documento de entrega.")
        return 0
    finally:
        navegador.cerrar()


if __name__ == "__main__":
    raise SystemExit(main())
