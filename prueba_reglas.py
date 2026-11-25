# Prueba rápida: mapa, tiempo real, paredes, vidas y límite de 10 segundos.
from juego import *

j = Juego()
print("Mapa:", RUTA_MAPA)
print(f"{FPS} ticks por segundo, límite {TIEMPO_MAX} s = {MAX_TICKS} ticks")
print("Inicio -> red:", (j.red.x, j.red.y), " pink:", (j.pink.x, j.pink.y))

# 1) UN solo tick: los dos se mueven a la vez, pero solo un poquito
j.paso(DERECHA, IZQUIERDA)
print(f"Tras 1 tick -> red x={j.red.x:.2f} (sube)  pink x={j.pink.x:.2f} (baja)")

# 2) Un segundo entero (30 ticks) de Red hacia la derecha: choca con la pared de x=18
for _ in range(FPS):
    j.paso(DERECHA, QUIETO)
print(f"Red 1 s a la derecha  -> x = {j.red.x:.2f} (la pared está en x=18, no puede pasar de ~17.6)")

# 3) Deslizar: Red empuja contra la pared en diagonal (derecha + arriba por turnos alternos)
for _ in range(FPS):
    j.paso(ARRIBA, QUIETO)
print(f"Red 1 s hacia arriba  -> y = {j.red.y:.2f} (pared de arriba en y=10, no pasa de ~11.4)")

# 4) Vidas
j.reset()
j.quitar_vida(j.pink); j.quitar_vida(j.pink)
print("Pink sin vidas. Ganador:", j.ganador())

# 5) Límite de tiempo
j.reset()
for _ in range(MAX_TICKS - 1):
    j.paso(QUIETO, QUIETO)
print(f"A los {j.tiempo:.2f} s. Ganador: {j.ganador()}  (la partida sigue)")
j.paso(QUIETO, QUIETO)
print(f"A los {j.tiempo:.2f} s. Ganador: {j.ganador()}  vidas red={j.red.vidas} pink={j.pink.vidas}")
