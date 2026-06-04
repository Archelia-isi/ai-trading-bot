import os
import glob
import pandas as pd
import numpy as np
import torch

import gymnasium as gym
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import SubprocVecEnv
import gym_anytrading
from gym_anytrading.envs import StocksEnv

# Definiamo la logica fuori dal blocco main per permettere al Multiprocessing di clonarla
def process_features(env):
    start = env.frame_bound[0] - env.window_size
    end = env.frame_bound[1]
    prices = env.df.loc[:, 'close'].to_numpy()[start:end]
    signal_features = env.df.loc[:, ['returns', 'volatility']].to_numpy()[start:end]
    return prices, signal_features

class AITradingEnv(StocksEnv):
    _process_data = process_features
    def __init__(self, df, window_size, frame_bound):
        super().__init__(df, window_size, frame_bound)
        self.trade_fee_bid_percent = 0.0001
        self.trade_fee_ask_percent = 0.0001
        
    def _calculate_reward(self, action):
        step_reward = 0
        trade = False
        if ((action == 1 and self._position == 0) or (action == 0 and self._position == 1)):
            trade = True
        if trade:
            current_price = self.prices[self._current_tick]
            last_trade_price = self.prices[self._last_trade_tick]
            price_diff = current_price - last_trade_price
            if self._position == 1: 
                step_reward += price_diff
        if self._total_profit < 0.95: 
            step_reward -= 100
        return step_reward

def make_env(df, window_size):
    def _init():
        return AITradingEnv(df=df, window_size=window_size, frame_bound=(window_size, len(df)))
    return _init

if __name__ == '__main__':
    try:
        from google.colab import drive
        drive.mount('/content/drive')
        BASE_DIR = '/content/drive/MyDrive/AI_Trading_Data'
        MODEL_DIR = '/content/drive/MyDrive/AI_Trading_Models'
    except ImportError:
        BASE_DIR = './AI_Trading_Data'
        MODEL_DIR = './AI_Trading_Models'

    os.makedirs(MODEL_DIR, exist_ok=True)

    print("Caricamento dataset in memoria principale (Copy-on-Write per 32 processi)...")
    all_files = glob.glob(f"{BASE_DIR}/*.parquet")
    file_to_train = all_files[0]
    df = pd.read_parquet(file_to_train)
    df['returns'] = df['close'].pct_change()
    df['volatility'] = df['returns'].rolling(window=20).std()
    df.dropna(inplace=True)

    # ---------------------------------------------------------
    # VETTORIZZAZIONE ESTREMA
    # ---------------------------------------------------------
    NUM_ENV = 32  # Dividiamo il mercato in 32 universi paralleli
    window_size = 60

    print(f"🚀 Creazione di {NUM_ENV} universi di trading paralleli (SubprocVecEnv)...")
    env = SubprocVecEnv([make_env(df, window_size) for _ in range(NUM_ENV)])

    print("Inizializzazione Modello RL (SCALATO PER A100 GPU)...")
    model_path = f"{MODEL_DIR}/trading_brain_v2_extreme.zip"

    if os.path.exists(model_path):
        print("Avvio APPRENDIMENTO INCREMENTALE...")
        model = PPO.load(model_path, env=env)
    else:
        print("Creazione Rete Neurale Massiccia (1024x1024x512)...")
        # Rete Neurale enorme per sfruttare le matrici della A100
        policy_kwargs = dict(activation_fn=torch.nn.ReLU, net_arch=[1024, 1024, 512])
        model = PPO(
            "MlpPolicy", 
            env, 
            verbose=1, 
            policy_kwargs=policy_kwargs, 
            n_steps=2048,       # Accumula 2048 step per ogni singolo ambiente (32)
            batch_size=16384,   # Dà in pasto alla GPU un minibatch ciclopico (16.384 dati alla volta)
            n_epochs=10, 
            learning_rate=0.0003,
            tensorboard_log=f"{MODEL_DIR}/logs/"
        )

    print("🔥 SCATENIAMO L'INFERNO 🔥 (Addestramento simultaneo su 32 mercati)")
    model.learn(total_timesteps=5_000_000, tb_log_name="PPO_A100_Extreme")

    print(f"Salvataggio del cervello in: {model_path}")
    model.save(model_path)
    print("🎉 INFERNO COMPLETATO!")
