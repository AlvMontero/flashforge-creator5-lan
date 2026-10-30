#!/usr/bin/env python3
"""MCP para la Flashforge Creator 5 por su API local (HTTP 8898, cámara MJPEG 8080).

Sin dependencias: JSON-RPC sobre stdio con la biblioteca estándar.
Protocolo: el conector Flashforge de OrcaSlicer 2.4.2 (src/slic3r/Utils/Flashforge.cpp) y
https://github.com/Parallel-7/flashforge-api-docs (no oficial).

La impresora tiene que estar en modo solo LAN. La IP, el número de serie y el código de acceso se
leen de ~/.config/flashforge-mcp/config.json (no está en git):
    {"host": "192.168.1.50", "serial": "...", "check_code": "..."}

Arrancar o cancelar una impresión pide confirm=true: Claude solo lo pasa cuando el usuario ha
dicho que sí y ha comprobado que la placa está limpia y vacía.
"""
import base64
import json
import os
import sys
import time
import urllib.request
import uuid

CONFIG = os.path.expanduser("~/.config/flashforge-mcp/config.json")
SNAP_DIR = os.path.expanduser("~/.config/flashforge-mcp/snapshots")
TIMEOUT = 15


def cfg():
    with open(CONFIG) as f:
        return json.load(f)


def auth(c):
    return {"serialNumber": c["serial"], "checkCode": c["check_code"]}


def post_json(path, body=None, timeout=TIMEOUT):
    c = cfg()
    data = json.dumps({**auth(c), **(body or {})}).encode()
    req = urllib.request.Request(f"http://{c['host']}:8898/{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read() or b"{}")
    if out.get("code", 0) != 0:
        raise RuntimeError(f"La impresora respondió code={out.get('code')}: {out.get('message')}")
    return out


def control(cmd, args):
    return post_json("control", {"payload": {"cmd": cmd, "args": args}})


# --- herramientas -------------------------------------------------------------------------------

STATUS_KEYS = ["name", "status", "printFileName", "printProgress", "printLayer", "targetPrintLayer",
               "estimatedTime", "printDuration", "platTemp", "platTargetTemp", "leftTemp",
               "leftTargetTemp", "rightTemp", "rightTargetTemp", "chamberTemp", "lightStatus",
               "doorStatus", "errorCode", "firmwareVersion", "ipAddr", "nozzleCnt", "nozzleStyle",
               "leftFilamentType", "rightFilamentType", "currentPrintSpeed", "printSpeedAdjust",
               "remainingDiskSpace", "cumulativePrintTime", "cumulativeFilament"]


def t_status(raw=False):
    d = post_json("detail").get("detail", {})
    if raw:
        return d
    out = {k: d[k] for k in STATUS_KEYS if k in d}
    # todo lo que hable de cabezales, boquillas o material, por si la Creator 5 usa otros nombres
    for k, v in d.items():
        if k not in out and any(s in k.lower() for s in ("nozzle", "extruder", "tool", "matl", "temp", "filament")):
            out[k] = v
    if isinstance(out.get("printProgress"), (int, float)):
        out["printProgress_pct"] = round(out["printProgress"] * 100, 1)
    return out


def t_list_files():
    return post_json("gcodeList")


def t_camera_snapshot():
    c = cfg()
    url = f"http://{c['host']}:8080/?action=stream"
    try:
        url = post_json("detail").get("detail", {}).get("cameraStreamUrl") or url
    except Exception:
        pass
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        buf, deadline = b"", time.time() + TIMEOUT
        while time.time() < deadline:
            buf += r.read(4096)
            a = buf.find(b"\xff\xd8")
            b = buf.find(b"\xff\xd9", a + 2) if a >= 0 else -1
            if a >= 0 and b > 0:
                jpg = buf[a:b + 2]
                break
        else:
            raise RuntimeError("No llegó ninguna imagen de la cámara")
    os.makedirs(SNAP_DIR, exist_ok=True)
    path = os.path.join(SNAP_DIR, time.strftime("c5-%Y%m%d-%H%M%S.jpg"))
    with open(path, "wb") as f:
        f.write(jpg)
    return {"_image": base64.b64encode(jpg).decode(), "path": path}


def _upload(path, print_now, leveling, mappings):
    c = cfg()
    name = os.path.basename(path)
    content = open(path, "rb").read()
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"gcodeFile\"; filename=\"{name}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    maps = json.dumps(mappings or [])
    headers = {**auth(c), "fileSize": str(len(content)), "printNow": "true" if print_now else "false",
               "levelingBeforePrint": "true" if leveling else "false", "flowCalibration": "false",
               "firstLayerInspection": "false", "timeLapseVideo": "false", "useMatlStation": "false",
               "gcodeToolCnt": str(len(mappings or [])),
               "materialMappings": base64.b64encode(maps.encode()).decode() if print_now else "",
               "Content-Type": f"multipart/form-data; boundary={boundary}"}
    req = urllib.request.Request(f"http://{c['host']}:8898/uploadGcode", data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as r:
        out = json.loads(r.read() or b"{}")
    if out.get("code", 0) != 0:
        raise RuntimeError(f"Subida rechazada code={out.get('code')}: {out.get('message')}")
    return {"uploaded": name, "print_now": print_now, "response": out}


def t_upload_file(path):
    return _upload(os.path.expanduser(path), False, False, None)


def need_confirm(confirm, what):
    if confirm is not True:
        raise RuntimeError(f"{what} necesita confirm=true. Pregunta antes al usuario (y que compruebe que la placa está limpia y vacía).")


def t_start_print(file_name, confirm=False, leveling=True, material_mappings=None):
    need_confirm(confirm, "Arrancar una impresión")
    body = {"fileName": file_name, "levelingBeforePrint": bool(leveling)}
    if material_mappings:
        body["materialMappings"] = material_mappings
    return post_json("printGcode", body)


def t_upload_and_print(path, confirm=False, leveling=True, material_mappings=None):
    need_confirm(confirm, "Arrancar una impresión")
    return _upload(os.path.expanduser(path), True, leveling, material_mappings)


def t_job(action, confirm=False):
    if action not in ("pause", "continue", "cancel"):
        raise RuntimeError("action debe ser pause, continue o cancel")
    if action == "cancel":
        need_confirm(confirm, "Cancelar la impresión")
    return control("jobCtl_cmd", {"jobID": "", "action": action})


def t_light(on):
    return control("lightControl_cmd", {"status": "open" if on else "close"})


TOOLS = {
    "c5_status": (t_status, "Estado de la Creator 5: estado, progreso, capas, tiempo, temperaturas, error, firmware. raw=true devuelve la respuesta completa.",
                  {"raw": {"type": "boolean"}}, []),
    "c5_camera_snapshot": (t_camera_snapshot, "Foto de la cámara de la Creator 5 (y la guarda en ~/.config/flashforge-mcp/snapshots).", {}, []),
    "c5_list_files": (t_list_files, "Últimos archivos de la impresora (gcodeList).", {}, []),
    "c5_upload_file": (t_upload_file, "Sube un .gcode o .3mf a la impresora sin imprimir.", {"path": {"type": "string"}}, ["path"]),
    "c5_start_print": (t_start_print, "Imprime un archivo que ya está en la impresora. Necesita confirm=true (el usuario lo ha aprobado y la placa está vacía). material_mappings: [{toolId (0-3), slotId (1-4), materialName, toolMaterialColor, slotMaterialColor}], solo para .3mf.",
                       {"file_name": {"type": "string"}, "confirm": {"type": "boolean"}, "leveling": {"type": "boolean"},
                        "material_mappings": {"type": "array", "items": {"type": "object"}}}, ["file_name"]),
    "c5_upload_and_print": (t_upload_and_print, "Sube un archivo y lo imprime. Necesita confirm=true (el usuario lo ha aprobado y la placa está vacía).",
                            {"path": {"type": "string"}, "confirm": {"type": "boolean"}, "leveling": {"type": "boolean"},
                             "material_mappings": {"type": "array", "items": {"type": "object"}}}, ["path"]),
    "c5_job_control": (t_job, "Pausa (pause), reanuda (continue) o cancela (cancel, necesita confirm=true) la impresión.",
                       {"action": {"type": "string", "enum": ["pause", "continue", "cancel"]}, "confirm": {"type": "boolean"}}, ["action"]),
    "c5_light": (t_light, "Enciende o apaga la luz de la Creator 5.", {"on": {"type": "boolean"}}, ["on"]),
}


# --- JSON-RPC por stdio -------------------------------------------------------------------------

def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle(req):
    m, rid = req.get("method"), req.get("id")
    if m == "initialize":
        return {"protocolVersion": req.get("params", {}).get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}}, "serverInfo": {"name": "flashforge-c5", "version": "0.1.0"}}
    if m == "ping":
        return {}
    if m == "tools/list":
        return {"tools": [{"name": n, "description": d,
                           "inputSchema": {"type": "object", "properties": p, "required": r}}
                          for n, (_, d, p, r) in TOOLS.items()]}
    if m == "tools/call":
        p = req.get("params", {})
        fn = TOOLS[p["name"]][0]
        try:
            res = fn(**(p.get("arguments") or {}))
            content = []
            if isinstance(res, dict) and "_image" in res:
                content.append({"type": "image", "data": res.pop("_image"), "mimeType": "image/jpeg"})
            content.append({"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=1)})
            return {"content": content}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
    if rid is not None:
        raise KeyError(m)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        if "id" not in req:  # notificación
            continue
        try:
            send({"jsonrpc": "2.0", "id": req["id"], "result": handle(req)})
        except Exception as e:
            send({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32601, "message": str(e)}})


if __name__ == "__main__":
    main()
