import os
import glob
import pandas as pd
import numpy as np

# --- SEZIONE 1: CONFIGURAZIONE GOOGLE DRIVE E LIBRERIE RL ---
try:
    from google.colab import drive
    drive.mount('/content/drive')
    BASE_DIR = '/content/drive/MyDrive/AI_Trading_Data'
    MODEL_DIR = '/content/drive/MyDrive/AI_Trading_Models'
except ImportError:
    BASE_DIR = './AI_Trading_Data'
    MODEL_DIR = './AI_Trading_Models'

os.makedirs(MODEL_DIR, exist_ok=True)

import gymnasium as gym
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
import torch

# --- SEZIONE 2: CARICAMENTO DATI (PARQUET) ---
print("Caricamento dataset in memoria...")
all_files = glob.glob(f"{BASE_DIR}/*.parquet")
if not all_files:
    raise ValueError(f"Nessun file parquet trovato in {BASE_DIR}. Hai eseguito la Fase 1?")

# CARICAMENTO INCREMENTALE: Partiamo da un singolo asset (es. il primo scaricato)
# L'utente potrà in seguito cambiare l'indice di all_files[0] per continuare l'addestramento (Incremental Learning)
file_to_train = all_files[0]
print(f"Addestramento Base in corso sull'asset: {file_to_train}")
df = pd.read_parquet(file_to_train)

# Feature Engineering Base per la Rete Neurale
print("Calcolo indicatori tecnici per la rete neurale...")
df['returns'] = df['close'].pct_change()
df['volatility'] = df['returns'].rolling(window=20).std()
df.dropna(inplace=True)

# --- SEZIONE 3: MOTORE DEL MERCATO SIMULATO (GYM ENVIRONMENT) ---
# Usiamo gym_anytrading per simulare il mercato
import gym_anytrading
from gym_anytrading.envs import StocksEnv

def process_features(env):
    """Passa alla Rete Neurale non solo i prezzi, ma anche le variazioni (ritorni) e la volatilità"""
    start = env.frame_bound[0] - env.window_size
    end = env.frame_bound[1]
    prices = env.df.loc[:, 'close'].to_numpy()[start:end]
    signal_features = env.df.loc[:, ['returns', 'volatility']].to_numpy()[start:end]
    return prices, signal_features

class AITradingEnv(StocksEnv):
    _process_data = process_features
    
    def __init__(self, df, window_size, frame_bound):
        super().__init__(df, window_size, frame_bound)
        self.trade_fee_bid_percent = 0.0001 # Simuliamo lo Spread
        self.trade_fee_ask_percent = 0.0001
        
    def _calculate_reward(self, action):
        """LA FUNZIONE OBIETTIVO SPIETATA"""
        step_reward = 0
        trade = False
        if ((action == 1 and self._position == 0) or (action == 0 and self._position == 1)):
            trade = True
            
        if trade:
            current_price = self.prices[self._current_tick]
            last_trade_price = self.prices[self._last_trade_tick]
            price_diff = current_price - last_trade_price
            
            # Se eravamo LONG e il prezzo è salito, riceve un Premio. Se sceso, una Penalità.
            if self._position == 1: 
                step_reward += price_diff
                
        # KILL SWITCH IMPLICITO: Se il bot perde il 5% del capitale di partenza, 
        # subisce una penalità astronomica, insegnandogli il terrore del drawdown.
        if self._total_profit < 0.95: 
            step_reward -= 100
            
        return step_reward

# L'IA guarderà le ultime 60 candele (1 ora intera) per prendere la decisione successiva
window_size = 60 
env_maker = lambda: AITradingEnv(df=df, window_size=window_size, frame_bound=(window_size, len(df)))
env = DummyVecEnv([env_maker])

# --- SEZIONE 4: COSTRUZIONE O CARICAMENTO DEL CERVELLO (REINFORCEMENT LEARNING) ---
print("Inizializzazione Modello Reinforcement Learning (PPO)...")
model_path = f"{MODEL_DIR}/trading_brain_v1.zip"

if os.path.exists(model_path):
    print(f"🧠 Cervello esistente trovato in {model_path}!")
    print("Avvio APPRENDIMENTO INCREMENTALE (Il bot manterrà la memoria e imparerà nuove cose)...")
    model = PPO.load(model_path, env=env)
else:
    print("Nessun cervello precedente trovato. Creazione nuovo Modello Base da zero...")
    # Architettura della Rete Neurale: 3 Strati profondi per processare le complessità del mercato
    policy_kwargs = dict(activation_fn=torch.nn.ReLU, net_arch=[256, 256, 128])
    model = PPO("MlpPolicy", env, verbose=1, policy_kwargs=policy_kwargs, tensorboard_log=f"{MODEL_DIR}/logs/")

# --- SEZIONE 5: ADDESTRAMENTO INTENSIVO (MILIONI DI TRADE SIMULATI) ---
print("⚡ AVVIO ADDESTRAMENTO ⚡ (La GPU sta per andare al 100%...)")
# 1 Milione di operazioni simulate per l'addestramento. Può richiedere ore.
model.learn(total_timesteps=1_000_000, tb_log_name="PPO_Training_Run")

print(f"Salvataggio del cervello evoluto in: {model_path}")
model.save(model_path)
print("🎉 ADDESTRAMENTO COMPLETATO! Il file trading_brain_v1.zip è pronto su Google Drive.")
