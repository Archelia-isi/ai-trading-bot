import sys
import numpy as np
import numpy.core
sys.modules['numpy._core'] = numpy.core
from stable_baselines3 import PPO

try:
    model = PPO.load("Titano_V7_DayTrader.zip")
    print("SUCCESS")
except Exception as e:
    print(f"FAILED: {e}")
