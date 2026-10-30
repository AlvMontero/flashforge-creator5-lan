# Prompt para montarlo con una IA de código

Copia el bloque de abajo en tu IA de código (Claude Code, Cursor, Copilot, etc.), abierta en una
carpeta vacía o en un clon de este repositorio. Cambia lo que va entre `<...>` antes de enviarlo.

```text
Quiero controlar mi impresora Flashforge Creator 5 por la red local, sin la nube de Flashforge, y ver
su estado en la pestaña «Dispositivo» de OrcaSlicer (campo «Device UI» de la conexión de la
impresora), que con esta impresora sale en blanco porque no tiene página web.

Datos:
- Impresora en <IP de la impresora>, en modo solo LAN. Número de serie y código de acceso los
  tengo yo: no los escribas en el código ni en ningún archivo que se suba a git; léelos de
  ~/.config/flashforge-mcp/config.json ({"host", "serial", "check_code"}, permisos 600) y pídeme
  que lo rellene.
- El panel correrá en <una Raspberry Pi / este ordenador / un NAS / ...>, con Python <versión>.

Referencia: el repositorio https://github.com/AlvMontero/flashforge-creator5-lan ya hace esto.
Úsalo como base (léelo antes de escribir nada) o reprodúcelo; ten en cuenta lo que dice su README.

Lo que sé de la impresora (firmware 2.0.0):
- API HTTP en el puerto 8898. Peticiones POST con JSON que incluye "serialNumber" y "checkCode":
  /detail (estado completo), /gcodeList, /printGcode, /control (payload {"cmd", "args"}: por
  ejemplo jobCtl_cmd con action pause|continue|cancel, lightControl_cmd con status open|close).
  /uploadGcode es multipart con la autenticación y las opciones en cabeceras (serialNumber,
  checkCode, fileSize, printNow, levelingBeforePrint...).
- Cámara MJPEG en http://<IP>:8080/?action=stream. Corta las conexiones si se le abren varias a
  la vez: el panel debe abrir una sola y repartir los fotogramas a todos los que miren.
- /detail devuelve, entre otros: status, printFileName, printProgress (0-1), printLayer,
  targetPrintLayer, printDuration (s), nozzleTemps y nozzleTargetTemps (4 valores), platTemp,
  platTargetTemp, errorCode, lightStatus, matlStationInfo.slotInfos (material y color por cabezal).
  Antes de empezar a imprimir, printLayer puede valer la última capa: no te fíes hasta que
  printDuration > 0.

Lo que quiero:
1. Un panel web en el puerto 8090, solo con la biblioteca estándar de Python, con: estado,
   archivo, progreso, capa, tiempo transcurrido y restante aproximado, temperaturas actual/objetivo
   de los 4 cabezales y la cama, material y color de cada cabezal, y la cámara en directo.
   Botones de pausar (con confirmación), reanudar, luz y velocidad (printerCtl_cmd con "speed";
   los campos que no cambies van a -200). Gráfica de temperaturas de los últimos 30 min, hora de
   fin (estimatedTime son los segundos que quedan), contadores (cumulativePrintTime en minutos,
   cumulativeFilament en metros) y lista de archivos (/gcodeList, miniaturas con /gcodeThumb) con
   botón de imprimir que exija marcar «la placa está limpia y vacía». Nada de cancelar desde el
   panel. Interfaz oscura y que se lea bien en la pestaña de OrcaSlicer y en el móvil.
   Avisos al móvil (ntfy o Telegram) cuando una impresión termine, se pause o dé error, aunque
   nadie tenga el panel abierto.
2. (Opcional) Un servidor MCP por stdio con herramientas de estado, foto de la cámara, listar,
   subir, imprimir, pausar/reanudar/cancelar y luz. Imprimir y cancelar deben exigir un parámetro
   confirm=true y fallar sin él.
3. Que arranque solo: <servicio de usuario de systemd / launchd en macOS / lo que convenga>.
   Si hay cortafuegos, dime qué regla hace falta para abrir el puerto solo a la red local, pero
   no la apliques tú.
4. Pruébalo contra la impresora real (solo lectura: estado y cámara) y enséñame que funciona.
   No lances, canceles ni pauses ninguna impresión sin preguntarme.
5. Dime al final la dirección exacta que tengo que poner en «Device UI» de OrcaSlicer.
```
