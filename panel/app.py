#!/usr/bin/env python3
"""Panel web de la Flashforge Creator 5 para la pestaña «Dispositivo» de OrcaSlicer (campo
«Device UI» de la conexión de la impresora); sirve también en cualquier navegador de la red local.

Corre en cualquier máquina con Python 3.8+ que vea la impresora (una Raspberry Pi, tu ordenador, un
NAS...) y usa las funciones de ../mcp/server.py. Muestra estado, temperaturas (con gráfica), material
de cada cabezal, cámara y archivos; deja pausar, reanudar, cambiar la velocidad, encender la luz e
imprimir un archivo de la impresora (con confirmación de placa vacía). Cancelar no.
Avisa al móvil (ntfy o Telegram) al terminar, pausarse o dar error, aunque nadie mire el panel.

Uso: python3 app.py [puerto]   (por defecto 8090)
Configuración: la del MCP, ~/.config/flashforge-mcp/config.json. Avisos (opcional):
    "notify": {"ntfy": "https://ntfy.sh/<tema>"}
    "notify": {"telegram": {"token": "...", "chat_id": "..."}}
"""
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp"))
import server as ff  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
PAGE = open(os.path.join(HERE, "index.html"), encoding="utf-8").read()
POLL = 5            # segundos entre lecturas de la impresora
HISTORY = 30 * 60   # segundos de gráfica


def summary(d):
    slots = (d.get("matlStationInfo") or {}).get("slotInfos") or []
    return {
        "status": d.get("status"),
        "file": d.get("printFileName"),
        "progress": d.get("printProgress"),
        "layer": d.get("printLayer"),
        "layers": d.get("targetPrintLayer"),
        "duration": d.get("printDuration"),
        "remaining": d.get("estimatedTime"),
        "speed": d.get("printSpeedAdjust"),
        "nozzles": d.get("nozzleTemps"),
        "nozzleTargets": d.get("nozzleTargetTemps"),
        "bed": d.get("platTemp"),
        "bedTarget": d.get("platTargetTemp"),
        "coolingFan": d.get("coolingFanSpeed"),
        "chamberFan": d.get("chamberFanSpeed"),
        "door": d.get("doorStatus"),
        "error": d.get("errorCode"),
        "light": d.get("lightStatus"),
        "totalMinutes": d.get("cumulativePrintTime"),
        "totalFilament": d.get("cumulativeFilament"),
        "disk": d.get("remainingDiskSpace"),
        "firmware": d.get("firmwareVersion"),
        "slots": [{"id": s.get("slotId"), "material": s.get("materialName"),
                   "color": s.get("materialColor"), "loaded": s.get("hasFilament")} for s in slots],
        "camera": "/camera",
    }


def notify(title, text):
    conf = ff.cfg().get("notify") or {}
    try:
        if conf.get("ntfy"):
            req = urllib.request.Request(conf["ntfy"], data=text.encode(),
                                         headers={"Title": title, "Tags": "printer"})
            urllib.request.urlopen(req, timeout=10).close()
        if conf.get("telegram"):
            t = conf["telegram"]
            body = urllib.parse.urlencode({"chat_id": t["chat_id"], "text": f"{title}\n{text}"}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{t['token']}/sendMessage", body, timeout=10).close()
    except Exception as e:
        print("aviso no enviado:", e, file=sys.stderr)


class Printer:
    """Lee la impresora cada POLL segundos (una sola vez para todos), guarda el historial de
    temperaturas y avisa cuando una impresión termina, se pausa o da error."""

    def __init__(self):
        self.last, self.error, self.lock = None, None, threading.Lock()
        self.history = deque(maxlen=HISTORY // POLL)
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        prev = None
        while True:
            try:
                s = summary(ff.post_json("detail").get("detail", {}))
                with self.lock:
                    self.last, self.error = s, None
                    self.history.append([int(time.time()), *(s["nozzles"] or []), s["bed"]])
                if prev:
                    self.events(prev, s)
                prev = s
            except Exception as e:
                with self.lock:
                    self.error = f"No responde la impresora: {e}"
            time.sleep(POLL)

    def events(self, a, b):
        name = b["file"] or a["file"] or "la impresión"
        if b["error"] and b["error"] != a["error"]:
            notify("Creator 5: error", f"{b['error']} en {name}")
        if a["status"] == "printing" and b["status"] in ("pause", "paused"):
            notify("Creator 5: en pausa", f"{name} se ha pausado (capa {b['layer']}/{b['layers']})")
        if a["status"] in ("printing", "pause", "paused") and b["status"] not in ("printing", "pause", "paused", "busy", "heating"):
            if b["status"] == "completed" or (a["progress"] or 0) > 0.98:
                notify("Creator 5: terminada", f"{name} ha terminado ({round((b['duration'] or a['duration'] or 0) / 60)} min)")
            else:
                notify("Creator 5: detenida", f"{name} se ha parado al {round((a['progress'] or 0) * 100)} % (estado: {b['status']})")

    def snapshot(self):
        with self.lock:
            if self.last is None:
                raise RuntimeError(self.error or "Leyendo la impresora…")
            return dict(self.last, stale=self.error)


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


printer = Printer()
cam = Camera()


def image_type(data):
    return "image/png" if data[:4] == b"\x89PNG" else "image/bmp" if data[:2] == b"BM" else "image/jpeg"


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def fail(self, e, code=502):
        self.send(code, json.dumps({"error": str(e)}))

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        try:
            if url.path in ("/", "/index.html"):
                return self.send(200, PAGE, "text/html; charset=utf-8")
            if url.path == "/camera":
                return self.camera()
            if url.path == "/api/status":
                return self.send(200, json.dumps(printer.snapshot()))
            if url.path == "/api/history":
                with printer.lock:
                    return self.send(200, json.dumps(list(printer.history)))
            if url.path == "/api/files":
                return self.send(200, json.dumps(ff.post_json("gcodeList").get("gcodeList") or []))
            if url.path == "/api/thumb":
                data = ff.file_thumb(q["file"][0])
                return self.send(200, data, image_type(data)) if data else self.send(404, "{}")
            if url.path == "/api/thumb/current":
                with urllib.request.urlopen(f"http://{ff.cfg()['host']}:8898/getThum", timeout=10) as r:
                    data = r.read()
                return self.send(200, data, image_type(data)) if data[:1] != b"{" else self.send(404, "{}")
        except Exception as e:
            return self.fail(e)
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
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            acts = {
                "/api/pause": lambda: ff.t_job("pause"),
                "/api/continue": lambda: ff.t_job("continue"),
                "/api/light/on": lambda: ff.t_light(True),
                "/api/light/off": lambda: ff.t_light(False),
                "/api/speed": lambda: ff.t_speed(body["percent"]),
                # el panel solo lo manda si la persona ha marcado que la placa está limpia y vacía
                "/api/print": lambda: ff.t_start_print(body["file"], confirm=body.get("plateClear") is True,
                                                       leveling=bool(body.get("leveling", True))),
                "/api/test-notify": lambda: notify("Creator 5: prueba", "Los avisos del panel funcionan."),
            }
            if self.path not in acts:
                return self.send(404, "{}")
            acts[self.path]()
            self.send(200, '{"ok": true}')
        except Exception as e:
            self.fail(e)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
