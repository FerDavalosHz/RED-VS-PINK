# entrenar.py - Entrena a Red y a Pink DESDE CERO con self-play.
#
#   Ejecuta:   .\venv\Scripts\python.exe entrenar.py
#   Mientras entrena, abre panel_entrenamiento.html en el navegador: se
#   refresca solo y te enseña qué van descubriendo. Ctrl+C para parar: lo ya
#   aprendido está guardado en cada ronda.
#
# NADIE LES ENSEÑA NADA. Empiezan sin saber que existen la pistola, la caja,
# el veneno, las paredes o el tiempo. Lo único que reciben son puntos:
#     +0.5 por quitar una vida, -0.5 por perderla, +1 ganar, -1 perder/empatar.
# Todo lo demás lo tienen que DESCUBRIR ellas probando cosas.
#
# SELF-PLAY: se turnan. Red aprende contra el Pink actual (congelado), luego
# Pink aprende contra el Red recién mejorado, y así RONDAS veces.
#
# FOTOS: antes de empezar y al final de cada ronda se guarda una copia en
#     modelos/historial/ronda_000, ronda_001, ...
#     python generar_visor.py --ronda 5 --abrir

import collections
import glob
import json
import os
import queue
import subprocess
import sys
import time

from stable_baselines3 import PPO

import recompensas
from entorno import RedVsPinkEnv, desde_modelo, observar, ajustar_juego, FRAME_SKIP
from juego import Juego, FPS, TIEMPO_MAX

AQUI = os.path.dirname(os.path.abspath(__file__))

# ---- Ajustes (cámbialos para entrenar más o menos) ----
RONDAS = int(os.environ.get("RVP_RONDAS", 40))             # cuántas veces se turnan
PASOS_POR_RONDA = int(os.environ.get("RVP_PASOS", 25_000)) # decisiones por IA y ronda
PARTIDAS_EVALUACION = 20        # partidas de prueba al final de cada ronda
CARPETA = os.environ.get("RVP_CARPETA") or os.path.join(AQUI, "modelos")   # (RVP_CARPETA: para pruebas)
HISTORIAL = os.path.join(CARPETA, "historial")

# Cosas que queremos saber si han descubierto (evento del juego -> nombre)
DESCUBRIMIENTOS = ["coge_pistola", "disparo", "golpe_bala", "sobrecalentada",
                   "coge_caja", "suelta_caja", "coge_veneno", "lanza_veneno", "bebe_veneno"]


class Emisor:
    """Graba algunos intentos del entrenamiento para verlos en intentos.html.

    NO PESA MUCHO, por diseño: solo se graba 1 de cada 'cada' intentos, en
    formato compacto (~20 KB cada uno). Se guardan en "lotes" de 10 intentos
    (modelos/lotes/lote_00000.js, ...) que NO se borran al reiniciar, así se
    puede ver TODO el historial. Tope: 150 lotes (~30 MB). Si se pasa, se van
    quitando lotes antiguos alternos: siempre queda una muestra de todo.
    """

    def __init__(self, mapa, cada=40, ultimos=100, cada_seg=4, lote=10, max_lotes=150):
        self.mapa = mapa
        self.cada = cada
        self.recientes = collections.deque(maxlen=ultimos)  # para la vista en vivo
        self.cada_seg = cada_seg
        self.lote = lote
        self.max_lotes = max_lotes
        self.carpeta_lotes = os.path.join(CARPETA, "lotes")
        os.makedirs(self.carpeta_lotes, exist_ok=True)
        existentes = self._lotes_en_disco()
        self.n_lote = int(existentes[-1][5:10]) + 1 if existentes else 0   # sigue la numeración
        self.pendientes = []                                # intentos del lote que se está llenando
        self.contados = 0
        self.ronda = 0
        self.ultimo_volcado = 0.0
        self.envs = ()                                      # los entornos (para saber qué mapa usan)
        self.uso = None                                     # lo mismo, si llega desde otro proceso
        # Cada intento grabado tiene un número ÚNICO que sigue creciendo aunque pares y
        # relances el entrenamiento (así nunca se confunden dos intentos distintos).
        self.seq = self._max_id_cerrado()
        self._adoptar_huerfanos()
        self._escribir_indice()

    def _guardar_max_id(self, n):
        self._escribir_atomico(os.path.join(self.carpeta_lotes, "estado.json"),
                               json.dumps({"max_id": n}))

    def _max_id_cerrado(self):
        """El mayor número de intento que ya está en un lote del disco."""
        try:
            with open(os.path.join(self.carpeta_lotes, "estado.json"), encoding="utf-8") as f:
                return int(json.load(f)["max_id"])
        except (OSError, ValueError, KeyError):
            pass
        mayor = 0                                           # primera vez: se mira dentro de los lotes
        for nombre in self._lotes_en_disco():
            try:
                with open(os.path.join(self.carpeta_lotes, nombre), encoding="utf-8") as f:
                    t = f.read()
                for it in json.loads(t[t.index("push(") + 5:t.rindex(")")])["intentos"]:
                    mayor = max(mayor, it["id"])
            except (OSError, ValueError):
                continue
        self._guardar_max_id(mayor)
        return mayor

    def _adoptar_huerfanos(self):
        """Recupera los intentos de la vista en vivo que aún no estaban en ningún lote
        (los que había cuando se paró el entrenamiento), para no perderlos."""
        try:
            with open(os.path.join(CARPETA, "intentos.js"), encoding="utf-8") as f:
                t = f.read()
            previos = json.loads(t[len("window.INTENTOS = "):].rstrip().rstrip(";"))["intentos"]
        except (OSError, ValueError, KeyError):
            return
        self.recientes.extend(previos[-self.recientes.maxlen:])
        huerfanos = [i for i in previos if i["id"] > self.seq]
        self.pendientes = huerfanos
        if huerfanos:
            self.seq = max(i["id"] for i in huerfanos)

    def _lotes_en_disco(self):
        return sorted(n for n in os.listdir(self.carpeta_lotes)
                      if n.startswith("lote_") and n.endswith(".js"))

    @staticmethod
    def _escribir_atomico(ruta, texto):
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(texto)
        # Windows no deja reemplazar un archivo mientras otro programa lo tiene abierto
        # (el navegador que lo lee, OneDrive sincronizando...): se reintenta unos segundos.
        for _ in range(30):
            try:
                os.replace(tmp, ruta)
                return
            except PermissionError:
                time.sleep(0.1)
        os.replace(tmp, ruta)

    def _escribir_indice(self):
        """Lista de lotes que hay, para que la página sepa cuáles cargar."""
        self._escribir_atomico(os.path.join(self.carpeta_lotes, "indice.js"),
                               "window.LOTES_INDICE = " + json.dumps(self._lotes_en_disco()) + ";")

    def _cerrar_lote(self):
        nombre = f"lote_{self.n_lote:05d}.js"
        texto = ("(window.LOTES = window.LOTES || []).push("
                 + json.dumps({"intentos": self.pendientes}, separators=(",", ":")) + ");")
        self._escribir_atomico(os.path.join(self.carpeta_lotes, nombre), texto)
        self._guardar_max_id(max(i["id"] for i in self.pendientes))
        self.n_lote += 1
        self.pendientes = []
        lotes = self._lotes_en_disco()
        while len(lotes) > self.max_lotes:           # demasiados: quito alternos de los antiguos
            candidatos = lotes[10:-50]               # se conservan siempre los más viejos y los más nuevos
            if not candidatos:
                break
            for viejo in candidatos[::2]:
                os.remove(os.path.join(self.carpeta_lotes, viejo))
            lotes = self._lotes_en_disco()
        self._escribir_indice()

    def quiere(self):
        self.contados += 1
        return self.contados % self.cada == 0

    def guardar(self, frames, info):
        # id = número único del intento grabado. corrida = la partida real (la nº 1200
        # de todas las jugadas), que es el número que se enseña en la página.
        self.seq += 1
        if info.get("uso"):                          # qué mapa y puntos usaba esa partida
            self.uso = info["uso"]
        intento = {"id": self.seq, "corrida": self.contados, "ronda": self.ronda,
                   "aprende": info["rol"],
                   "ganador": info["ganador"], "puntos": round(info["puntos"], 2),
                   "frames": frames, "mapa": info["mapa"], "vision": info.get("vision", 8),
                   "campo": info.get("campo_vision", 360)}
        self.recientes.append(intento)
        self.pendientes.append(intento)
        try:
            if len(self.pendientes) >= self.lote:
                self._cerrar_lote()
            if time.time() - self.ultimo_volcado >= self.cada_seg:
                self.volcar()
        except OSError as e:
            # Ver las repeticiones es secundario: un fallo al guardarlas NUNCA debe parar
            # el entrenamiento. Se avisa y se reintenta en la siguiente.
            self.ultimo_volcado = time.time()
            print("aviso: no pude guardar las repeticiones (se reintenta):", e, flush=True)

    def volcar(self):
        datos = {"mapa": self.mapa, "fps": FPS, "frames_por_seg": FPS / FRAME_SKIP,
                 "tiempo_max": TIEMPO_MAX, "total": self.contados,   # corridas jugadas en total
                 "intentos": list(self.recientes)}
        os.makedirs(CARPETA, exist_ok=True)
        self.ultimo_volcado = time.time()
        try:
            self._escribir_atomico(os.path.join(CARPETA, "intentos.js"),   # así nunca se lee a medias
                                   "window.INTENTOS = " + json.dumps(datos, separators=(",", ":")) + ";")
            uso = self.uso                           # qué mapa y qué puntos está usando de verdad
            if uso is None and self.envs:
                e = self.envs[0]
                uso = {"mapa": getattr(e.juego, "_mtime", None), "recompensas": e._rec_fecha}
            if uso:
                self._escribir_atomico(os.path.join(CARPETA, "en_uso.json"),
                                       json.dumps({**uso, "t": time.time()}))
        except OSError as e:                         # nunca debe tumbar el entrenamiento
            print("aviso: no pude actualizar la vista en vivo (se reintenta):", e, flush=True)


def crear_ia(env):
    # "MlpPolicy": cerebro de capas simples (2 capas de 64 neuronas).
    # ent_coef alto = les empuja a probar cosas MUY distintas (explorar), que
    # es justo lo que necesitan para descubrir la pistola sin ayuda.
    return PPO("MlpPolicy", env, verbose=0, device="cpu", ent_coef=0.02,
               n_steps=2048, batch_size=256)


def guardar(red, pink, ronda):
    for ruta in (CARPETA, os.path.join(HISTORIAL, f"ronda_{ronda:03d}")):
        os.makedirs(ruta, exist_ok=True)
        red.save(os.path.join(ruta, "red.zip"))
        pink.save(os.path.join(ruta, "pink.zip"))


def evaluar(red, pink, n=PARTIDAS_EVALUACION):
    """Hace jugar a las dos IAs n partidas y cuenta qué ha pasado."""
    res = {"red": 0, "pink": 0, "ambos_mueren": 0}
    valores = recompensas.leer()
    vistos = {k: 0 for k in DESCUBRIMIENTOS}   # en cuántas partidas pasó
    disparos, tiempo = 0, 0.0
    for _ in range(n):
        j = Juego()
        ajustar_juego(j, valores)                   # mismo rango de visión y espera que al entrenar
        acc = {"red": 0, "pink": 0}
        vio = set()
        while j.ganador() is None:
            if j.turno % FRAME_SKIP == 0:
                acc["red"] = int(red.predict(observar(j, "red"))[0])
                acc["pink"] = int(pink.predict(observar(j, "pink"))[0])
            j.paso(acc["red"], acc["pink"])
            for evento, _ in j.eventos:
                vio.add(evento)
                if evento == "disparo":
                    disparos += 1
        res[j.ganador()] += 1
        tiempo += j.tiempo
        for k in vio:
            if k in vistos:
                vistos[k] += 1
    pct = lambda v: round(100 * v / n, 1)
    fila = {"gana_red": pct(res["red"]), "gana_pink": pct(res["pink"]),
            "ambos": pct(res["ambos_mueren"]),
            "disparos": round(disparos / n, 2), "duracion": round(tiempo / n, 1)}
    fila.update({k: pct(v) for k, v in vistos.items()})
    return fila


def escribir_progreso(filas, ultima_ronda_prevista, episodios=0):
    """Deja los datos para que panel_entrenamiento.html los dibuje."""
    datos = {"total": ultima_ronda_prevista, "filas": filas, "episodios": episodios}
    with open(os.path.join(CARPETA, "progreso.json"), "w", encoding="utf-8") as f:
        json.dump(datos, f)
    with open(os.path.join(CARPETA, "progreso.js"), "w", encoding="utf-8") as f:
        f.write("const PROGRESO = " + json.dumps(datos) + ";")


def refrescar_visor():
    """Regenera visor.html con una partida de las IAs más recientes."""
    subprocess.run([sys.executable, os.path.join(AQUI, "generar_visor.py")],
                   cwd=AQUI, capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # sin ventana


# ======================================================================
# ENTRENAMIENTO EN PARALELO: Red y Pink entrenan A LA VEZ, cada una en su propio núcleo.
#
# Antes se turnaban (primero Red con Pink congelada, luego al revés): un solo núcleo
# trabajaba. Ahora cada una vive en su proceso y en cada ronda juega contra la versión
# que la otra guardó en la ronda anterior. Casi el doble de rápido.
# ======================================================================
class ColaGrabador:
    """Hace de 'grabador' dentro de un trabajador: manda los intentos al proceso principal."""

    def __init__(self, cola, rol, cada=40):
        self.cola, self.rol, self.cada, self.n = cola, rol, cada, 0

    def quiere(self):
        self.n += 1
        return self.n % self.cada == 0

    def guardar(self, frames, info):
        try:
            self.cola.put(("intento", self.rol, self.n, frames, info))
        except Exception:
            pass                                    # perder una repetición nunca debe parar el entrenamiento


def guardar_uno(modelo, rol, ronda):
    for ruta in (CARPETA, os.path.join(HISTORIAL, f"ronda_{ronda:03d}")):
        os.makedirs(ruta, exist_ok=True)
        modelo.save(os.path.join(ruta, f"{rol}.zip"))


def trabajador(rol, ordenes, salida, intentos, carpeta, pasos):
    """Un proceso que entrena a UNA IA (Red o Pink) mientras la otra entrena en otro núcleo."""
    global CARPETA, HISTORIAL
    CARPETA, HISTORIAL = carpeta, os.path.join(carpeta, "historial")
    import traceback
    import torch
    torch.set_num_threads(1)                        # un núcleo por trabajador
    otro = "pink" if rol == "red" else "red"
    try:
        env = RedVsPinkEnv(rol)
        env.grabador = ColaGrabador(intentos, rol)
        modelo = None
        while True:
            orden = ordenes.get()
            if orden[0] == "fin":
                return
            if orden[0] == "crear":                 # IA recién nacida (ronda 0)
                modelo = crear_ia(env)
                guardar_uno(modelo, rol, 0)
                salida.put(("listo", rol, 0, env.grabador.n))
            elif orden[0] == "cargar":              # seguir desde lo ya guardado
                modelo = PPO.load(os.path.join(CARPETA, f"{rol}.zip"), env=env, device="cpu")
                salida.put(("listo", rol, -1, env.grabador.n))
            elif orden[0] == "ronda":
                n = orden[1]
                # El rival es la versión de la ronda anterior: ya guardada, así que no cambia
                rival = PPO.load(os.path.join(HISTORIAL, f"ronda_{n - 1:03d}", f"{otro}.zip"),
                                 device="cpu")
                env.set_oponente(desde_modelo(rival))
                modelo.learn(pasos, reset_num_timesteps=False)
                guardar_uno(modelo, rol, n)
                salida.put(("listo", rol, n, env.grabador.n))
    except BaseException:
        salida.put(("error", rol, traceback.format_exc()))


def drenar(intentos, emisor, ultimo_n, base):
    """Pasa al grabador los intentos que han ido mandando los trabajadores."""
    while True:
        try:
            _, rol, n, frames, info = intentos.get_nowait()
        except queue.Empty:
            return
        ultimo_n[rol] = n
        emisor.contados = base + ultimo_n["red"] + ultimo_n["pink"]    # corridas de las dos
        emisor.guardar(frames, info)


def esperar_listos(salida, intentos, emisor, ultimo_n, base, procesos, esperados):
    """Espera a que los trabajadores digan 'listo' (mientras recoge sus repeticiones)."""
    pendientes = set(esperados)
    while pendientes:
        drenar(intentos, emisor, ultimo_n, base)
        try:
            msg = salida.get(timeout=0.5)
        except queue.Empty:
            for rol, p in procesos.items():
                if rol in pendientes and not p.is_alive():
                    raise RuntimeError(f"El trabajador de {rol} se detuvo sin avisar.")
            continue
        if msg[0] == "error":
            raise RuntimeError(f"Error en el trabajador de {msg[1]}:\n{msg[2]}")
        ultimo_n[msg[1]] = msg[3]
        emisor.contados = base + ultimo_n["red"] + ultimo_n["pink"]
        pendientes.discard(msg[1])
    drenar(intentos, emisor, ultimo_n, base)


def main_paralelo():
    import multiprocessing as mp
    ctx = mp.get_context("spawn")                   # en Windows siempre es "spawn"
    gestor = ctx.Manager()
    salida, intentos = gestor.Queue(), gestor.Queue()
    ordenes = {"red": gestor.Queue(), "pink": gestor.Queue()}

    j0 = Juego()
    emisor = Emisor({"ancho": j0.ancho, "alto": j0.alto, "paredes": j0.paredes,
                     "escaleras": j0.escaleras})

    ya_hechas = len(glob.glob(os.path.join(HISTORIAL, "ronda_*")))
    ruta_prog = os.path.join(CARPETA, "progreso.json")
    seguir = (os.path.exists(os.path.join(CARPETA, "red.zip")) and ya_hechas
              and os.path.exists(ruta_prog))
    base, filas = 0, []
    if seguir:
        print(f"Encontré IAs guardadas (ronda {ya_hechas - 1}): sigo desde ahí.", flush=True)
        with open(ruta_prog, encoding="utf-8") as f:
            previo = json.load(f)
        filas, base, primera = previo["filas"], previo.get("episodios", 0), ya_hechas
    else:
        primera = 1
    emisor.contados = base
    ultimo_n = {"red": 0, "pink": 0}                # corridas de cada trabajador desde que arrancó

    procesos = {rol: ctx.Process(target=trabajador, daemon=True,
                                 args=(rol, ordenes[rol], salida, intentos, CARPETA, PASOS_POR_RONDA))
                for rol in ("red", "pink")}
    for p in procesos.values():
        p.start()
    print("Entrenando con 2 núcleos: Red y Pink aprenden a la vez.", flush=True)
    try:
        for rol in procesos:
            ordenes[rol].put(("cargar",) if seguir else ("crear",))
        esperar_listos(salida, intentos, emisor, ultimo_n, base, procesos, procesos)
        if not seguir:
            red = PPO.load(os.path.join(HISTORIAL, "ronda_000", "red.zip"), device="cpu")
            pink = PPO.load(os.path.join(HISTORIAL, "ronda_000", "pink.zip"), device="cpu")
            filas = [{"ronda": 0, "segundos": 0, **evaluar(red, pink)}]
            print("Ronda 0 guardada: IAs recién nacidas, sin saber nada.", flush=True)
        ultima = primera + RONDAS - 1
        escribir_progreso(filas, ultima, emisor.contados)
        refrescar_visor()
        print("Abre la página para verlo en vivo.\n", flush=True)

        t0 = time.time()
        emisor.ronda = primera
        for rol in procesos:
            ordenes[rol].put(("ronda", primera))
        for ronda in range(primera, ultima + 1):
            esperar_listos(salida, intentos, emisor, ultimo_n, base, procesos, procesos)
            seg = round(time.time() - t0)
            emisor.volcar()
            if ronda < ultima:                      # la siguiente ronda empieza YA, mientras evalúo esta
                t0 = time.time()
                emisor.ronda = ronda + 1
                for rol in procesos:
                    ordenes[rol].put(("ronda", ronda + 1))
            red = PPO.load(os.path.join(HISTORIAL, f"ronda_{ronda:03d}", "red.zip"), device="cpu")
            pink = PPO.load(os.path.join(HISTORIAL, f"ronda_{ronda:03d}", "pink.zip"), device="cpu")
            fila = {"ronda": ronda, "segundos": seg, **evaluar(red, pink)}
            filas.append(fila)
            escribir_progreso(filas, ultima, emisor.contados)
            refrescar_visor()
            print(f"corridas totales: {emisor.contados} | ronda {ronda}/{ultima} ({seg} s) | "
                  f"gana red {fila['gana_red']}% pink {fila['gana_pink']}% ambos mueren {fila['ambos']}% | "
                  f"cogen pistola {fila['coge_pistola']}% | disparos/partida {fila['disparos']}", flush=True)
        print("\n¡Entrenamiento terminado!", flush=True)
        for rol in procesos:
            ordenes[rol].put(("fin",))
    finally:
        for p in procesos.values():
            p.join(timeout=5)
            if p.is_alive():
                p.terminate()
        gestor.shutdown()


def main_secuencial():
    """El modo de siempre: Red y Pink se turnan, en un solo núcleo (RVP_PARALELO=0)."""
    env_red = RedVsPinkEnv("red")        # sin bots: el rival es la otra IA
    env_pink = RedVsPinkEnv("pink")
    j0 = env_red.juego
    emisor = Emisor({"ancho": j0.ancho, "alto": j0.alto, "paredes": j0.paredes,
                     "escaleras": j0.escaleras})
    env_red.grabador = env_pink.grabador = emisor
    emisor.envs = (env_red, env_pink)

    ya_hechas = len(glob.glob(os.path.join(HISTORIAL, "ronda_*")))
    ruta_prog = os.path.join(CARPETA, "progreso.json")
    if (os.path.exists(os.path.join(CARPETA, "red.zip")) and ya_hechas
            and os.path.exists(ruta_prog)):
        print(f"Encontré IAs guardadas (ronda {ya_hechas - 1}): sigo desde ahí.")
        red = PPO.load(os.path.join(CARPETA, "red.zip"), env=env_red, device="cpu")
        pink = PPO.load(os.path.join(CARPETA, "pink.zip"), env=env_pink, device="cpu")
        with open(ruta_prog, encoding="utf-8") as f:
            previo = json.load(f)
        filas = previo["filas"]
        emisor.contados = previo.get("episodios", 0)   # seguimos contando desde ahí
        primera = ya_hechas
    else:
        red, pink = crear_ia(env_red), crear_ia(env_pink)
        guardar(red, pink, 0)                  # ronda 0 = recién nacidas
        fila0 = {"ronda": 0, "segundos": 0, **evaluar(red, pink)}
        filas = [fila0]
        primera = 1
        print("Ronda 0 guardada: IAs recién nacidas, sin saber nada.")
    ultima = primera + RONDAS - 1
    escribir_progreso(filas, ultima, emisor.contados)
    refrescar_visor()
    print("Abre panel_entrenamiento.html para verlo en vivo.\n")

    for ronda in range(primera, ultima + 1):
        t0 = time.time()
        emisor.ronda = ronda
        env_red.set_oponente(desde_modelo(pink))
        red.learn(PASOS_POR_RONDA, reset_num_timesteps=False)
        env_pink.set_oponente(desde_modelo(red))
        pink.learn(PASOS_POR_RONDA, reset_num_timesteps=False)
        guardar(red, pink, ronda)
        emisor.volcar()
        seg = round(time.time() - t0)
        fila = {"ronda": ronda, "segundos": seg, **evaluar(red, pink)}
        filas.append(fila)
        escribir_progreso(filas, ultima, emisor.contados)
        refrescar_visor()
        print(f"corridas totales: {emisor.contados} | ronda {ronda}/{ultima} ({seg} s) | gana red {fila['gana_red']}% "
              f"pink {fila['gana_pink']}% ambos mueren {fila['ambos']}% | "
              f"cogen pistola {fila['coge_pistola']}% | disparos/partida {fila['disparos']}")

    print("\n¡Entrenamiento terminado! Mira cómo juegan con:")
    print("    .\\venv\\Scripts\\python.exe generar_visor.py --abrir")


def main():
    if os.environ.get("RVP_PARALELO", "1") == "0":
        main_secuencial()
    else:
        main_paralelo()


if __name__ == "__main__":
    main()
