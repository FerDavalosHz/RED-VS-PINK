# Prueba de los objetos (caja, pistola, veneno) y del entorno de Gymnasium.
# NO entrena nada: solo comprueba que las reglas hacen lo que dicen.
from juego import *
from entorno import RedVsPinkEnv, observar, N_OBS
import bots

def avanzar(j, ticks, a_red=QUIETO, a_pink=QUIETO):
    for _ in range(ticks):
        j.paso(a_red, a_pink)

# Para probar sin depender del mapa: coloco las cosas a mano
j = Juego()
j.objetos = [o for o in j.objetos]             # copia del mapa real
print("Objetos del mapa:", [(o["tipo"], o["x"], o["y"]) for o in j.objetos])

# ---- PISTOLA: coger, disparar 4 veces, sobrecalentarse ----
j.red.x, j.red.y = 6.5, 13.5                   # junto a la pistola (6.5, 13.5)
j.red.dir = (1, 0)
j.paso(COGER, QUIETO)
print("Red coge la pistola ->", j.red.objeto["tipo"] if j.red.objeto else None)

# Pongo a Pink delante de Red, en línea
j.pink.x, j.pink.y = 12.5, 13.5
j.pink.vidas = 9                               # vidas de sobra para ver los 4 disparos
for _ in range(120):                           # 4 s de intentos de disparo
    j.paso(USAR, QUIETO)
    if j.red.objeto is None:
        break
print(f"Pink recibió {9 - j.pink.vidas} balas (esperado 4)")
pistola = [o for o in j.objetos if o["tipo"] == "pistola"][0]
print(f"Pistola: dueño = {pistola['dueno']}, calor = {pistola['calor']:.2f} "
      "(se soltó sola al ponerse al rojo)")
j.red.x, j.red.y = pistola["x"], pistola["y"]
j.paso(COGER, QUIETO)
print("Red intenta cogerla caliente ->", j.red.objeto, "(esperado None)")
avanzar(j, 3 * FPS)
j.paso(COGER, QUIETO)
print(f"3 s después, ya fría (calor {pistola['calor']:.2f}) ->",
      j.red.objeto["tipo"] if j.red.objeto else None)

# ---- CAJA: coger, soltar delante, que bloquee ----
j = Juego()
caja = [o for o in j.objetos if o["tipo"] == "caja"][0]
j.red.x, j.red.y = caja["x"] - 1, caja["y"]    # al lado de la caja
j.paso(COGER, QUIETO)
print("Red coge la caja ->", j.red.objeto["tipo"] if j.red.objeto else None)
j.red.dir = (1, 0)
j.paso(COGER, QUIETO)
print("Red suelta la caja en ->", (caja["x"], caja["y"]), " ¿hay caja ahí?",
      j.hay_caja(caja["x"], caja["y"]))
x_antes = j.red.x
avanzar(j, 30, a_red=DERECHA)
print(f"Red empuja contra la caja: x pasó de {x_antes:.2f} a {j.red.x:.2f} "
      f"(la caja ocupa la casilla {int(caja['x'])})")

# ---- VENENO: lanzar y que haga efecto 3 s después ----
j = Juego()
j.red.x, j.red.y = 10.5, 18.5                  # zona despejada, lejos del centro
j.pink.x, j.pink.y = 13.5, 18.5
j.objetos.append({"tipo": "veneno", "x": 10.5, "y": 18.5, "calor": 0.0, "dueno": None})
j.paso(COGER, QUIETO)
j.red.dir = (1, 0)
j.paso(USAR, QUIETO)
avanzar(j, 15)
print("Pink envenenado (ticks que faltan):", j.pink.envenenado, " vidas:", j.pink.vidas)
avanzar(j, 3 * FPS)
print("3 s después -> vidas de Pink:", j.pink.vidas, "(esperado 1)")

# ---- ENTORNO DE GYMNASIUM ----
env = RedVsPinkEnv("red", oponente=bots.aleatorio)
obs, _ = env.reset()
print(f"\nEntorno: {N_OBS} entradas, {env.action_space.n} acciones. obs.shape = {obs.shape}")
total, pasos = 0, 0
terminado = False
while not terminado:
    obs, r, terminado, _, info = env.step(env.action_space.sample())
    total += r; pasos += 1
print(f"Partida al azar: {pasos} decisiones, puntos de Red = {total:.2f}, resultado = {info['ganador']}")

# Un bot cazador contra otro: ¿saben jugar de verdad?
res = {"red": 0, "pink": 0, "ambos_mueren": 0}
for _ in range(20):
    j = Juego()
    while j.ganador() is None:
        j.paso(bots.cazador(None, j, "red"), bots.cazador(None, j, "pink"))
    res[j.ganador()] += 1
print("20 partidas cazador vs cazador:", res)

# Cazador contra un rival que no se mueve: debe ganar casi siempre
res = {"red": 0, "pink": 0, "ambos_mueren": 0}
for _ in range(20):
    j = Juego()
    while j.ganador() is None:
        j.paso(bots.cazador(None, j, "red"), QUIETO)
    res[j.ganador()] += 1
print("20 partidas cazador (Red) vs quieto (Pink):", res)
