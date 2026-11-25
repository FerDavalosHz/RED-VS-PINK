# bots.py - Rivales hechos a mano (sin IA) para que las IAs practiquen.
#
# Un bot es una función:  bot(obs, juego, nombre) -> acción (un número 0..6)
# Tiene la misma forma que una IA, así que se pueden intercambiar.

import math
import random
from collections import deque

from juego import (N_ACCIONES, QUIETO, ARRIBA, ABAJO, IZQUIERDA, DERECHA,
                   USAR, COGER, DIST_COGER, CALOR_PARA_COGER)


def quieto(obs, juego, nombre):
    """No hace nada. El rival más fácil."""
    return QUIETO


def aleatorio(obs, juego, nombre):
    """Elige una acción cualquiera cada vez."""
    return random.randrange(N_ACCIONES)


# ----------------------------------------------------------------------
# Herramientas para moverse por el mapa
# ----------------------------------------------------------------------
_CACHE_MUROS = {}


def _casillas_bloqueadas(j):
    """Casillas con pared (se calcula una vez) + las que tienen una caja."""
    clave = id(j.paredes)
    if clave not in _CACHE_MUROS:
        muros = set()
        for p in j.paredes:
            for x in range(p["x"], p["x"] + p["w"]):
                for y in range(p["y"], p["y"] + p["h"]):
                    muros.add((x, y))
        _CACHE_MUROS[clave] = muros
    cajas = {(math.floor(o["x"]), math.floor(o["y"])) for o in j.objetos
             if o["tipo"] == "caja" and o["dueno"] is None}
    return _CACHE_MUROS[clave] | cajas


def _primer_paso(j, origen, destino):
    """Busca el camino más corto (BFS) y devuelve la PRIMERA acción para seguirlo."""
    if origen == destino:
        return None
    bloq = _casillas_bloqueadas(j)
    if destino in bloq:
        return None
    previo = {origen: None}
    cola = deque([origen])
    while cola:
        c = cola.popleft()
        if c == destino:
            break
        for dx, dy, acc in ((1, 0, DERECHA), (-1, 0, IZQUIERDA),
                            (0, 1, ABAJO), (0, -1, ARRIBA)):
            n = (c[0] + dx, c[1] + dy)
            if (n in previo or n in bloq
                    or not (0 <= n[0] < j.ancho and 0 <= n[1] < j.alto)):
                continue
            previo[n] = (c, acc)
            cola.append(n)
    if destino not in previo:
        return None
    c = destino
    while previo[c][0] != origen:
        c = previo[c][0]
    return previo[c][1]


def _ir_a(j, yo, tx, ty):
    """Acción para acercarse al punto (tx, ty) rodeando paredes."""
    destino = (math.floor(tx), math.floor(ty))
    origen = (math.floor(yo.x), math.floor(yo.y))
    if origen == destino:                       # misma casilla: ir directo
        dx, dy = tx - yo.x, ty - yo.y
        if abs(dx) < 0.1 and abs(dy) < 0.1:
            return QUIETO
        if abs(dx) > abs(dy):
            return DERECHA if dx > 0 else IZQUIERDA
        return ABAJO if dy > 0 else ARRIBA
    accion = _primer_paso(j, origen, destino)
    if accion is None:
        return QUIETO
    # Antes de girar, centrarse en la casilla (los pasillos son de 1 casilla)
    if accion in (DERECHA, IZQUIERDA):
        fuera = math.floor(yo.y) + 0.5 - yo.y
        if abs(fuera) > 0.1:
            return ABAJO if fuera > 0 else ARRIBA
    else:
        fuera = math.floor(yo.x) + 0.5 - yo.x
        if abs(fuera) > 0.1:
            return DERECHA if fuera > 0 else IZQUIERDA
    return accion


def _linea_libre(j, ax, ay, bx, by):
    """¿Se ven en línea recta, sin paredes ni cajas en medio?"""
    dist = math.hypot(bx - ax, by - ay)
    pasos = max(1, int(dist / 0.25))
    for i in range(1, pasos):
        t = i / pasos
        if j.hay_obstaculo(ax + (bx - ax) * t, ay + (by - ay) * t):
            return False
    return True


def cazador(obs, juego, nombre, ruido=0.08):
    """Va a por la pistola, persigue al rival rodeando paredes y le dispara.

    'ruido' = probabilidad de hacer algo al azar, para que no sea siempre igual.
    """
    if random.random() < ruido:
        return random.randrange(N_ACCIONES)

    yo = juego.jugador(nombre)
    rival = juego.rival(nombre)

    # 1) Con las manos vacías: ir a por la pistola (si hay una libre y fría)
    if yo.objeto is None:
        pistolas = [o for o in juego.objetos
                    if o["tipo"] == "pistola" and o["dueno"] is None
                    and o["calor"] <= CALOR_PARA_COGER]
        if not pistolas:
            return QUIETO
        p = min(pistolas, key=lambda o: math.hypot(o["x"] - yo.x, o["y"] - yo.y))
        if math.hypot(p["x"] - yo.x, p["y"] - yo.y) < DIST_COGER - 0.2:
            return COGER
        return _ir_a(juego, yo, p["x"], p["y"])

    # 2) Con una caja en la mano: soltarla
    if yo.objeto["tipo"] == "caja":
        return COGER

    # 3) Con pistola o veneno: si lo ve en línea recta, apuntar y usar
    dx, dy = rival.x - yo.x, rival.y - yo.y
    if _linea_libre(juego, yo.x, yo.y, rival.x, rival.y):
        if abs(dy) <= 0.35:
            quiero = (1, 0) if dx > 0 else (-1, 0)
            return USAR if yo.dir == quiero else (DERECHA if dx > 0 else IZQUIERDA)
        if abs(dx) <= 0.35:
            quiero = (0, 1) if dy > 0 else (0, -1)
            return USAR if yo.dir == quiero else (ABAJO if dy > 0 else ARRIBA)
    # Si no lo ve: ir hacia él por el camino más corto
    return _ir_a(juego, yo, rival.x, rival.y)
