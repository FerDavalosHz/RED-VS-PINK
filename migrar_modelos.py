# migrar_modelos.py - Pone a los cerebros viejos al día para que sepan que existe la víbora.
#
# Los cerebros guardados tenían 57 entradas (lo que ven). Con la víbora ven 62: las 5 nuevas
# van AL FINAL. Este programa les añade esas 5 entradas con peso 0 en la primera capa, así
# que se comportan EXACTAMENTE igual que antes y, entrenando, aprenden a usarlas.
# Así no se pierde nada de lo que ya habían aprendido.
#
# Uso:  python migrar_modelos.py            (migra modelos/*.zip y modelos/historial/*/*.zip)
#       Los que ya están migrados se saltan solos.

import glob
import os
import sys

import numpy as np
import torch
from stable_baselines3 import PPO

from entorno import RedVsPinkEnv, N_OBS

AQUI = os.path.dirname(os.path.abspath(__file__))
CARPETA = os.environ.get("RVP_CARPETA", os.path.join(AQUI, "modelos"))


def migrar(ruta, rol, env):
    viejo = PPO.load(ruta, device="cpu")
    n_viejo = viejo.observation_space.shape[0]
    if n_viejo == N_OBS:
        return "ya estaba"
    nuevo = PPO("MlpPolicy", env, verbose=0, device="cpu", ent_coef=0.02,
                n_steps=2048, batch_size=256)
    estado = viejo.policy.state_dict()
    destino = nuevo.policy.state_dict()
    for k, v in estado.items():
        if v.shape != destino[k].shape:
            # solo la primera capa (entradas): se añaden columnas de ceros
            assert v.dim() == 2 and v.shape[0] == destino[k].shape[0] and v.shape[1] == n_viejo, (k, v.shape)
            relleno = torch.zeros(destino[k].shape, dtype=v.dtype)
            relleno[:, :n_viejo] = v
            estado[k] = relleno
    nuevo.policy.load_state_dict(estado)
    nuevo.num_timesteps = viejo.num_timesteps
    # Comprobación: con las entradas nuevas a 0 piensa igual que el cerebro viejo
    x = np.random.rand(20, n_viejo).astype(np.float32)
    x2 = np.concatenate([x, np.zeros((20, N_OBS - n_viejo), np.float32)], axis=1)
    with torch.no_grad():
        a = viejo.policy.get_distribution(torch.as_tensor(x)).distribution.probs
        b = nuevo.policy.get_distribution(torch.as_tensor(x2)).distribution.probs
    assert torch.allclose(a, b, atol=1e-6), "el cerebro migrado no piensa igual"
    nuevo.save(ruta)
    return f"{n_viejo} -> {N_OBS} entradas"


def main():
    envs = {rol: RedVsPinkEnv(rol) for rol in ("red", "pink")}
    rutas = sorted(glob.glob(os.path.join(CARPETA, "*.zip")) +
                   glob.glob(os.path.join(CARPETA, "historial", "ronda_*", "*.zip")))
    hechos = 0
    for r in rutas:
        rol = os.path.basename(r)[:-4]
        if rol not in envs:
            continue
        res = migrar(r, rol, envs[rol])
        hechos += res != "ya estaba"
    print(f"Migrados {hechos} de {len(rutas)} cerebros.")


if __name__ == "__main__":
    sys.exit(main())
