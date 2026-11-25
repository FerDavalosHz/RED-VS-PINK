# generar_visor.py - Juega UNA partida y la guarda como visor.html
#
# El visor es una página web con la partida grabada, y con el "cerebro" de
# cada IA dibujado: qué ve, qué neuronas se encienden y qué decide.
#
# Uso:
#     python generar_visor.py            -> crea visor.html
#     python generar_visor.py --abrir    -> y además lo abre en el navegador
#
# Si existen modelos/red.zip y modelos/pink.zip, usa esas IAs entrenadas.
# Si no, usa IAs SIN entrenar (cerebros al azar): sirve para ver el panel.

import json
import os
import sys
import webbrowser

import numpy as np
import torch
from stable_baselines3 import PPO

import recompensas
from entorno import RedVsPinkEnv, observar, ajustar_juego, NOMBRES_OBS, FRAME_SKIP
from juego import (Juego, FPS, TIEMPO_MAX, RADIO, NOMBRES_ACCIONES)

AQUI = os.path.dirname(os.path.abspath(__file__))


def cargar_ia(nombre, ronda=None):
    """Carga la IA guardada (la más reciente, o la de la ronda pedida).

    Si no existe ninguna, crea una IA sin entrenar (cerebro al azar).
    """
    if ronda is None:
        ruta = os.path.join(AQUI, "modelos", f"{nombre}.zip")
    else:
        ruta = os.path.join(AQUI, "modelos", "historial", f"ronda_{ronda:03d}", f"{nombre}.zip")
        if not os.path.exists(ruta):
            sys.exit(f"No existe la ronda {ronda}. Mira las carpetas de modelos/historial.")
    if os.path.exists(ruta):
        return PPO.load(ruta, device="cpu"), True
    return PPO("MlpPolicy", RedVsPinkEnv(nombre), device="cpu"), False


def redondear(a, n=3):
    return np.round(a.detach().numpy(), n).tolist()


def pesos(modelo):
    """Las conexiones del cerebro: cuánto pesa cada neurona en la siguiente."""
    pol = modelo.policy
    capas = pol.mlp_extractor.policy_net      # Linear, Tanh, Linear, Tanh
    return {"w1": redondear(capas[0].weight), "w2": redondear(capas[2].weight),
            "w3": redondear(pol.action_net.weight)}


def pensar(modelo, obs):
    """Pasa lo que ve la IA por su cerebro y apunta qué neuronas se activan."""
    pol = modelo.policy
    x = torch.as_tensor(obs, dtype=torch.float32).unsqueeze(0)
    with torch.no_grad():
        capas = pol.mlp_extractor.policy_net
        h1 = capas[1](capas[0](x))
        h2 = capas[3](capas[2](h1))
        probs = torch.softmax(pol.action_net(h2), dim=-1)
        accion = int(torch.multinomial(probs, 1))   # elige según las probabilidades
    return accion, {
        "obs": np.round(obs, 3).tolist(),
        "h1": redondear(h1[0], 2), "h2": redondear(h2[0], 2),
        "p": redondear(probs[0], 3), "a": accion,
    }


def main():
    torch.manual_seed(int.from_bytes(os.urandom(2), "little"))
    ronda = int(sys.argv[sys.argv.index("--ronda") + 1]) if "--ronda" in sys.argv else None
    ias, entrenadas = {}, {}
    for nombre in ("red", "pink"):
        ias[nombre], entrenadas[nombre] = cargar_ia(nombre, ronda)
        estado = "entrenada" if entrenadas[nombre] else "SIN ENTRENAR (pesos al azar)"
        print(f"  {nombre}: {estado}")

    j = Juego()
    ajustar_juego(j, recompensas.leer())            # rango de visión y espera actuales
    frames, decisiones = [], []
    acciones = {"red": 0, "pink": 0}
    while j.ganador() is None:
        if j.turno % FRAME_SKIP == 0:             # la IA decide cada FRAME_SKIP ticks
            dec = {}
            for n in ("red", "pink"):
                acciones[n], dec[n] = pensar(ias[n], observar(j, n))
            decisiones.append(dec)
        if j.turno == 0:
            frames.append({**j.estado(), "d": 0, "ev": []})
        j.paso(acciones["red"], acciones["pink"])
        frames.append({**j.estado(), "d": len(decisiones) - 1,
                       "ev": [list(e) for e in j.eventos]})

    datos = {
        "mapa": {"ancho": j.ancho, "alto": j.alto, "paredes": j.paredes,
                 "escaleras": j.escaleras},
        "config": {"fps": FPS, "tiempo_max": TIEMPO_MAX, "radio": RADIO,
                   "rango_vision": j.rango_vision, "campo_vision": j.campo_vision,
                   "acciones": NOMBRES_ACCIONES, "nombres_obs": NOMBRES_OBS},
        "modelos": {n: {"entrenada": entrenadas[n], **pesos(ias[n])}
                    for n in ("red", "pink")},
        "frames": frames,
        "decisiones": decisiones,
        "resultado": j.ganador(),
        "ronda": ronda,          # None = la más reciente
    }

    # "</" dentro de un <script> rompería la página, por eso se escapa
    texto = json.dumps(datos, separators=(",", ":")).replace("</", "<\\/")
    if "--solo-datos" in sys.argv:
        # Para la pestaña "Cerebros" del centro de control: solo los datos de la partida
        os.makedirs(os.path.join(AQUI, "modelos"), exist_ok=True)
        salida = os.path.join(AQUI, "modelos", "demo.js")
        with open(salida + ".tmp", "w", encoding="utf-8") as f:
            f.write("window.DEMO = " + texto + ";")
        os.replace(salida + ".tmp", salida)
    else:
        with open(os.path.join(AQUI, "visor_plantilla.html"), encoding="utf-8") as f:
            plantilla = f.read()
        salida = os.path.join(AQUI, "visor.html")
        with open(salida, "w", encoding="utf-8") as f:
            f.write(plantilla.replace("__DATOS__", texto))

    print(f"Partida: {len(frames)} frames, resultado = {j.ganador()}")
    print(f"Visor creado: {salida}")
    if "--abrir" in sys.argv:
        webbrowser.open("file:///" + salida.replace("\\", "/"))


if __name__ == "__main__":
    main()
