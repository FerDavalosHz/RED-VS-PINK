# Prueba de instalación: comprueba que las librerías funcionan.
# Todavía NO es el juego "Red vs Pink", solo un test rápido.

import gymnasium as gym
import stable_baselines3
import torch
from stable_baselines3 import PPO

print("Gymnasium:", gym.__version__)
print("Stable-Baselines3:", stable_baselines3.__version__)
print("PyTorch:", torch.__version__)

# CartPole: un palo en equilibrio sobre un carrito. La IA debe empujar
# el carrito a izquierda o derecha para que el palo no se caiga.
env = gym.make("CartPole-v1")

# PPO es el "método de aprendizaje" que usaremos. "MlpPolicy" = cerebro simple.
modelo = PPO("MlpPolicy", env, verbose=0, device="cpu")

print("Entrenando 5000 pasos (unos segundos)...")
modelo.learn(total_timesteps=5000)

print("¡Todo funciona!")
