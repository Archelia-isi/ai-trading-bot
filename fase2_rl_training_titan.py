import os
import glob
import pandas as pd
import numpy as np
import torch
import torch.nn as nn

import gymnasium as gym
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
import gym_anytrading
from gym_anytrading.envs import StocksEnv

# =========================================================================
# IL TITANO V2: Ottimizzato per addestramento senza crash
# =========================================================================
class TitanFeatureExtractor(BaseFeaturesExtractor):
    def __init__(self, observation_space: gym.spaces.Box, features_dim: int = 1024):
        super().__init__(observation_space, features_dim)
        
        n_input_channels = observation_space.shape[1]
        
        # Ridotto il numero di filtri (canali) per evitare di intasare la RAM durante 
        # il calcolo dei gradienti (la 'backpropagation'), ma mantenendo la profondità.
        self.cnn = nn.Sequential(
            nn.Conv1d(n_input_channels, 128, kernel_size=8, stride=2, padding=3),
            nn.ReLU(),
            nn.Conv1d(128, 256, kernel_size=8, stride=2, padding=3),
            nn.ReLU(),
            nn.Conv1d(256, 512, kernel_size=4, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv1d(512, 1024, kernel_size=4, stride=2, padding=1),
            nn.ReLU(),
            nn.Flatten(),
        )
        
        with torch.no_grad():
            dummy_input = torch.zeros(1, n_input_channels, observation_space.shape[0])
            n_flatten = self.cnn(dummy_input).shape[1]
            
        self.linear = nn.Sequential(
            nn.Linear(n_flatten, 1024),
            nn.ReLU(),
            nn.Linear(1024, features_dim),
            nn.ReLU()
        )

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        observations = observations.permute(0, 2, 1)
        x = self.cnn(observations)
        return self.linear(x)

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
        self.ticks_in_position = 0 # Contatore per il Day Trading
        
    def step(self, action):
        # Override per resettare il contatore quando si cambia posizione
        if ((action == 1 and self._position == 0) or (action == 0 and self._position == 1)):
            self.ticks_in_position = 0
        else:
            if self._position == 1:
                self.ticks_in_position += 1
                
        return super().step(action)
        
    def _calculate_reward(self, action):
        step_reward = 0
        
        # Premio in tempo reale se il prezzo sale mentre siamo LONG
        if self._position == 1:
            current_price = self.prices[self._current_tick]
            last_price = self.prices[self._current_tick - 1]
            step_reward += (current_price - last_price)
            
            # DAY TRADING ENFORCER: Se tieni aperto il trade per più di 300 minuti (5 ore), 
            # inizi a prendere mazzate pesanti. Più lo tieni aperto, peggio è.
            if self.ticks_in_position > 300:
                step_reward -= 0.001 * (self.ticks_in_position - 300)
            
        # Penalità piccolissima se sta fuori dal mercato a oziare
        if self._position == 0:
            step_reward -= 0.00001  
            
        return step_reward

def make_env(file_path, window_size):
    def _init():
        df = pd.read_parquet(file_path)
        df['returns'] = df['close'].pct_change()
        df['volatility'] = df['returns'].rolling(window=20).std()
        df.dropna(inplace=True)
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

    all_files = glob.glob(f"{BASE_DIR}/*.parquet")
    file_to_train = all_files[0]
    
    NUM_ENV = 32  
    window_size = 1000 

    print(f"🚀 Creazione universi (Window Size: {window_size})...")
    env = SubprocVecEnv([make_env(file_to_train, window_size) for _ in range(NUM_ENV)])

    model_path = f"{MODEL_DIR}/trading_brain_v3_titan.zip"

    policy_kwargs = dict(
        features_extractor_class=TitanFeatureExtractor,
        features_extractor_kwargs=dict(features_dim=1024),
        net_arch=[1024, 1024]
    )

    print("Evocazione del TITANO V2...")
    model = PPO(
        "MlpPolicy", 
        env, 
        verbose=1, 
        policy_kwargs=policy_kwargs, 
        n_steps=512,       # Digeribile
        batch_size=256,    # Batch ridotto per non intasare la Backpropagation
        n_epochs=10, 
        learning_rate=0.0001,
        ent_coef=0.01,     # LO PSICOLOGO: Forza l'esplorazione e impedisce l'iper-fissazione
        tensorboard_log=f"{MODEL_DIR}/logs/"
    )

    print("⚡ ADDESTRAMENTO IN CORSO... ⚡")
    model.learn(total_timesteps=10_000_000, tb_log_name="PPO_A100_Titan")

    model.save(model_path)
    print("🎉 TITANO SALVATO!")
