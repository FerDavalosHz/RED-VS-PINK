# servidor.py - El "cerebro" de la página: sirve las pantallas y hace lo que los
# botones piden (arrancar/parar el entrenamiento, guardar el mapa y los puntos).
#
# Solo usa la librería estándar de Python. Solo escucha en TU ordenador
# (127.0.0.1): nadie de fuera puede conectarse.
#
# Se abre con ABRIR_RED_VS_PINK.bat (doble clic). Si ya estaba abierto, el
# segundo intento solo abre la página y se cierra.

import http.server
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.parse import urlparse

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import recompensas  # noqa: E402

PUERTO = 8765
URL = f"http://localhost:{PUERTO}/"
RUTA_MAPA = os.path.join(AQUI, "mapa.json")
CARPETA_MODELOS = os.path.join(AQUI, "modelos")
LOG = os.path.join(AQUI, "entrenamiento.log")
SCRIPT = "entrenar.py"
_VENV_PY = os.path.join(AQUI, "venv", "Scripts", "python.exe")
PYTHON = _VENV_PY if os.path.exists(_VENV_PY) else sys.executable
SIN_VENTANA = 0x08000000      # CREATE_NO_WINDOW: consola invisible (los procesos hijos la heredan)
GRUPO_NUEVO = 0x00000200      # CREATE_NEW_PROCESS_GROUP: no le afectan las señales de este proceso
# OJO: NO usar DETACHED_PROCESS junto a CREATE_NO_WINDOW: el lanzador de Python del
# entorno virtual crea un segundo proceso y, sin consola que heredar, Windows le
# abre una ventana de cmd vacía.

TIPOS_OBJETO = {"red", "pink", "caja", "pistola", "veneno", "vibora"}


# ----------------------------------------------------------------------
# Entrenamiento: saber si corre, arrancarlo, pararlo
# ----------------------------------------------------------------------
_cache_pids = {}


def buscar_pids(script=SCRIPT, max_edad=2.0):
    """PIDs de los procesos que están ejecutando 'script' (aunque los lanzara otro)."""
    hoy = time.time()
    t, pids = _cache_pids.get(script, (0, []))
    if hoy - t < max_edad:
        return pids
    orden = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and "
             f"$_.CommandLine -like '*{script}*' }} | ForEach-Object {{ $_.ProcessId }}")
    try:
        salida = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", orden],
            capture_output=True, text=True, timeout=20, creationflags=SIN_VENTANA).stdout
        pids = [int(x) for x in salida.split() if x.isdigit()]
    except Exception:
        pids = []
    _cache_pids[script] = (hoy, pids)
    return pids


def iniciar(script=SCRIPT):
    if buscar_pids(script, 0):
        return {"ok": False, "mensaje": "Ya estaba entrenando."}
    with open(LOG, "wb") as log:                  # registro nuevo: así se ven los errores
        subprocess.Popen([PYTHON, "-u", script], cwd=AQUI, stdout=log,
                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         creationflags=SIN_VENTANA | GRUPO_NUEVO)
    _cache_pids.pop(script, None)
    return {"ok": True, "mensaje": "Entrenamiento lanzado."}


def parar(script=SCRIPT):
    pids = buscar_pids(script, 0)
    for pid in pids:                              # /T = también sus procesos hijos
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, creationflags=SIN_VENTANA)
    _cache_pids.pop(script, None)
    return {"ok": True, "mensaje": "Entrenamiento parado." if pids else "No había nada que parar."}


def rondas_guardadas():
    """Números de las rondas cuyas IAs están guardadas (modelos/historial/ronda_NNN)."""
    carpeta = os.path.join(CARPETA_MODELOS, "historial")
    try:
        return sorted(int(n[6:]) for n in os.listdir(carpeta)
                      if n.startswith("ronda_") and n[6:].isdigit())
    except OSError:
        return []


_cerrojo_demo = threading.Lock()


def generar_demo(ronda=None):
    """Juega una partida entre las IAs de esa ronda y guarda sus 'pensamientos'.

    Tarda unos segundos (carga PyTorch). Deja el resultado en modelos/demo.js.
    """
    rondas = rondas_guardadas()
    if ronda is None:
        ronda = rondas[-1] if rondas else None
    orden = [PYTHON, os.path.join(AQUI, "generar_visor.py"), "--solo-datos"]
    if ronda is not None:
        if ronda not in rondas:
            return {"ok": False, "mensaje": f"La ronda {ronda} no está guardada."}
        orden += ["--ronda", str(ronda)]
    with _cerrojo_demo:                           # de una en una
        r = subprocess.run(orden, cwd=AQUI, capture_output=True, text=True, timeout=180,
                           creationflags=SIN_VENTANA)
    if r.returncode != 0:
        return {"ok": False, "mensaje": (r.stderr or r.stdout or "error").strip()[-400:]}
    return {"ok": True, "ronda": ronda}


def ultimas_lineas(ruta, n=14):
    try:
        with open(ruta, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 6000))
            texto = f.read().decode("utf-8", errors="replace").lstrip("﻿")
        return texto.splitlines()[-n:]
    except OSError:
        return []


def leer_json(ruta):
    try:
        with open(ruta, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def estado():
    pids = buscar_pids()
    log = ultimas_lineas(LOG)
    # ¿El entrenamiento ya está usando el mapa y los puntos que hay guardados ahora?
    aplicado = {"mapa": None, "puntos": None}
    uso = leer_json(os.path.join(CARPETA_MODELOS, "en_uso.json"))
    if pids and uso and time.time() - uso.get("t", 0) < 90:
        def igual(usado, ruta):
            try:
                return usado is not None and abs(usado - os.path.getmtime(ruta)) < 0.01
            except OSError:
                return usado is None                  # el archivo no existe y no lo está usando
        aplicado = {"mapa": igual(uso.get("mapa"), RUTA_MAPA),
                    "puntos": igual(uso.get("recompensas"), recompensas.RUTA_RECOMPENSAS)}
    return {"entrenando": bool(pids), "aplicado": aplicado,
            "progreso": leer_json(os.path.join(CARPETA_MODELOS, "progreso.json")),
            "log": log,
            # se cayó solo si NO corre y el registro termina con un error
            "error": (not pids) and any("Traceback" in l or "Error" in l for l in log)}


# ----------------------------------------------------------------------
# Mapa: validar y guardar
# ----------------------------------------------------------------------
def _entero(v, minimo, maximo, nombre):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v):
        raise ValueError(f"{nombre} debe ser un número entero")
    v = int(v)
    if not minimo <= v <= maximo:
        raise ValueError(f"{nombre} fuera de rango")
    return v


def validar_mapa(m):
    if not isinstance(m, dict):
        raise ValueError("el mapa no es un objeto")
    ancho = _entero(m.get("ancho"), 5, 200, "ancho")
    alto = _entero(m.get("alto"), 5, 200, "alto")

    def rectangulo(r):
        return {"x": _entero(r.get("x"), 0, ancho, "x"), "y": _entero(r.get("y"), 0, alto, "y"),
                "w": _entero(r.get("w"), 1, ancho, "w"), "h": _entero(r.get("h"), 1, alto, "h")}

    paredes = [rectangulo(r) for r in m.get("paredes", [])]
    escaleras = [rectangulo(r) for r in m.get("escaleras", [])]
    spawn_jugadores = [rectangulo(r) for r in m.get("spawn_jugadores", [])]
    spawn_objetos = [rectangulo(r) for r in m.get("spawn_objetos", [])]
    objetos = []
    for o in m.get("objetos", []):
        if o.get("tipo") not in TIPOS_OBJETO:
            raise ValueError("objeto desconocido: " + str(o.get("tipo")))
        objetos.append({"tipo": o["tipo"], "x": _entero(o.get("x"), 0, ancho - 1, "x"),
                        "y": _entero(o.get("y"), 0, alto - 1, "y")})
    for jugador in ("red", "pink"):
        if sum(1 for o in objetos if o["tipo"] == jugador) != 1:
            raise ValueError(f"tiene que haber exactamente un {jugador}")
    return {"ancho": ancho, "alto": alto, "paredes": paredes, "objetos": objetos,
            "escaleras": escaleras, "spawn_jugadores": spawn_jugadores,
            "spawn_objetos": spawn_objetos}


def escribir_atomico(ruta, texto):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(texto)
    for _ in range(10):                           # el entrenamiento puede estar leyéndolo
        try:
            os.replace(tmp, ruta)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, ruta)


# ----------------------------------------------------------------------
# El servidor web
# ----------------------------------------------------------------------
class Manejador(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=AQUI, **kwargs)

    def log_message(self, *args):
        pass                                      # sin ruido

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # -- seguridad: solo páginas pedidas desde este mismo ordenador --
    def _permitido(self):
        host = self.headers.get("Host", "")
        if host not in (f"localhost:{PUERTO}", f"127.0.0.1:{PUERTO}"):
            return False
        origen = self.headers.get("Origin")
        return origen is None or origen in (f"http://localhost:{PUERTO}",
                                            f"http://127.0.0.1:{PUERTO}")

    def _json(self, datos, codigo=200):
        cuerpo = json.dumps(datos).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _cuerpo(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > 5_000_000:
            raise ValueError("demasiado grande")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if not self._permitido():
            return self._json({"error": "no permitido"}, 403)
        ruta = urlparse(self.path).path
        if ruta == "/api/estado":
            return self._json(estado())
        if ruta == "/api/rondas":
            return self._json({"rondas": rondas_guardadas()})
        if ruta == "/api/mapa":
            return self._json(leer_json(RUTA_MAPA) or {})
        if ruta == "/api/recompensas":
            if not os.path.exists(recompensas.RUTA_RECOMPENSAS):
                recompensas.guardar(recompensas.DEFECTOS)       # la crea la 1ª vez
            return self._json({"valores": recompensas.leer(), "meta": recompensas.PARAMETROS})
        if ruta == "/":
            self.path = "/centro.html"
        partes = ruta.lower().split("/")
        if any(p in ("venv", "__pycache__", ".git") for p in partes):
            return self._json({"error": "no"}, 404)
        return super().do_GET()

    def do_POST(self):
        if not self._permitido() or self.headers.get("X-RVP") != "1":
            return self._json({"error": "no permitido"}, 403)
        ruta = urlparse(self.path).path
        try:
            datos = self._cuerpo()
            if ruta == "/api/entrenar":
                accion = datos.get("accion")
                if accion == "iniciar":
                    return self._json(iniciar())
                if accion == "parar":
                    return self._json(parar())
                if accion == "reiniciar":
                    parar()
                    time.sleep(1.0)
                    return self._json(iniciar())
                return self._json({"error": "acción desconocida"}, 400)
            if ruta == "/api/demo":
                ronda = datos.get("ronda")
                return self._json(generar_demo(int(ronda) if ronda is not None else None))
            if ruta == "/api/mapa":
                escribir_atomico(RUTA_MAPA, json.dumps(validar_mapa(datos), indent=2))
                return self._json({"ok": True})
            if ruta == "/api/recompensas":
                return self._json({"ok": True,
                                   "valores": recompensas.guardar(datos.get("valores", {}))})
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            return self._json({"error": str(e)}, 400)
        return self._json({"error": "no existe"}, 404)


class Servidor(http.server.ThreadingHTTPServer):
    daemon_threads = True


def main():
    if sys.stdout is None:                        # con pythonw no hay consola
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.path.join(AQUI, "servidor.log"), "a", encoding="utf-8")
    try:
        servidor = Servidor(("127.0.0.1", PUERTO), Manejador)
    except OSError:                               # ya había uno abierto
        webbrowser.open(URL)
        return
    if not os.environ.get("RVP_SIN_NAVEGADOR"):
        threading.Timer(0.8, lambda: webbrowser.open(URL)).start()
    servidor.serve_forever()


if __name__ == "__main__":
    main()
