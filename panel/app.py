#!/usr/bin/env python3
"""Panel web de la Flashforge Creator 5 (estado, temperaturas, material, cámara, pausa/reanudar).

Pensado para la pestaña «Dispositivo» de OrcaSlicer (campo «Device UI» de la conexión de la
impresora), pero sirve en cualquier navegador de la red local. Corre en cualquier máquina con
Python 3.8+ que vea la impresora: una Raspberry Pi, tu ordenador, un NAS...

Usa las funciones de ../mcp/server.py y su configuración (~/.config/flashforge-mcp/config.json).
Solo deja pausar, reanudar y encender la luz: imprimir y cancelar no están en el panel.

Uso: python3 app.py [puerto]   (por defecto 8090)
"""
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp"))
import server as ff  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
PAGE = open(os.path.join(HERE, "index.html"), encoding="utf-8").read()


def status():
    d = ff.post_json("detail").get("detail", {})
    slots = (d.get("matlStationInfo") or {}).get("slotInfos") or []
    return {
        "status": d.get("status"),
        "file": d.get("printFileName"),
        "progress": d.get("printProgress"),
        "layer": d.get("printLayer"),
        "layers": d.get("targetPrintLayer"),
        "duration": d.get("printDuration"),
        "nozzles": d.get("nozzleTemps"),
        "nozzleTargets": d.get("nozzleTargetTemps"),
        "bed": d.get("platTemp"),
        "bedTarget": d.get("platTargetTemp"),
        "error": d.get("errorCode"),
        "light": d.get("lightStatus"),
        "slots": [{"id": s.get("slotId"), "material": s.get("materialName"),
                   "color": s.get("materialColor"), "loaded": s.get("hasFilament")} for s in slots],
        "camera": "/camera",
    }


class Camera:
    """Una sola conexión a la cámara, compartida por todos los que miran el panel.

    La cámara de la Creator 5 corta conexiones si se le abren varias a la vez, así que la Pi lee el
    vídeo una vez, guarda el último fotograma y lo reparte. Sin nadie mirando, suelta la conexión.
    """

    def __init__(self):
        self.frame, self.wanted, self.cond = None, 0.0, threading.Condition()
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        while True:
            if time.time() - self.wanted > 15:
                time.sleep(1)
                continue
            try:
                url = f"http://{ff.cfg()['host']}:8080/?action=stream"
                with urllib.request.urlopen(url, timeout=10) as up:
                    buf = b""
                    while time.time() - self.wanted < 15:
                        buf += up.read1(65536)
                        a = buf.find(b"\xff\xd8")
                        b = buf.find(b"\xff\xd9", a + 2) if a >= 0 else -1
                        if a >= 0 and b > 0:
                            with self.cond:
                                self.frame = buf[a:b + 2]
                                self.cond.notify_all()
                            buf = buf[b + 2:]
                        elif len(buf) > 2_000_000:
                            buf = b""
            except Exception:
                time.sleep(3)


cam = Camera()


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if self.path.startswith("/camera"):
            return self.camera()
        if self.path == "/api/status":
            try:
                return self.send(200, json.dumps(status()))
            except Exception as e:
                return self.send(502, json.dumps({"error": f"No responde la impresora: {e}"}))
        self.send(404, "{}")

    def camera(self):
        cam.wanted = time.time()
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        seen = None
        try:
            while True:
                cam.wanted = time.time()
                with cam.cond:
                    cam.cond.wait_for(lambda: cam.frame is not seen, timeout=10)
                    seen = cam.frame
                if seen is None:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(seen))
                self.wfile.write(seen + b"\r\n")
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def do_POST(self):
        acts = {"/api/pause": lambda: ff.t_job("pause"), "/api/continue": lambda: ff.t_job("continue"),
                "/api/light/on": lambda: ff.t_light(True), "/api/light/off": lambda: ff.t_light(False)}
        if self.path not in acts:
            return self.send(404, "{}")
        try:
            acts[self.path]()
            self.send(200, '{"ok": true}')
        except Exception as e:
            self.send(502, json.dumps({"error": str(e)}))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
