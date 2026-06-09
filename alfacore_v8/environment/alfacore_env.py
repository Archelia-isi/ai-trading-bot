import gymnasium as gym
from gymnasium import spaces
import numpy as np
import pandas as pd

class AlfacoreEnv(gym.Env):
    """
    Motore Fisico di Simulazione per Alfacore V8.
    Zero Lookahead Bias. Matematica Realized PnL. Slippage Stocastico.
    """
    def __init__(self, df: pd.DataFrame, is_crypto=True):
        super().__init__()
        self.df = df.copy()
        self.is_crypto = is_crypto
        
        # Gestione Sicura dell'Indice Temporale
        if 'Datetime' in self.df.columns:
            self.df['Datetime'] = pd.to_datetime(self.df['Datetime'])
        else:
            raise ValueError("Il DataFrame deve contenere obbligatoriamente una colonna 'Datetime'.")
            
        # Stato dell'Episodio
        self.current_step = 0
        self.balance = 10000.0  # Capitale Iniziale
        self.current_position = 0  # 0: Flat, 1: Long, -1: Short
        self.entry_price = 0.0
        
        # Fisica di Rete
        # Crypto: Base spread 0.20% | Tradizionale: Base spread 0.015% (es. Nasdaq)
        self.BASE_SPREAD = 0.0020 if is_crypto else 0.00015
        self.MAX_SIZE = 0.05  # Rischio fisso 5% per trade
        
        # Azioni: 0 (Chiudi/Flat), 1 (Compra/Long), 2 (Vendi/Short)
        self.action_space = spaces.Discrete(3)
        
        # FIX CRITICO: Spazio di Osservazione Esatto come da Master Blueprint
        # Crypto = 12 Feature (include Day_Of_Week) | Trad = 11 Feature (include Time_To_Close)
        self.obs_dim = 12 if is_crypto else 11
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(self.obs_dim,), dtype=np.float32)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = 0
        self.balance = 10000.0
        self.current_position = 0
        self.entry_price = 0.0
        return self._get_obs(), {}

    def _get_unrealized_pnl(self, current_price):
        if self.current_position == 0 or self.entry_price == 0.0: 
            return 0.0
        
        size_investita = self.balance * self.MAX_SIZE
        variazione_pct = (current_price - self.entry_price) / self.entry_price
        return size_investita * variazione_pct * self.current_position

    def _get_obs(self):
        row = self.df.iloc[self.current_step]
        dt = row['Datetime']
        price = row['Close']
        
        # 1. Feature Temporali (Orologio 24h Base)
        ora_decimale = dt.hour + dt.minute / 60.0
        time_sin = np.sin(ora_decimale * (2. * np.pi / 24.))
        time_cos = np.cos(ora_decimale * (2. * np.pi / 24.))
        
        # 2. Esposizione al Rischio (PnL_Latente_%)
        pnl_latente_pct = 0.0
        if self.current_position != 0 and self.entry_price > 0:
            pnl_val = self._get_unrealized_pnl(price)
            pnl_latente_pct = pnl_val / self.balance
            
        # 3. Assemblaggio Feature Condivise (10 Feature)
        base_obs = [
            float(row.get('Log_Return', 0.0)),
            float(row.get('ATR_Z_Score', 0.0)),
            float(row.get('Mom_50', 0.0)),
            float(row.get('BERT_Sentiment_EMA', 0.0)),
            float(row.get('Time_Since_News_Scaled', 0.0)), # FIX SOTA Sparsità
            float(row.get('XGB_Prob', 0.5)),
            float(self.current_position),
            float(pnl_latente_pct), # Rischio Interno
            float(time_sin),
            float(time_cos)
        ]
        
        # 4. Feature Specifiche Asset Class
        if self.is_crypto:
            # CRYPTO (2 Feature in più = 12 totali)
            giorno_settimana = dt.weekday() # 0 = Lunedì, 6 = Domenica
            day_sin = np.sin(giorno_settimana * (2. * np.pi / 7.))
            day_cos = np.cos(giorno_settimana * (2. * np.pi / 7.))
            base_obs.extend([float(day_sin), float(day_cos)])
        else:
            # TRADIZIONALE (1 Feature in più = 11 totali)
            # Time to close = normalizzazione del tempo rimanente prima delle 22:00
            ora_chiusura = 22.0
            ore_rimanenti = ora_chiusura - ora_decimale
            if ore_rimanenti < 0: 
                ore_rimanenti = 0.0
            time_to_close = ore_rimanenti / 24.0
            base_obs.append(float(time_to_close))
            
        return np.array(base_obs, dtype=np.float32)

    def step(self, action):
        # Mappatura Azione (0 -> 0, 1 -> +1, 2 -> -1)
        mapped_action = 0 if action == 0 else (1 if action == 1 else -1)
        
        row = self.df.iloc[self.current_step]
        price = row['Close']
        dt = row['Datetime']
        
        # Fotografia dello stato PRIMA dell'azione (per il Sortino Proxy)
        prev_equity = self.balance + self._get_unrealized_pnl(price)
        prev_pnl = self._get_unrealized_pnl(price)
        
        # ---------------------------------------------------------
        # FIX CRITICO: MOTORE CONTABILE REALIZED PnL
        # ---------------------------------------------------------
        if mapped_action != self.current_position:
            # Calcolo Slippage Stocastico
            moltiplicatore_slippage = np.random.uniform(1.0, 1.5)
            
            # Doppio spread in caso di Flip (Inversione Long -> Short diretta)
            if self.current_position != 0 and mapped_action != 0:
                moltiplicatore_slippage *= 2.0
                
            fee_slippage = (self.balance * self.MAX_SIZE) * (self.BASE_SPREAD * moltiplicatore_slippage)
            
            # Se avevamo una posizione aperta, realizziamo il PnL fisicamente nel Balance
            if self.current_position != 0:
                self.balance += self._get_unrealized_pnl(price)
                
            # Paghiamo i broker
            self.balance -= fee_slippage
            
            # Assegnamo il nuovo prezzo di ingresso (o 0.0 se siamo andati Flat)
            self.entry_price = price if mapped_action != 0 else 0.0
            
        # Aggiorna lo stato interno
        self.current_position = mapped_action
        self.current_step += 1
        
        done = False
        reward = 0.0
        
        # Fine storico dati
        if self.current_step >= len(self.df) - 1:
            done = True
        else:
            # Calcolo Reward basato sul prossimo time-step (T+1)
            next_row = self.df.iloc[self.current_step]
            next_price = next_row['Close']
            next_dt = next_row['Datetime']
            
            current_equity = self.balance + self._get_unrealized_pnl(next_price)
            current_pnl = self._get_unrealized_pnl(next_price)
            
            # ---------------------------------------------------------
            # REWARD: SORTINO PROXY
            # ---------------------------------------------------------
            delta_equity = current_equity - prev_equity
            pnl_delta = current_pnl - prev_pnl
            
            # Multa proporzionale per volatilità negativa latente (Drawdown Fluttuante)
            volatilita_negativa = abs(min(0, pnl_delta)) * 0.1
            reward = delta_equity - volatilita_negativa
            
            # ---------------------------------------------------------
            # CONDIZIONI DI TERMINE E REGOLE DI CHIUSURA
            # ---------------------------------------------------------
            
            # 1. Margin Call (Drawdown > 20%)
            if current_equity < 8000.0:
                done = True
                reward -= 100.0 # Punizione severa per bancarotta
                
            # 2. Orari di Chiusura / Daytrading
            if self.is_crypto:
                # Modello CRYPTO (24/7): Zombie Reset
                # Se cambia il giorno (Mezzanotte UTC) e la posizione è aperta
                if next_dt.day != dt.day and self.current_position != 0:
                    # Chiusura Forzata senza penalità extra
                    self.balance += self._get_unrealized_pnl(next_price)
                    self.balance -= (self.balance * self.MAX_SIZE) * self.BASE_SPREAD
                    self.current_position = 0
                    self.entry_price = 0.0
            else:
                # Modello TRAD (Daytrading): Time_To_Close penalizzato
                ora_decimale_next = next_dt.hour + next_dt.minute / 60.0
                ora_chiusura = 22.0
                ore_rimanenti = ora_chiusura - ora_decimale_next
                time_to_close = ore_rimanenti / 24.0 if ore_rimanenti > 0 else 0.0
                
                # Se mancano <= 0.02 (circa 28 minuti, ovvero le 21:32)
                if time_to_close <= 0.02 and self.current_position != 0:
                    # Chiusura Forzata e Multa d'ufficio per non aver chiuso da solo
                    self.balance += self._get_unrealized_pnl(next_price)
                    self.balance -= (self.balance * self.MAX_SIZE) * self.BASE_SPREAD
                    self.current_position = 0
                    self.entry_price = 0.0
                    reward -= 5.0 # Penalità educativa
                    
        return self._get_obs(), float(reward), done, False, {}
