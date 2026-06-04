import yfinance as yf
import pandas as pd
import numpy as np
import gym
from gym import spaces
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
import torch
import torch.nn as nn
from typing import Callable
import multiprocessing

# --- 1. DEFINIZIONE AMBIENTE SINGOLO ASSET ---
class UniversalAssetEnv(gym.Env):
    def __init__(self, data: pd.DataFrame, window_size=30):
        super(UniversalAssetEnv, self).__init__()
        self.data = data
        self.window_size = window_size
        self.current_step = self.window_size
        self.max_steps = len(self.data) - 1
        
        # Azioni: 0 (Short), 1 (Flat), 2 (Long)
        self.action_space = spaces.Discrete(3)
        
        # Osservazioni: 30 candele x 4 feature (Close, Volatility, XGB_Proxy, News_Proxy)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(self.window_size, 4), dtype=np.float32
        )

    def reset(self):
        self.current_step = self.window_size
        return self._next_observation()

    def _next_observation(self):
        window = self.data.iloc[self.current_step - self.window_size : self.current_step]
        
        close = window['Close_Norm'].values
        volatility = window['Volatility'].values
        
        # In Colab non abbiamo i dati reali di XGBoost e News storici per 10 anni.
        # Li inizializziamo a ZERO (rumore neutro). 
        # Titano imparerà a usare queste due colonne direttamente sul campo (tramite Online Learning su Railway).
        xgb_proxy = np.zeros(self.window_size)
        news_proxy = np.zeros(self.window_size)
        
        obs = np.column_stack((close, volatility, xgb_proxy, news_proxy))
        return obs.astype(np.float32)

    def step(self, action):
        current_price = self.data.iloc[self.current_step]['Close']
        next_price = self.data.iloc[self.current_step + 1]['Close']
        
        price_diff = (next_price - current_price) / current_price
        
        reward = 0
        if action == 2:   # Long
            reward = price_diff
        elif action == 0: # Short
            reward = -price_diff
        else:             # Flat
            reward = 0
            
        # Amplifichiamo il reward per favorire l'apprendimento
        reward = reward * 100 
        
        self.current_step += 1
        done = self.current_step >= self.max_steps
        
        return self._next_observation(), reward, done, {}

# --- 2. RETE NEURALE CNN PER MATRICE 30x4 ---
class UniversalFeatureExtractor(BaseFeaturesExtractor):
    def __init__(self, observation_space: gym.spaces.Box, features_dim: int = 512):
        super().__init__(observation_space, features_dim)
        
        # Il nuovo input ha 4 canali (Close, Vol, XGB, News)
        n_input_channels = 4
        
        self.cnn = nn.Sequential(
            nn.Conv1d(n_input_channels, 64, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(64, 128, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(128, 256, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Flatten()
        )
        
        # Calcolo dimensione output dinamico
        with torch.no_grad():
            sample = torch.zeros(1, n_input_channels, observation_space.shape[0])
            n_flatten = self.cnn(sample).shape[1]
            
        self.linear = nn.Sequential(
            nn.Linear(n_flatten, features_dim),
            nn.ReLU()
        )

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        # PPO invia (Batch, Window, Features). CNN1D vuole (Batch, Channels, Length)
        x = observations.permute(0, 2, 1)
        x = self.cnn(x)
        return self.linear(x)

# --- 3. PREPARAZIONE DATI E MULTIPROCESSING ---
def make_env(ticker: str) -> Callable:
    def _init():
        print(f"Scaricando storici per {ticker}...")
        df = yf.download(ticker, start="2020-01-01", end="2024-01-01", interval="1d")
        if df.empty:
            raise ValueError(f"Dati vuoti per {ticker}")
            
        df['Close_Norm'] = df['Close'].pct_change()
        df['Volatility'] = df['Close_Norm'].rolling(window=20).std()
        df.dropna(inplace=True)
        return UniversalAssetEnv(df)
    return _init

if __name__ == "__main__":
    print("🚀 Inizializzazione Addestramento V6 Universale...")
    
    # 1. LISTA DEGLI ASSET (Puoi aggiungerne quanti ne vuoi, il modello scala all'infinito)
    ASSETS = ["AAPL", "GOOGL", "MSFT", "AMZN", "META", "TSLA", "NVDA", "BTC-USD", "ETH-USD"]
    
    # 2. CREAZIONE AMBIENTI IN PARALLELO (Batching)
    num_cpu = min(multiprocessing.cpu_count(), len(ASSETS))
    print(f"⚙️ Creazione di {len(ASSETS)} ambienti vettorizzati distribuiti su {num_cpu} core...")
    
    env = SubprocVecEnv([make_env(ticker) for ticker in ASSETS])
    
    # 3. CREAZIONE DEL MODELLO UNIVERSALE
    policy_kwargs = dict(
        features_extractor_class=UniversalFeatureExtractor,
        features_extractor_kwargs=dict(features_dim=512),
        net_arch=dict(pi=[256, 128], vf=[256, 128])
    )
    
    model = PPO(
        "MlpPolicy", 
        env, 
        policy_kwargs=policy_kwargs, 
        verbose=1,
        learning_rate=0.0003,
        n_steps=2048,
        batch_size=256, # Elabora 256 asset/finestre in parallelo per volta!
        tensorboard_log="./v6_tensorboard/"
    )
    
    # 4. ADDESTRAMENTO AD ALTA VELOCITA'
    print("🔥 Inizio Addestramento V6 (10 Milioni di Step)...")
    model.learn(total_timesteps=10_000_000, progress_bar=True)
    
    # 5. SALVATAGGIO
    model.save("Titano_V6_Universale.zip")
    print("✅ Addestramento Completato. Scarica Titano_V6_Universale.zip e caricalo su Railway!")
