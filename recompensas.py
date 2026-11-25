# recompensas.py - Los PUNTOS del juego: qué da puntos y qué los quita.
#
# Los valores viven en recompensas.json. El entrenamiento relee ese archivo al
# empezar cada partida, así que si cambias un valor (desde la pestaña "Puntos"
# de la página, o a mano) se aplica en la partida siguiente, sin parar nada.
#
# Solo usa la librería estándar: lo usan tanto el entrenamiento como el servidor.

import json
import os
import time

RUTA_RECOMPENSAS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "recompensas.json")

# clave, título, explicación, valor por defecto, mínimo, máximo, paso del deslizador
PARAMETROS = [
    dict(clave="ganar", titulo="Ganar la partida",
         ayuda="Se lo lleva quien deja al otro sin vidas.",
         defecto=1.0, min=0.0, max=3.0, paso=0.05),
    dict(clave="perder", titulo="Perder (o que mueran los dos por el tiempo)",
         ayuda="Si se acaba el tiempo sin ganador, los dos reciben esto. Es lo que "
               "les obliga a atacar en vez de esconderse.",
         defecto=-1.0, min=-3.0, max=0.0, paso=0.05),
    dict(clave="vida_quitada", titulo="Quitarle una vida al rival",
         ayuda="Un disparo de escopeta que acierta, o el veneno haciendo efecto.",
         defecto=0.5, min=0.0, max=2.0, paso=0.05),
    dict(clave="vida_perdida", titulo="Perder una vida",
         ayuda="Que te acierten un disparo o te llegue el veneno.",
         defecto=-0.5, min=-2.0, max=0.0, paso=0.05),
    dict(clave="multiplicador_escopeta", titulo="La escopeta vale esto veces más (×)",
         ayuda="Los tres premios de buscar un objeto (descubrirlo, ir hacia él y cogerlo) se "
               "multiplican por este número cuando el objeto es la escopeta.",
         defecto=3.0, min=1.0, max=10.0, paso=0.5),
    dict(clave="coger_objeto", titulo="Coger un objeto (una vez por objeto y partida)",
         ayuda="Cuando cogen una caja, la escopeta o el veneno. Una sola vez por objeto: "
               "no se puede ganar cogiendo y soltando.",
         defecto=0.05, min=0.0, max=0.3, paso=0.01),
    dict(clave="acercarse_objeto", titulo="Ir hacia un objeto que ven (por casilla)",
         ayuda="Con la mano vacía, por cada casilla que se acercan al objeto que ven (la "
               "escopeta tiene prioridad). Si se alejan, restan.",
         defecto=0.01, min=0.0, max=0.05, paso=0.005),
    dict(clave="sostener_escopeta", titulo="Llevar la escopeta (por cada instante)",
         ayuda="Premio pequeñito, 30 veces por segundo. Es lo que las hace querer cogerla. "
               "Con 0 dejaron de cogerla en las pruebas.",
         defecto=0.001, min=0.0, max=0.01, paso=0.0005),
    dict(clave="perseguir", titulo="Acercarse al rival llevando la escopeta (por casilla)",
         ayuda="Con la escopeta en la mano, ganas por cada casilla que te acercas "
               "y pierdes si te alejas.",
         defecto=0.02, min=0.0, max=0.1, paso=0.005),
    dict(clave="disparo_punteria", titulo="Disparar con puntería",
         ayuda="Por cada disparo con el rival delante, a menos de 7 casillas y sin pared en medio.",
         defecto=0.05, min=0.0, max=0.3, paso=0.005),
    dict(clave="huir", titulo="Alejarse cuando el rival tiene la escopeta (por casilla)",
         ayuda="Si el rival la lleva, ganas por cada casilla que te alejas y "
               "pierdes si te acercas.",
         defecto=0.02, min=0.0, max=0.1, paso=0.005),
    dict(clave="choque_pared", titulo="Chocar con una pared (por cada instante)",
         ayuda="Se resta cuando intentas moverte y algo te lo impide. "
               "Pegarte 1 segundo a una pared son 30 instantes.",
         defecto=-0.003, min=-0.03, max=0.0, paso=0.001),
    dict(clave="bala_pared", titulo="Disparar a una pared (por disparo perdido)",
         ayuda="Se resta cuando la salva de la escopeta se estrella en vez de dar al rival.",
         defecto=-0.03, min=-0.3, max=0.0, paso=0.005),
    dict(clave="descubrir_objeto", titulo="Descubrir un objeto (verlo por primera vez)",
         ayuda="Una vez por objeto y partida, cuando un objeto entra en su vista (si no lo "
               "veían ya al empezar). Es el premio por BUSCAR: lo que no ven, no lo saben.",
         defecto=0.05, min=0.0, max=0.3, paso=0.01),
    dict(clave="explorar", titulo="Explorar: pisar una casilla nueva (por casilla)",
         ayuda="Premio pequeño por cada casilla que no habían pisado en esa partida. "
               "Les empuja a recorrer el mapa cuando no ven nada.",
         defecto=0.002, min=0.0, max=0.02, paso=0.001),
    dict(clave="escapar_tirador", titulo="Salir de la vista de un tirador",
         ayuda="Si el rival lleva la escopeta y te estaba viendo, y consigues salir de su "
               "rango de visión (o taparte con un muro). Máximo 5 veces por partida.",
         defecto=0.15, min=0.0, max=0.5, paso=0.01),
    dict(clave="morir_vibora", titulo="Morir por la víbora",
         ayuda="Se resta ADEMÁS de perder la partida cuando la última vida te la quita una "
               "mordida de la víbora. (Cada mordida ya resta 'Perder una vida'.)",
         defecto=-1.0, min=-3.0, max=0.0, paso=0.05),
    dict(clave="matar_vibora", titulo="Matar a la víbora (el que le da el último perdigón)",
         ayuda="La víbora aguanta 20 perdigones. Con 0 no ganan nada por matarla, solo les "
               "conviene evitarla. Si lo subes, les dará por buscar la escopeta para cazarla.",
         defecto=0.0, min=0.0, max=1.0, paso=0.05),
    # --- No son puntos: ajustes del entrenamiento ---
    dict(clave="posiciones_aleatorias", grupo="entrenamiento",
         titulo="Posiciones aleatorias (% de partidas)",
         ayuda="En ese % de partidas, Red, Pink y los objetos salen en sitios al azar "
               "(siempre donde se pueda llegar). Así aprenden 'ir a la escopeta, esté donde "
               "esté' en vez de memorizar un recorrido, y cambiar el mapa les afecta mucho "
               "menos. Las gráficas se miden siempre en el mapa tal cual, sin azar.",
         defecto=80.0, min=0.0, max=100.0, paso=5.0),
    dict(clave="rango_vision", grupo="entrenamiento", titulo="Rango de visión (casillas)",
         ayuda="Hasta dónde ven Red y Pink. Lo que está más lejos, o detrás de un muro o una "
               "caja, NO lo saben: ni dónde está el rival, ni los objetos. En las pantallas "
               "se dibuja como una zona clara alrededor de cada una.",
         defecto=8.0, min=3.0, max=20.0, paso=1.0),
    dict(clave="campo_vision", grupo="entrenamiento", titulo="Ángulo de visión (grados)",
         ayuda="Lo que abarca su vista, hacia donde miran. 180° = ven delante, no a su espalda. "
               "360° = ven en todas direcciones. Para esconderse de alguien, hay que ponerse a su espalda.",
         defecto=180.0, min=60.0, max=360.0, paso=10.0),
    dict(clave="espera_coger", grupo="entrenamiento", titulo="Espera entre coger/soltar (segundos)",
         ayuda="Tras coger o soltar algo hay que esperar este tiempo antes de volver a "
               "hacerlo. Evita que se pasen la partida cogiendo y soltando la caja.",
         defecto=2.0, min=0.0, max=5.0, paso=0.5),
]

DEFECTOS = {p["clave"]: p["defecto"] for p in PARAMETROS}
_LIMITES = {p["clave"]: (p["min"], p["max"]) for p in PARAMETROS}


def limpiar(datos):
    """Devuelve un diccionario completo y con valores dentro de sus límites."""
    resultado = dict(DEFECTOS)
    if isinstance(datos, dict):
        for clave, (minimo, maximo) in _LIMITES.items():
            v = datos.get(clave)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
                resultado[clave] = max(minimo, min(maximo, float(v)))
    return resultado


def leer(ruta=RUTA_RECOMPENSAS, anterior=None):
    """Lee los puntos. Si el archivo no existe, usa los de por defecto.

    Si está a medio guardar o roto, devuelve 'anterior' (lo último que valía).
    """
    if not os.path.exists(ruta):
        return dict(DEFECTOS)
    try:
        with open(ruta, encoding="utf-8") as f:
            return limpiar(json.load(f))
    except (OSError, ValueError):
        return anterior if anterior is not None else dict(DEFECTOS)


def guardar(valores, ruta=RUTA_RECOMPENSAS):
    """Guarda los puntos de golpe (sin que nadie pueda leerlos a medias)."""
    limpios = limpiar(valores)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(limpios, f, indent=2)
    for _ in range(10):                       # si el entrenamiento lo está leyendo, esperamos
        try:
            os.replace(tmp, ruta)
            return limpios
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, ruta)
    return limpios
