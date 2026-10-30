# Flashforge Creator 5 por red local: MCP + panel web

Dos herramientas pequeñas, sin dependencias (solo Python 3.8+), para manejar una **Flashforge
Creator 5** por su API de red local, sin la nube de Flashforge:

- **`mcp/server.py`**: servidor [MCP](https://modelcontextprotocol.io) para que una IA (Claude Code,
  Claude Desktop u otro cliente MCP) consulte el estado, vea la cámara, suba archivos y lance,
  pause o cancele impresiones.
- **`panel/`**: panel web con estado, progreso, hora de fin, temperaturas (con gráfica), material
  de los 4 cabezales, cámara en directo y archivos de la impresora; deja pausar, reanudar, cambiar
  la velocidad, encender la luz e imprimir, y **avisa al móvil** cuando termina, se pausa o falla.
  Sirve para la pestaña **«Dispositivo» de OrcaSlicer**, que con la Creator 5 sale en blanco, o para
  cualquier navegador de tu red.

*English summary: a dependency-free MCP server and a small web dashboard for the Flashforge
Creator 5 over its local LAN API (port 8898) and MJPEG camera (port 8080). The dashboard fills
OrcaSlicer's otherwise blank "Device" tab. Docs below are in Spanish.*

## Por qué

OrcaSlicer solo integra de verdad las impresoras Bambu Lab. Con cualquier otra, la pestaña
«Dispositivo» se limita a abrir la página web de la impresora, y la Creator 5 no tiene: el puerto
80 no responde, así que la pestaña sale en blanco. Lo que sí tiene la impresora es una API HTTP local
(puerto 8898), la misma que usa el conector «Flashforge» de OrcaSlicer para enviar trabajos, y una
cámara MJPEG (puerto 8080). Estas herramientas usan esas dos cosas.

Probado con una Creator 5 (4 cabezales), **firmware 2.0.0**, en **modo solo LAN**, y OrcaSlicer 2.4.2.
Con otros firmwares o modelos de Flashforge puede funcionar o no.

## Lo que necesitas

1. **IP de la impresora.** Mejor fíjala en el router (reserva DHCP), o habrá que cambiarla aquí cada
   vez que cambie.
2. **Número de serie y código de acceso** («check code»). Al activar el **modo solo LAN** en la
   impresora (en los ajustes de red; el nombre exacto del menú puede variar con el firmware), la
   pantalla muestra el código de acceso. El número de serie está en los ajustes o en la etiqueta.
   Con el modo solo LAN activo, la app de Flashforge en el móvil deja de ver la impresora.
3. **Python 3.8 o superior** en la máquina donde vaya a correr. No hace falta instalar nada más.

## Configuración

Copia [`config.example.json`](config.example.json) a `~/.config/flashforge-mcp/config.json` y
rellénalo. La usan tanto el MCP como el panel:

```bash
mkdir -p ~/.config/flashforge-mcp && chmod 700 ~/.config/flashforge-mcp
cp config.example.json ~/.config/flashforge-mcp/config.json
chmod 600 ~/.config/flashforge-mcp/config.json
nano ~/.config/flashforge-mcp/config.json
```

```json
{"host": "192.168.1.50", "serial": "SNXXXXXXXXXXX", "check_code": "tu-codigo"}
```

El código de acceso da control sobre la impresora: no lo subas a ningún repositorio.

Comprobación rápida (debe devolver el estado de la impresora):

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"c5_status","arguments":{}}}\n' | python3 mcp/server.py
```

## Panel web

### Dónde ponerlo

En cualquier máquina de tu red local que esté encendida cuando imprimas y que llegue a la impresora:

- **Una Raspberry Pi** u otro miniordenador siempre encendido. Es lo más cómodo: el panel está
  disponible para cualquier ordenador o móvil de casa.
- **Tu propio ordenador**, el mismo donde usas OrcaSlicer. Solo funcionará mientras esté encendido y
  el panel arrancado.
- **Un NAS, un servidor casero, un contenedor...** Cualquier sitio con Python 3.

### Arrancarlo a mano

```bash
git clone https://github.com/AlvMontero/flashforge-creator5-lan.git
cd flashforge-creator5-lan
python3 panel/app.py          # puerto 8090; otro: python3 panel/app.py 9000
```

Abre `http://IP-DE-ESA-MAQUINA:8090` en el navegador. En un Mac o en la misma máquina vale
`http://localhost:8090`.

### Dejarlo como servicio (Linux / Raspberry Pi OS, systemd)

Hay una unidad de ejemplo en [`panel/flashforge-panel.service`](panel/flashforge-panel.service). Da
por hecho que clonaste el repo en `~/flashforge-creator5-lan`:

```bash
mkdir -p ~/.config/systemd/user
cp panel/flashforge-panel.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now flashforge-panel
sudo loginctl enable-linger "$USER"     # para que arranque sin iniciar sesión
```

Si la máquina tiene cortafuegos, abre el puerto solo a tu red local. Con `ufw`:

```bash
sudo ufw allow from 192.168.0.0/16 to any port 8090 proto tcp comment 'Panel Creator 5'
```

En macOS puedes dejarlo arrancado con `launchd` o simplemente lanzarlo cuando lo necesites.

### Verlo en OrcaSlicer

En la pestaña **Preparar**, pulsa el icono de Wi-Fi junto a la impresora (la conexión de la
impresora) y en el campo **«Device UI»** pon la dirección del panel, por ejemplo
`http://raspberrypi.local:8090` o `http://192.168.1.60:8090`. La pestaña **«Dispositivo»** lo
mostrará.

### Qué hace y qué no

- Muestra estado, archivo con su miniatura, progreso, capa, tiempo transcurrido, tiempo restante y
  **hora aproximada de fin**, temperatura actual y objetivo de cada cabezal y de la cama, material y
  color de cada cabezal, ventiladores y puerta.
- **Gráfica de temperaturas** de los últimos 30 minutos (se ven bien los cambios de cabezal).
- **Contadores** de la impresora: horas impresas, metros de filamento, espacio libre y firmware.
- **Archivos de la impresora** con miniatura y botón de imprimir. Solo se activa con la impresora
  libre, y pide marcar «He comprobado que la placa está limpia y vacía» (y si nivelar antes).
- **Velocidad** de la impresión en curso: 50, 75, 100, 125 o 150 %.
- Cámara en directo. **La cámara de la Creator 5 corta las conexiones si se le abren varias a la
  vez** y luego tarda un rato en volver. Por eso el panel abre una sola conexión, guarda el último
  fotograma y lo reparte a todos los que miran (`/camera`). Si nadie mira, la suelta a los 15 s.
- Botones: **pausar** (pide confirmación), **reanudar** y **luz**. **No** deja cancelar; eso se hace
  desde la pantalla, OrcaSlicer o el MCP.
- El panel lee la impresora una vez cada 5 s para todos los que lo miran, así que tener varias
  pestañas abiertas no carga la impresora.
- **No tiene contraseña.** Cualquiera en tu red local puede verlo y pausar. No lo expongas a
  internet; si lo necesitas fuera de casa, usa una VPN (WireGuard, Tailscale...).

### Avisos al móvil

El panel avisa cuando una impresión **termina**, **se pausa** (por ejemplo, por un atasco) o **da
error**, aunque nadie tenga el panel abierto. Hace falta que el panel esté corriendo en una máquina
siempre encendida. Añade a `~/.config/flashforge-mcp/config.json` una de estas dos:

- **[ntfy](https://ntfy.sh)** (lo más fácil, sin cuenta): instala la app ntfy en el móvil, suscríbete
  a un tema con un nombre difícil de adivinar (por ejemplo `creator5-` y letras al azar) y pon
  `"notify": {"ntfy": "https://ntfy.sh/creator5-xxxxxxxx"}`. Ojo: en el servidor público, cualquiera
  que conozca el nombre del tema puede leer los avisos (solo llevan el nombre del archivo y el estado).
- **Telegram**: crea un bot con @BotFather y pon
  `"notify": {"telegram": {"token": "...", "chat_id": "..."}}`.

Reinicia el panel y pulsa «probar aviso» para comprobarlo.

### API del panel

Por si quieres usarla desde otra cosa: `GET /api/status`, `/api/history`, `/api/files`,
`/api/thumb?file=...`, `/api/thumb/current`, `/camera` (MJPEG); `POST /api/pause`, `/api/continue`,
`/api/light/on`, `/api/light/off`, `/api/speed` (`{"percent": 100}`), `/api/print`
(`{"file": "...", "plateClear": true, "leveling": true}`), `/api/test-notify`.

## Servidor MCP

### Claude Code

```bash
claude mcp add -s user flashforge -- python3 /ruta/a/flashforge-creator5-lan/mcp/server.py
```

### Otros clientes MCP (Claude Desktop, etc.)

Es un servidor MCP por stdio. En la configuración del cliente:

```json
{
  "mcpServers": {
    "flashforge": {"command": "python3", "args": ["/ruta/a/flashforge-creator5-lan/mcp/server.py"]}
  }
}
```

### Herramientas

| Herramienta | Qué hace |
|---|---|
| `c5_status` | Estado, progreso, capas, temperaturas, material de cada cabezal, errores. `raw=true` devuelve la respuesta completa de la impresora |
| `c5_camera_snapshot` | Foto de la cámara (también la guarda en `~/.config/flashforge-mcp/snapshots/`) |
| `c5_list_files` | Últimos archivos de la impresora |
| `c5_upload_file` | Sube un `.gcode` o `.3mf` sin imprimir |
| `c5_start_print` | Imprime un archivo que ya está en la impresora |
| `c5_upload_and_print` | Sube e imprime |
| `c5_job_control` | Pausa, reanuda o cancela |
| `c5_light` | Enciende o apaga la luz |
| `c5_set_speed` | Cambia la velocidad de la impresión en curso (%) |

**Arrancar y cancelar piden `confirm=true`**, y sin él devuelven un error. La idea es que la IA solo lo
pase cuando una persona haya dicho que sí y haya comprobado que la placa está limpia y vacía: la
cámara de la Creator 5 no ve toda la placa.

## Notas de uso con la Creator 5

Cosas que encontramos probándola (firmware 2.0.0):

- **Mejor `.gcode` que `.gcode.3mf`.** Un `.gcode.3mf` laminado con la línea de comandos de
  OrcaSlicer (sin miniatura) se quedó «descomprimiendo» y dio el error E0166. El `.gcode` plano
  funciona. Los que se envían desde OrcaSlicer con su interfaz no dieron problemas.
- **Cabezales en el G-code:** `T0`–`T3` son los cabezales 1–4.
- **El final del perfil de la Creator 5 en OrcaSlicer 2.4.2 no apaga la boquilla ni la cama.** Si
  generas G-code tú mismo, añade `M104 S0 Tn` y `M140 S0` al final.
- **Cambiar la temperatura a mitad de impresión** (torres de temperatura): funcionó enviando
  `M104 S<t>` seguido de `M104 S<t> T<n>`. Con solo la segunda forma, parecía no aplicarse (sin
  comprobar del todo).
- La API devuelve a veces, antes de empezar a imprimir, `printLayer` igual a la última capa. No te
  fíes de ese valor hasta que `printDuration` sea mayor que 0.
- `chamberTemp` devuelve valores sin sentido (por ejemplo -83) en este modelo.

## Hacerlo con una IA de código

Si prefieres que una IA de código (Claude Code, Cursor, Copilot...) te lo monte o lo adapte a tu
caso, en [PROMPT.md](PROMPT.md) tienes un prompt listo para copiar.

## Créditos

- Protocolo: el conector Flashforge de OrcaSlicer (`src/slic3r/Utils/Flashforge.cpp`) y la
  documentación no oficial de [Parallel-7/flashforge-api-docs](https://github.com/Parallel-7/flashforge-api-docs).
- No es un proyecto de Flashforge ni está respaldado por Flashforge. Úsalo bajo tu responsabilidad.

Licencia [MIT](LICENSE).
