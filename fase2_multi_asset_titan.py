import os
import glob
import pandas as pd
import numpy as np
import torch
import torch.nn as nn

import gymnasium as gym
from gymnasium import spaces
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

# =========================================================================
# V4: TRUE MULTI-ASSET PORTFOLIO MANAGER & DAY TRADER
# =========================================================================

class MultiAssetFeatureExtractor(BaseFeaturesExtractor):
    def __init__(self, observation_space: gym.spaces.Box, features_dim: int = 1024):
        super().__init__(observation_space, features_dim)
        n_input_channels = observation_space.shape[1]
        
        # Architettura massiccia per gestire 20 asset simultaneamente
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


class MultiAssetTradingEnv(gym.Env):
    def __init__(self, df, window_size, num_assets):
        super().__init__()
        self.window_size = window_size
        self.num_assets = num_assets
        # Conversione in float32 per risparmiare moltissima RAM
        self.prices_and_vol = df.to_numpy(dtype=np.float32)
        
        # Spazio Azioni: MultiDiscrete. 
        # Per ognuno dei 20 asset l'IA sceglie: 0=Short, 1=Flat, 2=Long
        self.action_space = spaces.MultiDiscrete([3] * self.num_assets)
        
        # Spazio Osservazioni: 1000 candele x (20 prezzi + 20 volatilità)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, 
            shape=(self.window_size, self.num_assets * 2), 
            dtype=np.float32
        )
        
        self._start_tick = self.window_size
        self._end_tick = len(self.prices_and_vol) - 1

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self._current_tick = self._start_tick
        self._positions = np.zeros(self.num_assets, dtype=np.int32)
        self._ticks_in_position = np.zeros(self.num_assets, dtype=np.int32)
        self._entry_prices = np.zeros(self.num_assets, dtype=np.float32)
        return self._get_observation(), {}
        
    def step(self, actions):
        target_positions = actions - 1
        
        changed = (target_positions != self._positions)
        
        current_prices = self.prices_and_vol[self._current_tick, 0::2]
        last_prices = self.prices_and_vol[self._current_tick - 1, 0::2]
        
        # --- CALCOLO WIN / LOSS SUI TRADE CHIUSI ---
        closed_longs = changed & (self._positions == 1)
        closed_shorts = changed & (self._positions == -1)
        
        long_profits = current_prices[closed_longs] - self._entry_prices[closed_longs]
        short_profits = self._entry_prices[closed_shorts] - current_prices[closed_shorts]
        
        wins_this_step = int(np.sum(long_profits > 0) + np.sum(short_profits > 0))
        losses_this_step = int(np.sum(long_profits <= 0) + np.sum(short_profits <= 0))
        
        # Aggiorna il prezzo di ingresso per i nuovi trade aperti
        self._entry_prices[changed] = current_prices[changed]
        
        self._ticks_in_position[changed] = 0
        unchanged_and_active = (~changed) & (target_positions != 0)
        self._ticks_in_position[unchanged_and_active] += 1
        
        self._positions = target_positions
        
        price_diff_percent = (current_prices - last_prices) / (last_prices + 1e-8)
        
        rewards = np.zeros(self.num_assets, dtype=np.float32)
        
        rewards[target_positions == 1] += price_diff_percent[target_positions == 1]
        rewards[target_positions == -1] -= price_diff_percent[target_positions == -1]
        
        over_time = (target_positions != 0) & (self._ticks_in_position > 300)
        rewards[over_time] -= 0.0001 * (self._ticks_in_position[over_time] - 300)
        
        rewards -= 0.00001 
        
        step_reward = float(np.sum(rewards))
                
        self._current_tick += 1
        done = self._current_tick >= self._end_tick
        truncated = False
        
        info = {
            "wins": wins_this_step,
            "losses": losses_this_step
        }
        
        return self._get_observation(), step_reward, done, truncated, info
        
    def _get_observation(self):
        return self.prices_and_vol[self._current_tick - self.window_size : self._current_tick]


def prepare_multi_asset_dataframe(base_dir):
    all_files = glob.glob(f"{base_dir}/*.parquet")
    print(f"Trovati {len(all_files)} asset. Avvio fusione globale...")
    
    dfs = []
    for file in all_files:
        asset_name = os.path.basename(file).split('_')[0]
        df = pd.read_parquet(file)
        if 'datetime' in df.columns:
            df.set_index('datetime', inplace=True)
            
        # Calcolo Volatilità e formattazione
        df['returns'] = df['close'].pct_change()
        df['volatility'] = df['returns'].rolling(window=20).std()
        
        df_sub = df[['close', 'volatility']].copy()
        df_sub.rename(columns={
            'close': f'close_{asset_name}', 
            'volatility': f'vol_{asset_name}'
        }, inplace=True)
        
        dfs.append(df_sub)
        
    # Fusione di tutti gli asset su un'unica linea temporale
    merged_df = pd.concat(dfs, axis=1, join='outer')
    
    # Riempimento dei buchi per i mercati chiusi nel weekend (Azioni/Forex)
    merged_df.ffill(inplace=True)
    merged_df.bfill(inplace=True)
    merged_df.fillna(0, inplace=True) 
    
    return merged_df, len(all_files)

def make_env(df, window_size, num_assets):
    def _init():
        return MultiAssetTradingEnv(df=df, window_size=window_size, num_assets=num_assets)
    return _init


from stable_baselines3.common.callbacks import BaseCallback

class TradeMetricsCallback(BaseCallback):
    def __init__(self, verbose=0):
        super().__init__(verbose)
        self.total_wins = 0
        self.total_losses = 0

    def _on_step(self) -> bool:
        for info in self.locals.get("infos", []):
            self.total_wins += info.get("wins", 0)
            self.total_losses += info.get("losses", 0)
        return True

    def _on_rollout_end(self) -> None:
        self.logger.record("trading/winning_trades", self.total_wins)
        self.logger.record("trading/losing_trades", self.total_losses)
        if (self.total_wins + self.total_losses) > 0:
            win_rate = self.total_wins / (self.total_wins + self.total_losses)
            self.logger.record("trading/win_rate_percent", win_rate * 100)

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
    
    # 1. Pipeline di Fusione Dati
    merged_df, num_assets = prepare_multi_asset_dataframe(BASE_DIR)
    print(f"Dataframe fuso: {merged_df.shape[0]} righe, {merged_df.shape[1]} colonne (Assets: {num_assets})")
    
    # 2. Vettorizzazione (32 cloni simultanei)
    NUM_ENV = 32
    window_size = 1000 
    print(f"🚀 Creazione di {NUM_ENV} universi paralleli (Window Size: {window_size})...")
    env = SubprocVecEnv([make_env(merged_df, window_size, num_assets) for _ in range(NUM_ENV)])

    model_path = f"{MODEL_DIR}/trading_brain_v4_multiasset.zip"

    policy_kwargs = dict(
        features_extractor_class=MultiAssetFeatureExtractor,
        features_extractor_kwargs=dict(features_dim=1024),
        net_arch=[1024, 1024]
    )

    print("Evocazione dell'HEDGE FUND TITAN V4...")
    model = PPO(
        "MlpPolicy", 
        env, 
        verbose=1, 
        policy_kwargs=policy_kwargs, 
        n_steps=2048,      # Rollout massiccio
        batch_size=2048,   # Carico pesante per la VRAM della A100
        n_epochs=10, 
        learning_rate=0.0001,
        ent_coef=0.01,     # Day Trading Psychologist (Sempre attivo)
        tensorboard_log=f"{MODEL_DIR}/logs/"
    )

    print("⚡ ADDESTRAMENTO IN CORSO... ⚡")
    # Aggiunta la Callback per stampare Win Rate in tempo reale!
    model.learn(total_timesteps=10_000_000, tb_log_name="PPO_A100_Titan_V4", callback=TradeMetricsCallback())

    model.save(model_path)
    print("🎉 TITAN V4 MULTI-ASSET SALVATO!")
