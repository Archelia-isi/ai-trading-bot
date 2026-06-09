import pandas as pd
import numpy as np
import gymnasium as gym
from gymnasium import spaces
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack
from stable_baselines3.common.callbacks import EvalCallback
import os

# ==============================================================================
# FASE 1: LA FABBRICA DEI DATI (Data Engineering & NLP Pipeline)
# ==============================================================================

def merge_nlp_and_prices(df_prezzi, df_testi, timeframe='15min'):
    """
    Risolve il bug di merge_asof: raggruppa le news nel timeframe della candela,
    somma la magnitudo degli shock e calcola il decadimento (EMA).
    """
    df_prezzi['Datetime'] = pd.to_datetime(df_prezzi['Datetime'], utc=True)
    df_testi['Date'] = pd.to_datetime(df_testi['Date'], utc=True)
    
    df_prezzi.sort_values('Datetime', inplace=True)
    df_testi.sort_values('Date', inplace=True)
    
    # 1. Raggruppamento e Somma Magnitudo
    df_testi.set_index('Date', inplace=True)
    df_news_agg = df_testi.resample(timeframe).agg(
        Raw_Shock=('Raw_BERT_Score', 'sum'),
        News_Volume=('Raw_BERT_Score', 'count')
    ).reset_index()
    
    # 2. Merge Sicuro (No Lookahead Bias)
    df_finale = pd.merge_asof(
        df_prezzi, 
        df_news_agg, 
        left_on='Datetime', 
        right_on='Date', 
        direction='backward'
    )
    
    df_finale['Raw_Shock'] = df_finale['Raw_Shock'].fillna(0.0)
    df_finale['News_Volume'] = df_finale['News_Volume'].fillna(0)
    
    # 3. Decadimento EMA e Time Since News (Anti-Sparsità)
    alpha = 0.3
    decay = 0.95
    ema_list = []
    tsn_list = []
    
    curr_ema = 0.0
    curr_tsn = 1.0 # 1.0 = nessuna news recente, 0.0 = appena uscita
    
    for shock in df_finale['Raw_Shock']:
        if shock != 0.0:
            curr_ema = (shock * alpha) + (curr_ema * (1 - alpha))
            curr_tsn = 0.0
        else:
            curr_ema = curr_ema * decay
            curr_tsn = min(1.0, curr_tsn + 0.05)
            
        ema_list.append(curr_ema)
        tsn_list.append(curr_tsn)
        
    df_finale['BERT_EMA'] = ema_list
    df_finale['Time_Since_News_Scaled'] = tsn_list
    return df_finale

def build_features(df, is_crypto=False):
    """
    Ingegneria delle feature rigorosamente Rolling (Niente Lookahead Bias).
    """
    # Evita log(0) sui ritorni
    df['Log_Return'] = np.log(df['Close'] / df['Close'].shift(1)).fillna(0.0)
    
    # Simulazione calcolo ATR e EMA per l'esempio (nella realtà dovresti avere i dati base da MT5)
    if 'High' in df.columns and 'Low' in df.columns:
        df['ATR_14'] = df['High'] - df['Low']
    else:
        df['ATR_14'] = df['Close'].rolling(14).std()
        
    if 'EMA_50' not in df.columns:
        df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
        
    # Rolling Z-Score
    rolling_mean_atr = df['ATR_14'].rolling(window=30).mean()
    rolling_std_atr = df['ATR_14'].rolling(window=30).std()
    df['ATR_Z_Score_Rolling'] = ((df['ATR_14'] - rolling_mean_atr) / rolling_std_atr).fillna(0.0)
    
    df['Mom_50_Rolling'] = ((df['Close'] - df['EMA_50']) / df['EMA_50']).fillna(0.0)
    
    # Vettori Temporali Ciclici
    df['Time_Sin'] = np.sin(2 * np.pi * df['Datetime'].dt.hour / 24)
    df['Time_Cos'] = np.cos(2 * np.pi * df['Datetime'].dt.hour / 24)
    
    if is_crypto:
        df['Day_Of_Week'] = df['Datetime'].dt.dayofweek
        df['Day_Of_Week_Sin'] = np.sin(2 * np.pi * df['Day_Of_Week'] / 7)
        df['Day_Of_Week_Cos'] = np.cos(2 * np.pi * df['Day_Of_Week'] / 7)
    else:
        # Proxy rudimentale per Time To Close
        df['Time_To_Close'] = 1.0 - (df['Datetime'].dt.hour / 24.0)
        
    # Drop NaN introdotti dai Rolling
    df.dropna(inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df

# ==============================================================================
# FASE 2: IL MOTORE FISICO UNIFICATO (Gymnasium)
# ==============================================================================

class AlfacoreEnv(gym.Env):
    def __init__(self, dataframe, is_crypto=False):
        super(AlfacoreEnv, self).__init__()
        self.df = dataframe.reset_index(drop=True)
        self.is_crypto = is_crypto
        self.MAX_STEPS = len(self.df) - 1
        
        # FISICA E CONTABILITÀ
        self.INITIAL_BALANCE = 10000.0
        self.BASE_SPREAD = 0.0020 if is_crypto else 0.00015
        self.MAX_DRAWDOWN = 0.10 if is_crypto else 0.05
        self.MAX_SIZE = 0.05 # 5% del conto a trade
        
        # AZIONI: 0 (Flat), 1 (Long), 2 (Short) -> Spazio Discreto perfetto
        self.action_space = spaces.Discrete(3)
        
        # OSSERVAZIONI: 12 (Crypto) o 11 (Trad)
        self.obs_cols = ['Log_Return', 'ATR_Z_Score_Rolling', 'Mom_50_Rolling', 
                         'Time_Sin', 'Time_Cos', 'XGB_Prob', 'BERT_EMA', 'Time_Since_News_Scaled']
        if is_crypto:
            self.obs_cols.extend(['Day_Of_Week_Sin', 'Day_Of_Week_Cos'])
        else:
            self.obs_cols.append('Time_To_Close')
            
        obs_shape = len(self.obs_cols) + 2 # + Current_Position e PnL_Latente
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(obs_shape,), dtype=np.float32)

    def reset(self, seed=None):
        super().reset(seed=seed)
        self.current_step = 0
        self.balance = self.INITIAL_BALANCE
        self.prev_equity = self.INITIAL_BALANCE
        self.current_position = 0
        self.entry_price = 0.0
        self.prev_unrealized_pnl = 0.0
        return self._get_obs(), {}

    def _get_unrealized_pnl(self, current_price):
        if self.current_position == 0 or self.entry_price == 0.0:
            return 0.0
        price_diff_pct = (current_price - self.entry_price) / self.entry_price
        trade_margin = self.INITIAL_BALANCE * self.MAX_SIZE
        return trade_margin * price_diff_pct * self.current_position

    def step(self, action):
        mapped_action = 0 if action == 0 else (1 if action == 1 else -1)
        current_market_price = self.df.iloc[self.current_step]['Close']
        
        # --- 1. MOTORE CONTABILE (Fix Realized PnL & Spread) ---
        if mapped_action != self.current_position:
            # A) Consolida il profitto/perdita PRIMA di chiudere (Fix Buco Contabile)
            if self.current_position != 0:
                realized_pnl = self._get_unrealized_pnl(current_market_price)
                self.balance += realized_pnl
                self.entry_price = 0.0
                
            # B) Paga l'attrito (Slippage Randomizzato)
            dynamic_spread = self.BASE_SPREAD * np.random.uniform(1.0, 1.5)
            if self.current_position != 0 and mapped_action != 0:
                self.balance -= self.INITIAL_BALANCE * (dynamic_spread * 2) # Flip Puro (Doppio Spread)
            else:
                self.balance -= self.INITIAL_BALANCE * dynamic_spread       # Entry/Exit
                
            # C) Salva nuovo ingresso
            if mapped_action != 0:
                self.entry_price = current_market_price
                
        # --- 2. AVANZAMENTO TEMPO ---
        self.current_step += 1
        
        # FIX CATASTROFICO: Controllo Out of Bounds prima di leggere il df
        done = False
        if self.current_step >= self.MAX_STEPS:
            done = True
            # Riporta indietro lo step per non crashare nella lettura dell'ultimo obs
            self.current_step = self.MAX_STEPS - 1 
            
        current_market_price = self.df.iloc[self.current_step]['Close']
        
        # --- 3. REWARD (Differential Sortino Proxy) ---
        current_equity = self.balance + self._get_unrealized_pnl(current_market_price)
        delta_equity = (current_equity - self.prev_equity) / self.prev_equity
        
        # Penalizza SOLO la Downside Volatility
        pnl_delta = self._get_unrealized_pnl(current_market_price) - self.prev_unrealized_pnl
        downside_stress = abs(min(0, pnl_delta)) * 0.1 
        
        raw_reward = delta_equity - downside_stress
        reward = np.clip(raw_reward * 100, -1.0, 1.0)
        
        # --- 4. CONDIZIONI DI MORTE ---
        if (self.INITIAL_BALANCE - current_equity) / self.INITIAL_BALANCE >= self.MAX_DRAWDOWN:
            done = True
            reward = -1.0 # Morte per Drawdown Eccessivo
            
        if not self.is_crypto and 'Time_To_Close' in self.df.columns:
            if self.df.iloc[self.current_step]['Time_To_Close'] <= 0.02:
                if mapped_action != 0: 
                    self._force_close(current_market_price)
                done = True
                reward -= 0.1 # Multa fine giornata
                
        if self.is_crypto and self._is_utc_midnight():
            if mapped_action != 0: 
                self._force_close(current_market_price)
            done = True

        # Aggiorna stato
        self.prev_equity = current_equity
        self.prev_unrealized_pnl = self._get_unrealized_pnl(current_market_price)
        self.current_position = mapped_action

        return self._get_obs(), float(reward), done, False, {}

    def _force_close(self, price):
        self.balance += self._get_unrealized_pnl(price)
        self.balance -= self.INITIAL_BALANCE * self.BASE_SPREAD
        self.current_position = 0
        self.entry_price = 0.0

    def _is_utc_midnight(self):
        # Esempio: se sono le 23:45 o oltre, è quasi mezzanotte
        dt = self.df.iloc[self.current_step]['Datetime']
        return dt.hour == 23 and dt.minute >= 45

    def _get_obs(self):
        # Mettiamo fallback in caso la colonna XGB_Prob mancasse nei dati finti
        obs_row = []
        for col in self.obs_cols:
            val = self.df.iloc[self.current_step].get(col, 0.5) # 0.5 come fallback per oracoli assenti
            obs_row.append(float(val))
            
        pnl_pct = 0.0
        if self.entry_price > 0:
            current_close = self.df.iloc[self.current_step]['Close']
            pnl_pct = (current_close - self.entry_price) / self.entry_price
            pnl_pct *= self.current_position
            
        obs_row.extend([float(self.current_position), float(pnl_pct)])
        return np.array(obs_row, dtype=np.float32)

# ==============================================================================
# FASE 3: TRAINING LOOP (A100 Ready)
# ==============================================================================

def train_alfacore(df_train, df_val, is_crypto=False, total_timesteps=10_000_000):
    env_train_base = AlfacoreEnv(df_train, is_crypto=is_crypto)
    env_eval_base = AlfacoreEnv(df_val, is_crypto=is_crypto)
    
    # FRAME STACKING: L'IA ora "vede" le ultime 10 candele sovrapposte
    env_train_stacked = VecFrameStack(DummyVecEnv([lambda: env_train_base]), n_stack=10)
    env_eval_stacked = VecFrameStack(DummyVecEnv([lambda: env_eval_base]), n_stack=10)
    
    model_name = "crypto_v8" if is_crypto else "trad_v8"
    os.makedirs(f"./models/{model_name}/", exist_ok=True)
    
    eval_cb = EvalCallback(
        env_eval_stacked, 
        best_model_save_path=f'./models/{model_name}/',
        eval_freq=50000 if not is_crypto else 20000, 
        deterministic=True, 
        patience=5
    )
    
    # Iperparametri tarati: Gamma 0.99 lungo termine, Entropia bilanciata
    model = PPO(
        "MlpPolicy",
        env_train_stacked,
        learning_rate=0.0003 if not is_crypto else 0.0001,
        n_steps=2048 if not is_crypto else 4096,
        batch_size=256,
        gamma=0.99,
        ent_coef=0.01 if not is_crypto else 0.02,
        verbose=1,
        device="cuda" # Forza l'uso della GPU A100 su Colab
    )
    
    print(f"🚀 Avviando l'addestramento per Alfacore {'CRYPTO' if is_crypto else 'TRAD'}...")
    model.learn(total_timesteps=total_timesteps, callback=eval_cb)
    print("✅ Addestramento completato!")
    return model

if __name__ == "__main__":
    print("Alfacore V8 Master Script Inizializzato. Pronti per generare dati e addestrare!")
