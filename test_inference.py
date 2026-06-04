import os
import sys
import numpy as np
from stable_baselines3 import PPO

model_path = "services/titano_engine/models/Titano_V5_OcchiAperti.zip"
print(f"Caricamento {model_path}...")
model = PPO.load(model_path)

print("Test 1: Input RAW CLOSE (es. 150.0)")
obs_close = np.random.rand(30, 34) * 100 + 50
obs_close = obs_close.flatten()
action1, _ = model.predict(obs_close, deterministic=True)
print(f"Azione con RAW CLOSE: {action1}")

print("Test 2: Input RETURNS (es. 0.001)")
obs_ret = np.random.randn(30, 34) * 0.01
obs_ret = obs_ret.flatten()
action2, _ = model.predict(obs_ret, deterministic=True)
print(f"Azione con RETURNS: {action2}")

