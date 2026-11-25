# juego.py - Las reglas de "Red vs Pink" (sin gráficos y sin IA).
#
# REGLAS:
#   - Dos jugadores: "red" (triángulo azul) y "pink" (cuadrado rosa), 2 vidas cada uno.
#   - Tiempo real: los dos se mueven A LA VEZ, 30 veces por segundo.
#   - Gana quien deja al otro sin vidas.
#   - Si pasan 20 segundos y nadie ha ganado, MUEREN LOS DOS.
#   - Tres objetos:
#       CAJA     -> sólida: tapa huecos y frena balas. Se puede coger y soltar.
#       ESCOPETA -> (en el código y en mapa.json se llama "pistola") lanza 5
#                   perdigones en abanico, alcance 7 casillas. Una salva quita
#                   como mucho 1 vida. Cada disparo la calienta (amarilla ->
#                   roja). Al llegar al máximo se SUELTA sola y hay que esperar a
#                   que se enfríe en el suelo.
#       VENENO   -> se lanza como una poción (acción "usar"): si toca al rival, pierde
#                   una vida 3 segundos después. O se BEBE (acción "coger/soltar" con
#                   el veneno en la mano): quien lo bebe muere al instante.
#   - VISIÓN: cada jugador solo ve lo que está dentro de su rango de visión (8
#     casillas) y sin muro ni caja en medio. Lo demás no lo sabe.
#   - Coger o soltar algo obliga a esperar 2 segundos antes de poder volver a hacerlo.
#   - VÍBORA: un bicho que NO es una IA, es un algoritmo. Si ve a alguien (rango y sin
#     muros en medio) lo persigue, despacio. Si lo pierde de vista, va hasta donde lo vio
#     por última vez. Una mordida quita una vida (1 vez por segundo). Aguanta 20 perdigones.
#   - El mapa (paredes, objetos, salidas) se lee de mapa.json.
#   - FÍSICA (con la librería pymunk): los jugadores tienen peso e inercia (aceleran
#     y frenan, no se paran en seco), chocan entre ellos y se empujan. Las cajas del
#     suelo se pueden EMPUJAR y se deslizan un poco; si sueltas una caja corriendo,
#     sale lanzada. Los perdigones empujan a quien golpean (y a las cajas), y la
#     mordida de la víbora te aparta de un golpe.

import json
import math
import os
import random

import pymunk

# ---- DÓNDE ESTÁ EL MAPA ----
# Por defecto: el archivo mapa.json que está junto a este juego.py.
# Si algún día quieres otro sitio, cambia SOLO esta línea.
RUTA_MAPA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mapa.json")

# ---- Partida ----
VIDAS_INICIALES = 2

# ---- TIEMPO REAL ----
FPS = 30                    # trocitos de tiempo por segundo (ticks)
DT = 1.0 / FPS              # lo que dura cada trocito, en segundos
TIEMPO_MAX = 20             # segundos: si nadie gana, MUEREN LOS DOS
MAX_TICKS = TIEMPO_MAX * FPS

VELOCIDAD = 6.0             # casillas por SEGUNDO
RADIO = 0.4                 # "tamaño" del jugador: casi una casilla

# ---- ACCIONES: la IA elige un número del 0 al 6 ----
QUIETO, ARRIBA, ABAJO, IZQUIERDA, DERECHA, USAR, COGER = range(7)
N_ACCIONES = 7
NOMBRES_ACCIONES = ["quieto", "arriba", "abajo", "izquierda", "derecha",
                    "usar", "coger/soltar"]

# Para cada movimiento: cuánto cambia (x, y). Arriba es y más pequeña.
MOVIMIENTOS = {
    QUIETO:    (0, 0),
    ARRIBA:    (0, -1),
    ABAJO:     (0, 1),
    IZQUIERDA: (-1, 0),
    DERECHA:   (1, 0),
}

# ---- OBJETOS ----
DIST_COGER = 1.3            # a qué distancia puedes coger un objeto
CADENCIA = int(0.8 * FPS)   # ticks entre disparo y disparo (la escopeta recarga lenta)
CALOR_POR_DISPARO = 0.38    # 3 disparos y la escopeta se pone al rojo (algo se enfría entre disparos)
CALOR_MAX = 1.0
CALOR_PARA_COGER = 0.5      # si está más caliente que esto, no se puede coger
ENFRIAR_EN_MANO = 0.05      # calor que pierde por segundo en la mano
ENFRIAR_EN_SUELO = 0.25     # calor que pierde por segundo en el suelo
VEL_BALA = 18.0             # casillas por segundo
# ESCOPETA: cada disparo lanza 5 perdigones en abanico y se apagan a los 7 casillas.
RANGO_ESCOPETA = 7.0
ABANICO = (-0.3, -0.15, 0.0, 0.15, 0.3)   # ángulo (radianes) de cada perdigón
VEL_POCION = 10.0
TIEMPO_VENENO = 3           # segundos hasta que el veneno quita la vida

# ---- VÍBORA (es un algoritmo, no un modelo) ----
VIBORA_VIDA = 20            # perdigones que aguanta (cada perdigón que le da quita 1)
VIBORA_VEL = 2.0            # casillas por segundo (los jugadores van a 6: es lenta)
VIBORA_RADIO = 0.45
VIBORA_RANGO = 7.0          # hasta dónde ve a los jugadores (casillas)
VIBORA_MORDIDA = FPS        # ticks entre una mordida y la siguiente (1 segundo)

# ---- VISIÓN Y ESPERA (el entrenamiento los lee de recompensas.json, se cambian en la página) ----
RANGO_VISION = 8.0          # casillas. Lo que está más lejos, o detrás de un muro o una caja, NO se ve
CAMPO_VISION = 180.0        # grados que abarca su vista, hacia donde miran. 180 = no ven a su espalda
ESPERA_COGER = 2.0          # segundos que hay que esperar entre un coger/soltar y el siguiente

# ---- FÍSICA (pymunk). Las distancias van en casillas y el tiempo en segundos ----
ACELERACION = 40.0          # casillas/s² que puede ganar (o perder) de velocidad un jugador:
                            # llega a la velocidad máxima en ~0,15 s y frena en lo mismo
MASA_JUGADOR = 1.0
MASA_CAJA = 3.0             # pesa el triple que un jugador: empujarla cuesta (vas más lento)
LADO_CAJA = 0.96            # un pelín menos de 1 casilla, para que quepa por pasillos de 1
FRENO_CAJA = 0.80           # cada tick la caja conserva este % de su velocidad (rozamiento con el suelo)
EMPUJE_BALA = 3.0           # velocidad que da un perdigón a quien golpea (casillas/s)
EMPUJE_BALA_CAJA = 0.6      # velocidad que da cada perdigón a una caja
EMPUJE_MORDIDA = 5.0        # la víbora te aparta de un golpe al morder
SUBPASOS = 2                # la física se calcula 2 veces por tick: más precisa
TIPO_PARED, TIPO_CAJA, TIPO_JUGADOR = 1, 2, 3   # etiquetas para saber con qué se choca


def cargar_mapa(ruta=RUTA_MAPA):
    """Lee el archivo del mapa y lo devuelve como diccionario de Python."""
    if not os.path.exists(ruta):
        raise FileNotFoundError(
            f"No encuentro el mapa en: {ruta}\n"
            "Guárdalo desde editor_mapa.html y ponlo ahí."
        )
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


class Jugador:
    """Un jugador: nombre, posición, vidas, hacia dónde mira y qué lleva."""

    def __init__(self, nombre, x, y, mirada):
        self.nombre = nombre
        # El CUERPO físico: un círculo con peso. Momento infinito = no gira.
        self.cuerpo = pymunk.Body(MASA_JUGADOR, float("inf"))
        self.cuerpo.position = (x, y)
        self.forma = pymunk.Circle(self.cuerpo, RADIO)
        self.forma.friction = 0.0          # resbala por las paredes en vez de quedarse pegado
        self.forma.elasticity = 0.0        # no rebota
        self.forma.collision_type = TIPO_JUGADOR
        self.leer_cuerpo()
        self.quiere = (0, 0)              # hacia dónde intenta moverse en este tick
        self.vidas = VIDAS_INICIALES
        self.dir = mirada          # hacia dónde mira (dx, dy): es hacia donde dispara
        self.objeto = None         # el objeto que lleva en la mano (o None)
        self.envenenado = 0        # ticks que faltan para que el veneno haga efecto
        self.recarga = 0           # ticks hasta poder volver a disparar
        self.espera_coger = 0      # ticks hasta poder volver a coger o soltar algo

    # x, y, vx, vy: copia rápida de lo que dice el cuerpo físico (preguntarle a pymunk
    # cada vez es lento). Se actualiza tras cada paso de física con leer_cuerpo().
    # Al cambiar x o y a mano, el cuerpo físico se teletransporta ahí.
    def leer_cuerpo(self):
        (self._x, self._y), (self.vx, self.vy) = self.cuerpo.position, self.cuerpo.velocity

    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, valor):
        self._x = valor
        self.cuerpo.position = (valor, self._y)

    @property
    def y(self):
        return self._y

    @y.setter
    def y(self, valor):
        self._y = valor
        self.cuerpo.position = (self._x, valor)

    @property
    def vivo(self):
        return self.vidas > 0


class Vibora:
    """La víbora: persigue al que ve. Su "cerebro" son unas pocas reglas, sin aprender nada."""

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.vida = VIBORA_VIDA
        self.dir = (1, 0)          # hacia dónde se arrastra (solo para dibujarla)
        self.meta = None           # último sitio donde vio a alguien (x, y)
        self.ruta = []             # casillas por las que va hacia esa meta
        self.recalcular = 0        # ticks hasta volver a calcular la ruta
        self.mordida = 0           # ticks hasta poder volver a morder


class Juego:
    """Guarda todo el estado de la partida y sabe avanzar un trocito de tiempo."""

    def __init__(self, ruta_mapa=RUTA_MAPA):
        self.ruta_mapa = ruta_mapa
        self.mapa = cargar_mapa(ruta_mapa)
        self._mtime = os.path.getmtime(ruta_mapa)   # cuándo se guardó el mapa por última vez
        # Probabilidad (0 a 1) de que una partida empiece con Red, Pink y los objetos
        # en sitios al azar. 0 = siempre como en el mapa. El entrenamiento lo sube.
        self.prob_aleatoria = 0.0
        self.fijar_vision(RANGO_VISION, CAMPO_VISION)  # hasta dónde y con qué ángulo ven
        self.espera_coger = int(ESPERA_COGER * FPS)    # espera entre coger/soltar (ticks)
        self._aplicar_mapa()
        self.reset()

    def _aplicar_mapa(self):
        self.ancho = self.mapa["ancho"]
        self.alto = self.mapa["alto"]
        self.paredes = self.mapa["paredes"]
        self.escaleras = self.mapa.get("escaleras", [])
        # Zonas de salida dibujadas en el editor (listas de rectángulos). Si están
        # vacías, las salidas al azar usan todo el mapa alcanzable.
        self.spawn_jugadores = self.mapa.get("spawn_jugadores", [])
        self.spawn_objetos = self.mapa.get("spawn_objetos", [])
        self._comp = None                          # zonas conectadas: se recalculan con el mapa nuevo
        # Las casillas que ocupan las paredes, en un conjunto: preguntar "¿hay pared aquí?"
        # (y trazar líneas de visión) así es mucho más rápido que recorrer todas las paredes.
        self._celdas_muro = {(x, y) for p in self.paredes
                             for x in range(p["x"], p["x"] + p["w"])
                             for y in range(p["y"], p["y"] + p["h"])}

    def _cabe(self, x, y):
        """¿Cabe un jugador en (x, y), sin contar las cajas? (solo paredes y bordes)"""
        for cx in (x - RADIO, x + RADIO):
            for cy in (y - RADIO, y + RADIO):
                if not (0 <= cx < self.ancho and 0 <= cy < self.alto) or self.hay_pared(cx, cy):
                    return False
        return True

    def _componentes(self):
        """Las 'zonas conectadas' del mapa: grupos de casillas por las que se puede
        caminar de una a otra. Un cuarto cerrado es una zona y el exterior es otra.

        Devuelve (casilla -> nº de zona, lista con las casillas de cada zona).
        """
        if self._comp is None:
            libres = {(x, y) for x in range(self.ancho) for y in range(self.alto)
                      if self._cabe(x + 0.5, y + 0.5)}
            comp_de, comps = {}, []
            for inicio in libres:
                if inicio in comp_de:
                    continue
                n, zona, pendientes = len(comps), [], [inicio]
                comp_de[inicio] = n
                while pendientes:
                    x, y = pendientes.pop()
                    zona.append((x, y))
                    for v in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if v in libres and v not in comp_de:
                            comp_de[v] = n
                            pendientes.append(v)
                comps.append(zona)
            self._comp = (comp_de, comps)
        return self._comp

    def _zona_principal(self):
        """Las casillas de la zona conectada donde está Red en el mapa: el cuarto que
        diseñaste. Si Red no está en una casilla válida, la zona más grande."""
        comp_de, comps = self._componentes()
        if not comps:
            return []
        roja = next((o for o in self.mapa["objetos"] if o["tipo"] == "red"), None)
        n = comp_de.get((roja["x"], roja["y"])) if roja else None
        if n is None:
            n = max(range(len(comps)), key=lambda i: len(comps[i]))
        return comps[n]

    @staticmethod
    def _en_zonas(zonas, celdas):
        """Las casillas que caen dentro de alguno de los rectángulos (o todas, si no hay)."""
        if not zonas:
            return list(celdas)
        return [c for c in celdas
                if any(z["x"] <= c[0] < z["x"] + z["w"] and z["y"] <= c[1] < z["y"] + z["h"]
                       for z in zonas)]

    def _spawn_invalido(self):
        """¿Hay algo colocado encima de un sólido? (jugador en pared o caja, objeto en pared)"""
        for jug in (self.red, self.pink):
            if not self._cabe(jug.x, jug.y) or self.hay_caja(jug.x, jug.y):
                return True
        return any(self.hay_pared(o["x"], o["y"]) for o in self.objetos)

    def _colocar_al_azar(self, todo=False):
        """Red, Pink y los objetos en casillas al azar.

        - Solo casillas alcanzables: nunca encima de paredes ni encerrados.
        - Con zonas de salida dibujadas en el editor, solo dentro de ellas.
        - Lo que NO tiene su zona dibujada se queda donde lo pusiste en el mapa
          (salvo que no haya ninguna zona: entonces todo sale al azar por el mapa).
        - 'todo=True' mueve también lo que no tiene zona (para arreglar algo que el
          mapa dejó encima de un sólido).
        - Nada se coloca encima de otra cosa.
        Si no hay sitio suficiente, no cambia nada.
        """
        sin_zonas = not self.spawn_jugadores and not self.spawn_objetos
        mover_jug = todo or bool(self.spawn_jugadores) or sin_zonas
        mover_obj = todo or bool(self.spawn_objetos) or sin_zonas
        comp_de, comps = self._componentes()
        base = self._zona_principal()               # el cuarto donde está Red en tu mapa
        if not base:
            return
        # Jugadores: dentro de TU zona (aunque sea un cuarto cerrado) o, si no hay, en el cuarto
        # base. Siempre en una sola zona conectada, para que se puedan encontrar.
        if mover_jug:
            celdas = self._en_zonas(self.spawn_jugadores, comp_de.keys()) if self.spawn_jugadores \
                else list(base)
            por_comp = {}
            for c in celdas:
                por_comp.setdefault(comp_de[c], []).append(c)
            validas = [n for n, cs in por_comp.items() if len(cs) >= 2]
            if validas:
                n_jug = random.choices(validas, weights=[len(por_comp[n]) for n in validas])[0]
                pool_jug = por_comp[n_jug]
            else:                                   # zona dibujada demasiado pequeña: el cuarto base
                n_jug = comp_de[base[0]]
                pool_jug = list(base)
        else:                                       # los jugadores se quedan donde están
            n_jug = comp_de.get((math.floor(self.red.x), math.floor(self.red.y)), comp_de[base[0]])
            pool_jug = []
        # Objetos: dentro de su zona, pero en la MISMA zona conectada que los jugadores
        # (así siempre se pueden alcanzar, y nunca aparecen fuera de tu cuarto).
        zona_obj = comps[n_jug]
        pool_obj = self._en_zonas(self.spawn_objetos, zona_obj) if self.spawn_objetos \
            else list(zona_obj)
        if len(pool_obj) < len(self.objetos):
            pool_obj = list(zona_obj)
        random.shuffle(pool_jug)
        random.shuffle(pool_obj)
        colocados = []                              # centros ya usados
        if not mover_jug:                           # lo que se queda quieto también ocupa sitio
            colocados += [(self.red.x, self.red.y), (self.pink.x, self.pink.y)]
        if not mover_obj:
            colocados += [(o["x"], o["y"]) for o in self.objetos]

        def siguiente(pool, distancia_min):
            for c in pool:
                x, y = c[0] + 0.5, c[1] + 0.5
                if all(math.hypot(x - a, y - b) >= distancia_min for a, b in colocados):
                    pool.remove(c)
                    colocados.append((x, y))
                    return x, y
            return None

        sitios_jug = sitios_obj = None
        if mover_jug:
            red = siguiente(pool_jug, 0)
            pink = None
            for d in (5, 3, 1):                     # Pink lejos de Red (si la zona es pequeña, menos)
                pink = siguiente(pool_jug, d)
                if pink:
                    break
            sitios_jug = [red, pink]
        if mover_obj:
            sitios_obj = [siguiente(pool_obj, 2) or siguiente(pool_obj, 1) for _ in self.objetos]
        if (sitios_jug and None in sitios_jug) or (sitios_obj and None in sitios_obj):
            return                                  # no hay sitio: se queda el mapa tal cual
        if sitios_jug:
            (self.red.x, self.red.y), (self.pink.x, self.pink.y) = sitios_jug
        if sitios_obj:
            for obj, (x, y) in zip(self.objetos, sitios_obj):
                obj["x"], obj["y"] = x, y

    def _colocar_viboras(self, al_azar):
        """Las víboras salen donde las pusiste; con posiciones al azar, en un sitio al azar
        (lejos de los jugadores). Si una quedó encima de un muro o una caja, también se mueve."""
        if not self.viboras:
            return
        base = self._zona_principal()
        if not base:
            return
        for v in self.viboras:
            if not al_azar and self._cabe(v.x, v.y) and not self.hay_caja(v.x, v.y):
                continue
            pool = self._en_zonas(self.spawn_objetos, base) or list(base)
            lejos = [c for c in pool
                     if min(math.hypot(c[0] + 0.5 - j.x, c[1] + 0.5 - j.y)
                            for j in (self.red, self.pink)) >= VIBORA_RANGO + 1
                     and not self.hay_caja(c[0] + 0.5, c[1] + 0.5)]
            if not lejos:
                lejos = [c for c in base if not self.hay_caja(c[0] + 0.5, c[1] + 0.5)]
            if lejos:
                c = random.choice(lejos)
                v.x, v.y = c[0] + 0.5, c[1] + 0.5

    def recargar_mapa_si_cambio(self):
        """Si has guardado un mapa.json nuevo, empieza a usarlo (sin parar nada).

        Si el archivo está a medio guardar o tiene errores, se queda con el
        mapa anterior y vuelve a intentarlo en la siguiente partida.
        """
        try:
            fecha = os.path.getmtime(self.ruta_mapa)
            if fecha == self._mtime:
                return False
            nuevo = cargar_mapa(self.ruta_mapa)
            if not all(k in nuevo for k in ("ancho", "alto", "paredes", "objetos")):
                return False
            tipos = {o["tipo"] for o in nuevo["objetos"]}
            if not {"red", "pink"} <= tipos:
                return False                         # sin Red y Pink no se puede jugar
        except Exception:
            return False
        self.mapa, self._mtime = nuevo, fecha
        self._aplicar_mapa()
        return True

    def reset(self):
        """Empieza una partida nueva con todo como está en el mapa."""
        self.recargar_mapa_si_cambio()
        salidas = {o["tipo"]: o for o in self.mapa["objetos"]
                   if o["tipo"] in ("red", "pink")}
        if "red" not in salidas or "pink" not in salidas:
            raise ValueError("El mapa necesita a Red y a Pink.")
        # +0.5 para colocarlos en el CENTRO de su casilla
        self.red = Jugador("red", salidas["red"]["x"] + 0.5,
                           salidas["red"]["y"] + 0.5, (1, 0))
        self.pink = Jugador("pink", salidas["pink"]["x"] + 0.5,
                            salidas["pink"]["y"] + 0.5, (-1, 0))
        # Los objetos se copian para poder cambiarlos sin estropear el mapa.
        self.objetos = [
            {"tipo": o["tipo"], "x": o["x"] + 0.5, "y": o["y"] + 0.5,
             "calor": 0.0, "dueno": None}
            for o in self.mapa["objetos"] if o["tipo"] not in ("red", "pink", "vibora")
        ]
        self.viboras = [Vibora(o["x"] + 0.5, o["y"] + 0.5)
                        for o in self.mapa["objetos"] if o["tipo"] == "vibora"]
        self.proyectiles = []      # perdigones y pociones en el aire
        self.salva = 0             # número de la última salva disparada
        # Posiciones al azar (si toca), o si el mapa dejó algo encima de un sólido
        al_azar = self.prob_aleatoria > 0 and random.random() < self.prob_aleatoria
        if al_azar or self._spawn_invalido():
            self._colocar_al_azar(todo=not al_azar)
        self._colocar_viboras(al_azar)
        self._crear_mundo()
        self.eventos = []          # lo que ha pasado en el último tick
        self.turno = 0             # ticks transcurridos

    # ------------------------------------------------------------------
    # El mundo físico (pymunk)
    # ------------------------------------------------------------------
    def _crear_mundo(self):
        """Crea el 'espacio' de pymunk: paredes fijas, bordes, jugadores y cajas."""
        self.espacio = pymunk.Space()          # sin gravedad: el juego se ve desde arriba
        self.espacio.collision_slop = 0.005    # cuánto se permite que se solapen (casi nada)
        fijo = self.espacio.static_body
        A, H = self.ancho, self.alto
        rects = [(p["x"], p["y"], p["w"], p["h"]) for p in self.paredes]
        # Los 4 bordes del campo, como paredes gruesas por fuera
        rects += [(-1, -1, A + 2, 1), (-1, H, A + 2, 1), (-1, 0, 1, H), (A, 0, 1, H)]
        for x, y, w, h in rects:
            forma = pymunk.Poly(fijo, [(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
            forma.friction, forma.elasticity = 0.0, 0.0
            forma.collision_type = TIPO_PARED
            self.espacio.add(forma)
        for jug in (self.red, self.pink):
            self.espacio.add(jug.cuerpo, jug.forma)
        self._sincronizar_cajas()

    def _sincronizar_cajas(self):
        """Pone en el mundo físico las cajas que están en el suelo (y quita las que
        alguien lleva en la mano). Si alguien movió una caja 'a mano' (cambiando su
        x, y), el cuerpo físico se va con ella."""
        for o in self.objetos:
            if o["tipo"] != "caja":
                continue
            cuerpo = o.get("_cuerpo")
            if o["dueno"] is not None:         # en la mano: fuera del mundo físico
                if cuerpo is not None and cuerpo.space is self.espacio:
                    self.espacio.remove(cuerpo, o["_forma"])
                continue
            if cuerpo is None:
                cuerpo = pymunk.Body(MASA_CAJA, float("inf"))   # no gira: siempre recta
                forma = pymunk.Poly.create_box(cuerpo, (LADO_CAJA, LADO_CAJA))
                forma.friction, forma.elasticity = 0.0, 0.0
                forma.collision_type = TIPO_CAJA
                o["_cuerpo"], o["_forma"], o["_sync"] = cuerpo, forma, None
            if cuerpo.space is not self.espacio:
                if cuerpo.space is not None:
                    cuerpo.space.remove(cuerpo, o["_forma"])
                self.espacio.add(cuerpo, o["_forma"])
            if o["_sync"] != (o["x"], o["y"]):
                cuerpo.position = (o["x"], o["y"])
                o["_sync"] = (o["x"], o["y"])

    def _fisica(self):
        """Mueve el mundo un tick: los jugadores aceleran hacia donde quieren ir,
        las cajas frenan por el rozamiento, y pymunk resuelve todos los choques."""
        self._sincronizar_cajas()
        # FUERZAS (empujones) de este tick. Se usan fuerzas y no se cambia la velocidad
        # a mano: así pymunk puede separar bien a dos cosas que chocan.
        fuerzas = []
        for jug in (self.red, self.pink):
            qx, qy = jug.quiere if jug.vivo else (0, 0)
            vx, vy = jug.cuerpo.velocity
            # Cambio de velocidad que quiere, limitado por la aceleración máxima
            cx, cy = qx * VELOCIDAD - vx, qy * VELOCIDAD - vy
            cambio = math.hypot(cx, cy)
            maximo = ACELERACION * DT
            if cambio > maximo:
                cx, cy = cx / cambio * maximo, cy / cambio * maximo
            fuerzas.append((jug.cuerpo, (cx / DT * MASA_JUGADOR, cy / DT * MASA_JUGADOR)))
        for o in self.objetos:                 # rozamiento de las cajas con el suelo
            if o["tipo"] == "caja" and o["dueno"] is None:
                v = o["_cuerpo"].velocity
                if v.length < 0.05:
                    o["_cuerpo"].velocity = (0, 0)
                else:
                    f = -(1 - FRENO_CAJA) / DT * MASA_CAJA
                    fuerzas.append((o["_cuerpo"], (v.x * f, v.y * f)))
        for _ in range(SUBPASOS):
            for cuerpo, f in fuerzas:          # pymunk borra las fuerzas tras cada paso
                cuerpo.force = f
            self.espacio.step(DT / SUBPASOS)
        self.red.leer_cuerpo()
        self.pink.leer_cuerpo()
        # Las cajas guardan su nueva posición
        for o in self.objetos:
            if o["tipo"] == "caja" and o["dueno"] is None:
                p = o["_cuerpo"].position
                o["x"], o["y"] = p.x, p.y
                o["_sync"] = (o["x"], o["y"])
        # ¿Alguien empujó contra una pared? (evento "choque")
        for jug in (self.red, self.pink):
            if jug.quiere != (0, 0) and self._contra_pared(jug):
                self.eventos.append(("choque", jug.nombre))

    def _contra_pared(self, jug):
        """¿Está el jugador tocando una pared (o borde) en la dirección en que empuja?"""
        dx, dy = jug.quiere
        choca = False

        def mirar(arb):
            nonlocal choca
            a, b = arb.shapes
            otra = b if a is jug.forma else a
            if otra.collision_type != TIPO_PARED:
                return
            n = arb.normal if a is jug.forma else -arb.normal   # de mí hacia la pared
            if n.x * dx + n.y * dy > 0.7:
                choca = True

        jug.cuerpo.each_arbiter(mirar)
        return choca

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    def jugador(self, nombre):
        return self.red if nombre == "red" else self.pink

    def rival(self, nombre):
        return self.pink if nombre == "red" else self.red

    def hay_pared(self, x, y):
        """¿Hay una pared en el punto (x, y)?"""
        return (math.floor(x), math.floor(y)) in self._celdas_muro

    def fijar_vision(self, rango, grados):
        """Cuánto y con qué ángulo ven los jugadores (rango en casillas, campo en grados)."""
        self.rango_vision = rango
        self.campo_vision = grados
        # coseno del medio ángulo: más de 360° = ven en todas direcciones
        self._cos_campo = math.cos(math.radians(grados / 2)) if grados < 360 else -2.0

    def ve(self, quien, x, y):
        """¿Puede el jugador 'quien' ver el punto (x, y)?

        Solo si está dentro de su rango de visión, DELANTE de él (dentro del ángulo hacia
        donde mira: no ve a su espalda) y sin una pared ni una caja en medio.
        Lo que no ve, no lo sabe.
        """
        dx, dy = x - quien.x, y - quien.y
        dist = math.hypot(dx, dy)
        if dist > self.rango_vision:
            return False
        if dist > 0.5 and self._cos_campo > -1.5:      # fuera de su campo de visión: a su espalda
            if (dx * quien.dir[0] + dy * quien.dir[1]) / dist < self._cos_campo - 1e-9:
                return False
        pasos = int(dist / 0.4)
        for i in range(1, pasos + 1):
            t = i / (pasos + 1)
            sx, sy = quien.x + dx * t, quien.y + dy * t
            if abs(sx - x) < 0.5 and abs(sy - y) < 0.5:
                continue                  # lo pegado al objetivo no lo tapa (una caja no se tapa a sí misma)
            if self.hay_obstaculo(sx, sy):
                return False
        return True

    def caja_en(self, x, y):
        """La caja del suelo que ocupa el punto (x, y), o None. Las cajas ya no van
        por casillas: pueden estar en cualquier sitio porque se empujan."""
        for o in self.objetos:
            if (o["tipo"] == "caja" and o["dueno"] is None
                    and abs(o["x"] - x) <= 0.5 and abs(o["y"] - y) <= 0.5):
                return o
        return None

    def hay_caja(self, x, y):
        """¿Hay una caja (soltada en el suelo) en el punto (x, y)?"""
        return self.caja_en(x, y) is not None

    def hay_obstaculo(self, x, y):
        """Borde del campo, pared o caja: cosas que nada puede atravesar."""
        if not (0 <= x < self.ancho and 0 <= y < self.alto):
            return True
        return self.hay_pared(x, y) or self.hay_caja(x, y)

    def puede_estar(self, x, y):
        """¿Cabe un jugador en (x, y)? Comprueba las 4 esquinas de su cuerpo."""
        for cx in (x - RADIO, x + RADIO):
            for cy in (y - RADIO, y + RADIO):
                if self.hay_obstaculo(cx, cy):
                    return False
        return True

    @property
    def tiempo(self):
        """Segundos que lleva la partida."""
        return self.turno * DT

    # ------------------------------------------------------------------
    # Movimiento
    # ------------------------------------------------------------------
    # (El movimiento ya no se hace aquí: la acción solo dice HACIA DÓNDE quiere ir
    #  el jugador, y _fisica() lo acelera y resuelve los choques.)

    def quitar_vida(self, jugador):
        if jugador.vivo:
            jugador.vidas -= 1
            if not jugador.vivo:
                jugador.envenenado = 0

    # ------------------------------------------------------------------
    # Acciones con objetos
    # ------------------------------------------------------------------
    def coger(self, jug):
        """Coge el objeto libre más cercano (si está a menos de DIST_COGER)."""
        mejor, mejor_d = None, DIST_COGER
        for o in self.objetos:
            if o["dueno"] is not None:
                continue
            if o["tipo"] == "pistola" and o["calor"] > CALOR_PARA_COGER:
                continue                       # quema demasiado
            d = math.hypot(o["x"] - jug.x, o["y"] - jug.y)
            if d <= mejor_d:
                mejor, mejor_d = o, d
        if mejor is not None:
            mejor["dueno"] = jug.nombre
            jug.objeto = mejor
            self.eventos.append(("coge_" + mejor["tipo"], jug.nombre))
            return True
        return False

    def beber(self, jug):
        """Se bebe la poción de veneno que lleva: muere al instante."""
        obj = jug.objeto
        if obj is not None and obj["tipo"] == "veneno":
            self.objetos.remove(obj)
            jug.objeto = None
            jug.vidas = 0
            jug.envenenado = 0
            self.eventos.append(("bebe_veneno", jug.nombre))
            return True
        return False

    def _hueco_para_caja(self, cx, cy, jug):
        """¿Cabe una caja con centro en (cx, cy) sin pisar nada?"""
        m = LADO_CAJA / 2
        if not (m <= cx <= self.ancho - m and m <= cy <= self.alto - m):
            return False
        for ex in (cx - m, cx + m):            # las 4 esquinas, sin pared
            for ey in (cy - m, cy + m):
                if self.hay_pared(ex, ey):
                    return False
        for o in self.objetos:                 # ni encima de otra caja
            if (o["tipo"] == "caja" and o["dueno"] is None
                    and abs(o["x"] - cx) < LADO_CAJA and abs(o["y"] - cy) < LADO_CAJA):
                return False
        # Ni encima de un jugador o de una víbora (no se aplasta a nadie)
        cuerpos = [(j.x, j.y, RADIO) for j in (self.red, self.pink)]
        cuerpos += [(v.x, v.y, VIBORA_RADIO) for v in self.viboras]
        for x, y, r in cuerpos:
            px = min(max(x, cx - m), cx + m)   # punto de la caja más cercano a ese cuerpo
            py = min(max(y, cy - m), cy + m)
            if math.hypot(x - px, y - py) < r:
                return False
        return True

    def soltar(self, jug):
        """Suelta lo que lleva. La caja se coloca justo delante; si ibas corriendo,
        sale lanzada con tu velocidad y se desliza hasta frenar."""
        obj = jug.objeto
        if obj is None:
            return False
        if obj["tipo"] == "caja":
            dx, dy = jug.dir
            sep = RADIO + LADO_CAJA / 2 + 0.03
            cx, cy = jug.x + dx * sep, jug.y + dy * sep
            if (dx, dy) == (0, 0) or not self._hueco_para_caja(cx, cy, jug):
                return False
            obj["x"], obj["y"] = cx, cy
            obj["dueno"] = None
            self._sincronizar_cajas()          # vuelve al mundo físico...
            obj["_cuerpo"].velocity = jug.cuerpo.velocity   # ...con tu velocidad
        else:
            obj["x"], obj["y"] = jug.x, jug.y
        obj["dueno"] = None
        jug.objeto = None
        self.eventos.append(("suelta_" + obj["tipo"], jug.nombre))
        return True

    def usar(self, jug):
        """Usa el objeto de la mano: disparar la pistola o lanzar el veneno."""
        obj = jug.objeto
        if obj is None:
            return
        dx, dy = jug.dir
        if obj["tipo"] == "pistola":
            if jug.recarga > 0 or obj["calor"] >= CALOR_MAX:
                return
            # Escopeta: 5 perdigones en abanico (el del medio es el "central")
            self.salva += 1
            base = math.atan2(dy, dx)
            for desvio in ABANICO:
                ang = base + desvio
                bala = {"tipo": "bala", "de": jug.nombre, "salva": self.salva,
                        "centro": desvio == 0.0, "rec": RANGO_ESCOPETA,
                        "x": jug.x, "y": jug.y,
                        "dx": math.cos(ang), "dy": math.sin(ang)}
                # Una víbora pegada a ti se come el perdigón nada más salir
                if self._golpea_vibora(bala):
                    continue
                bala["x"], bala["y"] = jug.x + dx * 0.5, jug.y + dy * 0.5
                if self._golpea_vibora(bala):
                    continue
                self.proyectiles.append(bala)
            jug.recarga = CADENCIA
            obj["calor"] = min(CALOR_MAX, obj["calor"] + CALOR_POR_DISPARO)
            self.eventos.append(("disparo", jug.nombre))
            if obj["calor"] >= CALOR_MAX:      # ¡al rojo! Se suelta sola.
                self.soltar(jug)
                self.eventos.append(("sobrecalentada", jug.nombre))
        elif obj["tipo"] == "veneno":
            self.proyectiles.append({"tipo": "pocion", "de": jug.nombre,
                                     "x": jug.x + dx * 0.5, "y": jug.y + dy * 0.5,
                                     "dx": dx, "dy": dy})
            self.objetos.remove(obj)           # la poción se gasta
            jug.objeto = None
            self.eventos.append(("lanza_veneno", jug.nombre))

    def aplicar_accion(self, jug, accion):
        if jug.recarga > 0:
            jug.recarga -= 1
        if jug.espera_coger > 0:
            jug.espera_coger -= 1
        jug.quiere = MOVIMIENTOS.get(accion, (0, 0))   # sin moverse = frena
        if accion in (ARRIBA, ABAJO, IZQUIERDA, DERECHA):
            jug.dir = MOVIMIENTOS[accion]
        elif accion == USAR:
            self.usar(jug)
        elif accion == COGER:
            if jug.espera_coger > 0:
                return                          # todavía en espera: pulsar no hace nada
            if jug.objeto is None:
                hecho = self.coger(jug)
            elif jug.objeto["tipo"] == "veneno":
                hecho = self.beber(jug)         # con el veneno en la mano, "coger/soltar" = BEBER
            else:
                hecho = self.soltar(jug)
            if hecho:                           # solo cuenta si de verdad cogió, soltó o bebió
                jug.espera_coger = self.espera_coger

    # ------------------------------------------------------------------
    # Lo que pasa solo en cada tick
    # ------------------------------------------------------------------
    def actualizar_objetos(self):
        for o in self.objetos:
            if o["dueno"] is not None:         # lo que llevas va contigo
                d = self.jugador(o["dueno"])
                o["x"], o["y"] = d.x, d.y
                if o["tipo"] == "pistola":
                    o["calor"] = max(0.0, o["calor"] - ENFRIAR_EN_MANO * DT)
            elif o["tipo"] == "pistola":
                o["calor"] = max(0.0, o["calor"] - ENFRIAR_EN_SUELO * DT)

    def mover_proyectiles(self):
        vivos = []
        salvas_con_golpe = set()       # una salva de escopeta quita como mucho UNA vida
        for p in self.proyectiles:
            if p.get("salva") in salvas_con_golpe:
                continue               # otro perdigón de su salva ya dio: este desaparece
            vel = VEL_BALA if p["tipo"] == "bala" else VEL_POCION
            n = max(1, math.ceil(vel * DT / 0.25))   # trocitos pequeños: sin atravesar
            d = vel * DT / n
            vive = True
            objetivo = self.rival(p["de"])
            for _ in range(n):
                p["x"] += p["dx"] * d
                p["y"] += p["dy"] * d
                if self.hay_obstaculo(p["x"], p["y"]):
                    vive = False               # choca y desaparece
                    caja = self.caja_en(p["x"], p["y"])
                    if caja is not None and p["tipo"] == "bala" and "_cuerpo" in caja:   # empuja la caja
                        caja["_cuerpo"].velocity += (p["dx"] * EMPUJE_BALA_CAJA,
                                                     p["dy"] * EMPUJE_BALA_CAJA)
                    if p.get("centro"):    # solo el perdigón central cuenta como disparo perdido
                        self.eventos.append(("bala_pared", p["de"]))
                    break
                if p["tipo"] == "bala" and self._golpea_vibora(p):
                    vive = False                   # el perdigón se queda en la víbora
                    break
                if objetivo.vivo and math.hypot(p["x"] - objetivo.x, p["y"] - objetivo.y) < RADIO:
                    if p["tipo"] == "bala":
                        # El golpe lo empuja hacia atrás
                        objetivo.cuerpo.velocity += (p["dx"] * EMPUJE_BALA, p["dy"] * EMPUJE_BALA)
                        self.quitar_vida(objetivo)
                        self.eventos.append(("golpe_bala", objetivo.nombre))
                        salvas_con_golpe.add(p["salva"])
                    elif objetivo.envenenado == 0:
                        objetivo.envenenado = TIEMPO_VENENO * FPS
                        self.eventos.append(("envenenado", objetivo.nombre))
                    vive = False
                    break
                if "rec" in p:                 # los perdigones se apagan al llegar a su alcance
                    p["rec"] -= d
                    if p["rec"] <= 0:
                        vive = False
                        break
            if vive:
                vivos.append(p)
        self.proyectiles = [p for p in vivos if p.get("salva") not in salvas_con_golpe]

    # ---- La víbora ----
    def _linea_libre(self, x0, y0, x1, y1):
        """¿Se puede ir en línea recta de un punto a otro sin chocar con un muro o una caja?"""
        dx, dy = x1 - x0, y1 - y0
        pasos = int(math.hypot(dx, dy) / 0.4)
        for i in range(1, pasos + 1):
            t = i / (pasos + 1)
            if self.hay_obstaculo(x0 + dx * t, y0 + dy * t):
                return False
        return True

    def _vibora_cabe(self, x, y):
        for cx in (x - 0.4, x + 0.4):
            for cy in (y - 0.4, y + 0.4):
                if self.hay_obstaculo(cx, cy):
                    return False
        return True

    def _ruta_vibora(self, v, meta):
        """Camino casilla a casilla (búsqueda en anchura) desde la víbora hasta 'meta'."""
        inicio = (math.floor(v.x), math.floor(v.y))
        fin = (math.floor(meta[0]), math.floor(meta[1]))
        if inicio == fin:
            return []
        previo = {inicio: None}
        cola = [inicio]
        i = 0
        while i < len(cola):
            c = cola[i]
            i += 1
            if c == fin:
                break
            for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + d[0], c[1] + d[1])
                if n in previo or not self._vibora_cabe(n[0] + 0.5, n[1] + 0.5):
                    continue
                previo[n] = c
                cola.append(n)
        if fin not in previo:
            return []
        ruta, c = [], fin
        while c != inicio:
            ruta.append((c[0] + 0.5, c[1] + 0.5))
            c = previo[c]
        ruta.reverse()
        return ruta

    def _vibora_avanza(self, v, hacia):
        """Un trocito hacia un punto. Devuelve False si no pudo moverse nada."""
        dx, dy = hacia[0] - v.x, hacia[1] - v.y
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return True
        paso = min(VIBORA_VEL * DT, dist)
        mx, my = dx / dist * paso, dy / dist * paso
        movido = False
        if self._vibora_cabe(v.x + mx, v.y):
            v.x += mx
            movido = movido or abs(mx) > 1e-9
        if self._vibora_cabe(v.x, v.y + my):
            v.y += my
            movido = movido or abs(my) > 1e-9
        if abs(dx) >= abs(dy):
            v.dir = (1 if dx > 0 else -1, 0)
        else:
            v.dir = (0, 1 if dy > 0 else -1)
        return movido

    def actualizar_viboras(self):
        for v in self.viboras:
            if v.mordida > 0:
                v.mordida -= 1
            # 1) ¿A quién ve? Al jugador vivo más cercano dentro de su rango y sin muros en medio.
            objetivo, mejor = None, 1e9
            for j in (self.red, self.pink):
                d = math.hypot(j.x - v.x, j.y - v.y)
                if j.vivo and d <= VIBORA_RANGO and d < mejor and self._linea_libre(v.x, v.y, j.x, j.y):
                    objetivo, mejor = j, d
            if objetivo is not None:
                v.meta = (objetivo.x, objetivo.y)       # lo recuerda: irá hasta donde lo vio
                if not self._vibora_avanza(v, v.meta):  # atascada en una esquina: busca camino
                    v.recalcular = 0
                    v.ruta = self._ruta_vibora(v, v.meta)
                    if v.ruta:
                        self._vibora_avanza(v, v.ruta[0])
                else:
                    v.ruta = []
            elif v.meta is not None:
                # 2) No ve a nadie: va hasta el último sitio donde vio a alguien
                if v.recalcular <= 0 or not v.ruta:
                    v.ruta = self._ruta_vibora(v, v.meta)
                    v.recalcular = 10
                v.recalcular -= 1
                if v.ruta:
                    if math.hypot(v.ruta[0][0] - v.x, v.ruta[0][1] - v.y) < 0.15:
                        v.ruta.pop(0)
                    if v.ruta:
                        self._vibora_avanza(v, v.ruta[0])
                if not v.ruta or math.hypot(v.meta[0] - v.x, v.meta[1] - v.y) < 0.3:
                    v.meta, v.ruta = None, []           # llegó y no hay nadie: se queda quieta
            # 3) Morder
            if v.mordida == 0:
                for j in (self.red, self.pink):
                    d = math.hypot(j.x - v.x, j.y - v.y)
                    if j.vivo and d < RADIO + VIBORA_RADIO:
                        if d > 1e-6:               # el mordisco te aparta de ella
                            j.cuerpo.velocity += ((j.x - v.x) / d * EMPUJE_MORDIDA,
                                                  (j.y - v.y) / d * EMPUJE_MORDIDA)
                        self.quitar_vida(j)
                        v.mordida = VIBORA_MORDIDA
                        self.eventos.append(("mordida", j.nombre))
                        if not j.vivo:
                            self.eventos.append(("muerte_vibora", j.nombre))
                        break

    def _golpea_vibora(self, p):
        """¿Este perdigón da a una víbora? Le quita 1 de vida; a 0 muere."""
        for v in self.viboras:
            if v.vida > 0 and abs(p["x"] - v.x) < VIBORA_RADIO and abs(p["y"] - v.y) < VIBORA_RADIO:
                v.vida -= 1
                self.eventos.append(("balazo_vibora", p["de"]))
                if v.vida <= 0:
                    self.eventos.append(("vibora_muerta", p["de"]))
                return True
        return False

    def actualizar_veneno(self):
        for jug in (self.red, self.pink):
            if jug.envenenado > 0:
                jug.envenenado -= 1
                if jug.envenenado == 0:
                    self.quitar_vida(jug)
                    self.eventos.append(("golpe_veneno", jug.nombre))

    # ------------------------------------------------------------------
    # Un trocito de tiempo
    # ------------------------------------------------------------------
    def paso(self, accion_red, accion_pink):
        """Avanza UN trocito de tiempo (1/30 s). Los dos actúan A LA VEZ."""
        if self.ganador() is not None:
            return                              # partida terminada
        self.eventos = []
        acciones = {"red": accion_red, "pink": accion_pink}
        # El orden se alterna cada tick para que ninguno tenga ventaja.
        orden = ("red", "pink") if self.turno % 2 == 0 else ("pink", "red")
        for nombre in orden:
            self.aplicar_accion(self.jugador(nombre), acciones[nombre])
        self._fisica()                          # los dos se mueven A LA VEZ y chocan
        self.actualizar_objetos()
        self.actualizar_viboras()
        self.mover_proyectiles()
        self.viboras = [v for v in self.viboras if v.vida > 0]
        self.actualizar_veneno()
        self.turno += 1
        # Se acabó el tiempo y nadie ha ganado: mueren los dos.
        if self.turno >= MAX_TICKS and self.red.vivo and self.pink.vivo:
            self.red.vidas = 0
            self.pink.vidas = 0
            self.eventos.append(("se_acabo_el_tiempo", ""))

    def ganador(self):
        """Devuelve 'red', 'pink', 'ambos_mueren', o None si la partida sigue."""
        if not self.red.vivo and not self.pink.vivo:
            return "ambos_mueren"
        if not self.red.vivo:
            return "pink"
        if not self.pink.vivo:
            return "red"
        return None

    def estado_compacto(self):
        """Foto MUY pequeña de la partida (para grabar intentos sin gastar disco).

        [tick, red, pink, objetos, proyectiles] donde cada jugador es
        [x, y, vidas, mira_x, mira_y, objeto('c','p','v' o ''), calor, envenenado]
        """
        def jug(j):
            t = j.objeto["tipo"] if j.objeto else ""
            return [round(j.x, 1), round(j.y, 1), j.vidas, j.dir[0], j.dir[1],
                    t[:1], round(j.objeto["calor"], 1) if t == "pistola" else 0,
                    1 if j.envenenado > 0 else 0]
        return [self.turno, jug(self.red), jug(self.pink),
                [[o["tipo"][:1], round(o["x"], 1), round(o["y"], 1),
                  round(o["calor"], 1), 1 if o["dueno"] else 0] for o in self.objetos],
                [[p["tipo"][:1], round(p["x"], 1), round(p["y"], 1)]
                 for p in self.proyectiles],
                [[round(v.x, 1), round(v.y, 1), v.vida] for v in self.viboras]]

    def estado(self):
        """Foto de la partida en este instante (la usa el visor HTML)."""
        def jug(j):
            return {"x": round(j.x, 2), "y": round(j.y, 2), "vidas": j.vidas,
                    "dir": list(j.dir),
                    "objeto": j.objeto["tipo"] if j.objeto else "",
                    "calor": round(j.objeto["calor"], 2)
                    if j.objeto and j.objeto["tipo"] == "pistola" else 0,
                    "veneno": j.envenenado}
        return {
            "t": self.turno,
            "red": jug(self.red), "pink": jug(self.pink),
            "objetos": [[o["tipo"], round(o["x"], 2), round(o["y"], 2),
                         round(o["calor"], 2), o["dueno"] or ""]
                        for o in self.objetos],
            "proyectiles": [[p["tipo"], round(p["x"], 2), round(p["y"], 2)]
                            for p in self.proyectiles],
            "viboras": [[round(v.x, 2), round(v.y, 2), v.vida, list(v.dir)] for v in self.viboras],
            "ganador": self.ganador(),
        }
