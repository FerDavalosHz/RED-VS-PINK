# entorno.py - Convierte "Red vs Pink" en un entorno de Gymnasium.
#
# Un entorno de Gymnasium es una "caja" con 3 funciones:
#     reset()       -> empieza una partida y devuelve lo que ve la IA
#     step(accion)  -> la IA hace algo y la caja devuelve:
#                      (lo que ve ahora, puntos ganados, ¿terminó?, ...)
#     action_space / observation_space -> qué puede hacer y qué puede ver
#
# Stable-Baselines3 sabe entrenar a cualquier IA que juegue en una caja así.
#
# Cada entorno es para UNA IA (el "rol": red o pink). El otro jugador lo
# controla el "oponente": un bot, una IA ya entrenada, etc.

import math
import os

import gymnasium as gym
import numpy as np
from gymnasium import spaces

import bots
import recompensas
from juego import (Juego, N_ACCIONES, RUTA_MAPA, MAX_TICKS, CALOR_MAX, RADIO,
                   RANGO_ESCOPETA, FPS, CALOR_PARA_COGER,
                   CADENCIA, ENFRIAR_EN_MANO, VIBORA_VIDA, VELOCIDAD)

FRAME_SKIP = 3        # la IA decide cada 3 ticks (10 veces por segundo)
VISION = 2            # mira una cuadrícula de (2*2+1) x (2*2+1) = 5x5 casillas

# ----------------------------------------------------------------------
# Lo que ve la IA: una lista de números. Cada número tiene un nombre para
# que el panel de neuronas pueda mostrar qué significa cada entrada.
# ----------------------------------------------------------------------
NOMBRES_OBS = (
    ["mi x", "mi y", "rival x", "rival y", "rival dx", "rival dy",
     "mis vidas", "vidas rival", "miro x", "miro y", "tiempo que queda",
     "mano vacia", "llevo caja", "llevo pistola", "llevo veneno", "mi calor",
     "rival pistola", "rival veneno", "rival caja",
     "estoy envenenado", "rival envenenado",
     "caja dx", "caja dy", "hay caja",
     "pistola dx", "pistola dy", "hay pistola", "pistola calor",
     "veneno dx", "veneno dy", "hay veneno",
     "recarga"]
    + [f"muro ({ox:+d},{oy:+d})" for oy in range(-VISION, VISION + 1)
       for ox in range(-VISION, VISION + 1)]
    # Al final (así los cerebros antiguos siguen valiendo): la víbora más cercana QUE VEN
    + ["víbora dx", "víbora dy", "hay víbora", "víbora cerca", "víbora vida"]
    # FÍSICA: con inercia importa lo rápido que vas (y el rival, si lo ves)
    + ["mi vel x", "mi vel y", "rival vel x", "rival vel y"]
)
N_OBS = len(NOMBRES_OBS)


def observar(j, nombre):
    """Lo que ve el jugador 'nombre' ahora mismo, como lista de números."""
    yo, en = j.jugador(nombre), j.rival(nombre)
    ob = []

    # VISIÓN: ¿veo al rival? Solo si está dentro de mi rango y sin muro ni caja en medio.
    # Si no lo veo, NO SÉ NADA de él: todo lo del rival se pone a 0.
    ve = j.ve(yo, en.x, en.y)
    # Mi posición y, si lo veo, la del rival y el vector hacia él (entre -1 y 1)
    ob += [yo.x / j.ancho, yo.y / j.alto]
    ob += ([en.x / j.ancho, en.y / j.alto, (en.x - yo.x) / j.ancho, (en.y - yo.y) / j.alto]
           if ve else [0.0, 0.0, 0.0, 0.0])
    # Vidas (las del rival, solo si lo veo), hacia dónde miro, tiempo que queda
    ob += [yo.vidas / 2, en.vidas / 2 if ve else 0.0, yo.dir[0], yo.dir[1],
           1 - j.turno / MAX_TICKS]
    # Qué llevo en la mano: vacío / caja / pistola / veneno
    tipo = yo.objeto["tipo"] if yo.objeto else ""
    ob += [tipo == "", tipo == "caja", tipo == "pistola", tipo == "veneno"]
    ob += [yo.objeto["calor"] / CALOR_MAX if tipo == "pistola" else 0.0]
    # Qué lleva el rival (solo si lo veo)
    tipo_en = en.objeto["tipo"] if (en.objeto and ve) else ""
    ob += [tipo_en == "pistola", tipo_en == "veneno", tipo_en == "caja"]
    # Veneno en el cuerpo
    ob += [yo.envenenado > 0, (en.envenenado > 0) and ve]

    # El objeto libre más cercano de cada tipo QUE VEO: hacia dónde está
    for t in ("caja", "pistola", "veneno"):
        mejor, mejor_d = None, 1e9
        for o in j.objetos:
            if o["tipo"] == t and o["dueno"] is None and j.ve(yo, o["x"], o["y"]):
                d = math.hypot(o["x"] - yo.x, o["y"] - yo.y)
                if d < mejor_d:
                    mejor, mejor_d = o, d
        if mejor is None:
            ob += [0.0, 0.0, 0.0] + ([0.0] if t == "pistola" else [])
        else:
            ob += [(mejor["x"] - yo.x) / j.ancho, (mejor["y"] - yo.y) / j.alto, 1.0]
            if t == "pistola":
                ob += [mejor["calor"] / CALOR_MAX]
    ob += [yo.recarga / CADENCIA]

    # Muros alrededor: 1 si hay pared, caja o borde; 0 si está libre
    cx0, cy0 = math.floor(yo.x), math.floor(yo.y)
    for oy in range(-VISION, VISION + 1):
        for ox in range(-VISION, VISION + 1):
            ob.append(1.0 if j.hay_obstaculo(cx0 + ox + 0.5, cy0 + oy + 0.5) else 0.0)

    # La víbora más cercana que veo (como con los objetos: lo que no veo, no lo sé)
    mejor, mejor_d = None, 1e9
    for v in j.viboras:
        d = math.hypot(v.x - yo.x, v.y - yo.y)
        if d < mejor_d and j.ve(yo, v.x, v.y):
            mejor, mejor_d = v, d
    if mejor is None:
        ob += [0.0, 0.0, 0.0, 0.0, 0.0]
    else:
        ob += [(mejor.x - yo.x) / j.ancho, (mejor.y - yo.y) / j.alto, 1.0,
               1.0 - mejor_d / max(j.rango_vision, 1e-6), mejor.vida / VIBORA_VIDA]

    # Velocidades (entre -1 y 1: 1 = a tope de velocidad). La del rival, solo si lo veo.
    ob += [yo.vx / VELOCIDAD, yo.vy / VELOCIDAD]
    ob += [en.vx / VELOCIDAD, en.vy / VELOCIDAD] if ve else [0.0, 0.0]

    return np.clip(np.array(ob, dtype=np.float32), -1.0, 1.0)


def ajustar_juego(j, v):
    """Aplica al juego los ajustes de recompensas.json que le afectan (visión y espera)."""
    j.fijar_vision(v["rango_vision"], v["campo_vision"])
    j.espera_coger = int(round(v["espera_coger"] * FPS))


def desde_modelo(modelo, deterministico=False):
    """Convierte una IA de Stable-Baselines3 en un 'oponente' para el entorno."""
    def jugar(obs, juego, nombre):
        accion, _ = modelo.predict(obs, deterministic=deterministico)
        return int(accion)
    return jugar


class RedVsPinkEnv(gym.Env):
    """Una IA (rol 'red' o 'pink') jugando contra un oponente."""

    metadata = {"render_modes": []}

    def __init__(self, rol="red", oponente=None, frame_skip=FRAME_SKIP,
                 ruta_mapa=RUTA_MAPA, premio_pistola=0.0,
                 premio_sostener=0.001, premio_perseguir=0.02, premio_disparo=0.05,
                 premio_huir=0.02, castigo_choque=0.003, castigo_bala_pared=0.03):
        super().__init__()
        assert rol in ("red", "pink")
        self.rol = rol
        # Ayuda opcional: puntos por coger la pistola la primera vez. Por defecto
        # 0 = SIN ayudas: la IA tiene que descubrir sola que la pistola sirve.
        self.premio_pistola = premio_pistola
        # INCENTIVOS (se pueden poner a 0 para quitarlos):
        #  - premio_sostener: un premio MUY pequeño por cada tick con la pistola en
        #    la mano (máx. 0.3 en una partida). Es lo que les hace querer cogerla:
        #    con 0, en las pruebas dejaron de cogerla por completo (rondas 7-8).
        #    No premia buscarla, solo tenerla. Además se gana por USARLA bien:
        #  - premio_perseguir: ganas por cada casilla que te ACERCAS al rival
        #    mientras llevas la pistola (y pierdes si te alejas).
        #  - premio_disparo: ganas por cada disparo CON PUNTERÍA, es decir, cuando
        #    el rival está justo delante tuyo en línea recta y sin pared en medio.
        #    Disparar a lo loco no da nada.
        #  Y para el que NO tiene la pistola:
        #  - premio_huir: mientras el RIVAL la lleva, ganas por cada casilla que
        #    te ALEJAS de él y pierdes por cada casilla que te acercas.
        #  Perseguir y huir se miden con la diferencia de distancia, así que ir
        #  y venir no suma nada: solo cuenta acercarse o alejarse de verdad.
        self.premio_sostener = premio_sostener
        self.premio_perseguir = premio_perseguir
        self.premio_disparo = premio_disparo
        self.premio_huir = premio_huir
        # CASTIGOS (puntos que se RESTAN):
        #  - castigo_choque: por cada tick que intentas moverte y chocas con una pared,
        #    una caja o el borde. Pegarte 1 segundo a una pared (30 ticks) = -0.09.
        #  - castigo_bala_pared: por cada bala que dispares y se estrelle contra una
        #    pared o una caja en vez de dar al rival.
        self.castigo_choque = castigo_choque
        self.castigo_bala_pared = castigo_bala_pared
        # Opcional: algo con .quiere() y .guardar(frames, info) que recibe los
        # intentos (partidas) para poder verlos en directo mientras entrena.
        self.grabador = None
        self._grabando = False
        self.enemigo = "pink" if rol == "red" else "red"
        self.frame_skip = frame_skip
        self.oponente = oponente or bots.aleatorio
        self.juego = Juego(ruta_mapa)
        # Los puntos se leen de recompensas.json (y se vuelven a leer si cambia).
        self.ruta_recompensas = recompensas.RUTA_RECOMPENSAS
        self.R = dict(recompensas.DEFECTOS)
        self._rec_fecha = "sin leer"
        self._cargar_recompensas()
        # Qué puede hacer: 7 acciones. Qué puede ver: N_OBS números entre -1 y 1.
        self.action_space = spaces.Discrete(N_ACCIONES)
        self.observation_space = spaces.Box(-1.0, 1.0, shape=(N_OBS,), dtype=np.float32)

    def set_oponente(self, oponente):
        """Cambia al rival (así hacemos el self-play)."""
        self.oponente = oponente

    def _cargar_recompensas(self):
        """Lee recompensas.json si ha cambiado: así cambias los puntos EN VIVO."""
        try:
            fecha = os.path.getmtime(self.ruta_recompensas)
        except OSError:
            fecha = None                       # no existe: valen los de por defecto
        if fecha == self._rec_fecha:
            return
        self._rec_fecha = fecha
        v = recompensas.leer(self.ruta_recompensas, anterior=self.R)
        self.R = v
        self.premio_sostener = v["sostener_escopeta"]
        self.premio_perseguir = v["perseguir"]
        self.premio_disparo = v["disparo_punteria"]
        self.premio_huir = v["huir"]
        self.castigo_choque = -v["choque_pared"]       # en el archivo es negativo
        self.castigo_bala_pared = -v["bala_pared"]
        self.prob_aleatoria = v["posiciones_aleatorias"] / 100.0   # 0 = siempre el mapa tal cual

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self._cargar_recompensas()
        self.juego.prob_aleatoria = self.prob_aleatoria
        ajustar_juego(self.juego, self.R)
        self.juego.reset()
        yo = self.juego.jugador(self.rol)
        # Lo que ya veo al empezar no cuenta como "descubierto": el premio es por BUSCAR.
        self._vistos = {id(o) for o in self.juego.objetos if self.juego.ve(yo, o["x"], o["y"])}
        self._visitadas = {(math.floor(yo.x), math.floor(yo.y))}
        self._vis_ticks = 0                         # cuánto me lleva viendo un tirador
        self._escapes = 0                           # cuántas veces me he escapado de uno
        self._premiados = set()                     # objetos por los que ya cobré el premio de cogerlos
        self._obj_objetivo = None                   # objeto hacia el que voy (para el premio de acercarme)
        self._dist_obj_prev = 0.0
        self._puntos = 0.0
        self._dist_prev = self._distancia()
        self._grabando = bool(self.grabador and self.grabador.quiere())
        self._frames = [self.juego.estado_compacto()] if self._grabando else None
        return observar(self.juego, self.rol), {}

    def step(self, accion):
        j = self.juego
        # El rival decide UNA vez y mantiene su acción durante el frame_skip
        obs_rival = observar(j, self.enemigo)
        a_rival = int(self.oponente(obs_rival, j, self.enemigo))
        a_yo = int(accion)

        recompensa = 0.0
        for _ in range(self.frame_skip):
            if self.rol == "red":
                j.paso(a_yo, a_rival)
            else:
                j.paso(a_rival, a_yo)
            recompensa += self._recompensa()
            if j.ganador() is not None:
                break

        self._puntos += recompensa
        terminado = j.ganador() is not None
        if self._grabando:                          # una foto por decisión (10 por segundo)
            self._frames.append(j.estado_compacto())
            if terminado:                           # el intento acabó: se manda a ver
                self.grabador.guardar(self._frames, {
                    "rol": self.rol, "ganador": j.ganador(), "puntos": self._puntos,
                    "vision": j.rango_vision, "campo_vision": j.campo_vision,
                    # qué mapa y qué puntos estaba usando esta partida (para el aviso "en uso")
                    "uso": {"mapa": getattr(j, "_mtime", None), "recompensas": self._rec_fecha},
                    # el mapa de ESTE intento (puede cambiar mientras entrenas)
                    "mapa": {"ancho": j.ancho, "alto": j.alto,
                             "paredes": j.paredes, "escaleras": j.escaleras}})
                self._grabando = False
        return (observar(j, self.rol), recompensa, terminado, False,
                {"ganador": j.ganador()})

    def _peso(self, objeto):
        """Los premios por encontrar, ir hacia y coger un objeto valen MÁS si es la escopeta."""
        return self.R["multiplicador_escopeta"] if objeto["tipo"] == "pistola" else 1.0

    def _distancia(self):
        """Distancia en casillas entre los dos jugadores."""
        a, b = self.juego.red, self.juego.pink
        return math.hypot(a.x - b.x, a.y - b.y)

    def _apunta_al_rival(self):
        """¿El rival está justo delante de mí, en línea recta y sin obstáculos?"""
        yo, en = self.juego.jugador(self.rol), self.juego.rival(self.rol)
        dx, dy = yo.dir
        vx, vy = en.x - yo.x, en.y - yo.y
        delante = vx * dx + vy * dy                    # cuánto está delante (+) o detrás (-)
        al_lado = abs(vx * dy - vy * dx)               # cuánto se desvía de mi línea
        # El abanico se abre con la distancia: cuanto más lejos, más ancho (hasta RANGO)
        if (delante <= 0 or delante > RANGO_ESCOPETA
                or al_lado > RADIO + delante * math.tan(0.3)):
            return False
        pasos = max(1, int(delante / 0.25))
        for i in range(1, pasos):                  # ¿hay pared o caja en medio?
            t = i / pasos
            if self.juego.hay_obstaculo(yo.x + vx * t, yo.y + vy * t):
                return False
        return True

    def _recompensa(self):
        """Los puntos de este tick. Esto es lo que 'enseña' a la IA."""
        r = 0.0
        for evento, quien in self.juego.eventos:
            if evento in ("golpe_bala", "golpe_veneno"):
                r += (self.R["vida_quitada"] if quien == self.enemigo
                      else self.R["vida_perdida"])           # quitar / perder una vida
            elif evento.startswith("coge_") and quien == self.rol:
                obj = self.juego.jugador(self.rol).objeto        # lo que acaba de coger
                if obj is not None and id(obj) not in self._premiados:
                    self._premiados.add(id(obj))                 # una vez por objeto y partida
                    r += self.R["coger_objeto"] * self._peso(obj)
            elif evento == "disparo" and quien == self.rol and self._apunta_al_rival():
                r += self.premio_disparo                       # disparo con puntería
            elif evento == "muerte_vibora" and quien == self.rol:
                r += self.R["morir_vibora"]                    # te mató la víbora
            elif evento == "mordida" and quien == self.rol:
                r += self.R["vida_perdida"]                    # una mordida es una vida perdida
            elif evento == "vibora_muerta" and quien == self.rol:
                r += self.R["matar_vibora"]
            elif evento == "choque" and quien == self.rol:
                r -= self.castigo_choque                       # te estampaste
            elif evento == "bala_pared" and quien == self.rol:
                r -= self.castigo_bala_pared                   # bala perdida
        # --- Incentivos pequeños (ver __init__) ---
        yo, en = self.juego.jugador(self.rol), self.juego.rival(self.rol)
        dist = self._distancia()
        if yo.objeto and yo.objeto["tipo"] == "pistola":
            r += self.premio_sostener                          # tenerla en la mano
            r += self.premio_perseguir * (self._dist_prev - dist)   # acercarte (+) / alejarte (-)
        if en.objeto and en.objeto["tipo"] == "pistola":
            r += self.premio_huir * (dist - self._dist_prev)   # alejarte (+) / acercarte (-)
        self._dist_prev = dist

        # --- Buscar y esconderse ---
        # Descubrir: un objeto entra por primera vez en mi rango de visión (una vez por objeto)
        if self.R["descubrir_objeto"] and len(self._vistos) < len(self.juego.objetos):
            for o in self.juego.objetos:
                if (o["dueno"] is None and id(o) not in self._vistos
                        and self.juego.ve(yo, o["x"], o["y"])):
                    self._vistos.add(id(o))
                    r += self.R["descubrir_objeto"] * self._peso(o)
        # Explorar: pisar una casilla que no había pisado en esta partida
        celda = (math.floor(yo.x), math.floor(yo.y))
        if celda not in self._visitadas:
            self._visitadas.add(celda)
            r += self.R["explorar"]
        # Ir hacia un objeto: con la mano vacía, premio por cada casilla que me acerco al objeto
        # que veo (la escopeta primero). Se mide con la diferencia de distancia: ir y venir no suma.
        objetivo = None
        if yo.objeto is None and self.R["acercarse_objeto"]:
            mejor_clave = None
            for o in self.juego.objetos:
                if o["dueno"] is not None or not self.juego.ve(yo, o["x"], o["y"]):
                    continue
                if o["tipo"] == "pistola" and o["calor"] > CALOR_PARA_COGER:
                    continue                                    # quema: no se puede coger
                d = math.hypot(o["x"] - yo.x, o["y"] - yo.y)
                clave = (o["tipo"] != "pistola", d)             # la escopeta tiene prioridad
                if mejor_clave is None or clave < mejor_clave:
                    mejor_clave, objetivo = clave, (o, d)
        if objetivo is not None:
            o, d = objetivo
            if id(o) == self._obj_objetivo:                     # sigo yendo hacia el mismo
                r += self.R["acercarse_objeto"] * self._peso(o) * (self._dist_obj_prev - d)
            self._obj_objetivo, self._dist_obj_prev = id(o), d
        else:
            self._obj_objetivo = None
        # Escapar de un tirador: el rival lleva la escopeta y me veía; dejo de estar a su vista
        if en.objeto and en.objeto["tipo"] == "pistola":
            if self.juego.ve(en, yo.x, yo.y):
                self._vis_ticks += 1
            else:
                if self._vis_ticks >= 15 and self._escapes < 5:     # me veía al menos 0.5 s
                    r += self.R["escapar_tirador"]
                    self._escapes += 1
                self._vis_ticks = 0
        else:
            self._vis_ticks = 0

        g = self.juego.ganador()
        if g is not None:
            r += self.R["ganar"] if g == self.rol else self.R["perder"]   # ganar / perder o empatar
        return r
