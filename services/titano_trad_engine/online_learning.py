import logging
import asyncio
import os
import yfinance as yf
import pandas as pd
import numpy as np
import sys
import numpy.core
sys.modules['numpy._core'] = numpy.core
import gymnasium as gym
from gymnasium import spaces
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
from core.database import DatabaseManager

logger = logging.getLogger(__name__)
db = DatabaseManager()

class ExperienceReplayEnv(gym.Env):
    def __init__(self, evaluated_trades: list, daily_bonus: float = 0.0):
        super(ExperienceReplayEnv, self).__init__()
        self.trades = evaluated_trades
        self.current_trade_idx = 0
        self.daily_bonus = daily_bonus
        
        self.dimensione_finestra = 30
        self.action_space = spaces.Discrete(3) 
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(self.dimensione_finestra, 4), dtype=np.float32
        )
        
        self.precomputed_states = []
        self._precompute_states()
        
    def _precompute_states(self):
        logger.info(f"Ricostruzione stato per {len(self.trades)} trade storici (Scaricamento dati in corso)...")
        if not self.trades: return
        
        unique_epics = list(set([t['epic'] for t in self.trades]))
        epic_to_yf = {}
        for epic in unique_epics:
            yf_ticker = epic
            if "USD" in epic and "-" not in epic: yf_ticker = epic.replace("USD", "-USD")
            epic_to_yf[epic] = yf_ticker
            
        try:
            df_bulk = yf.download(list(epic_to_yf.values()), period="60d", interval="1d", progress=False)
        except Exception as e:
            logger.error(f"Errore download yfinance bulk: {e}")
            return

        for trade in self.trades:
            epic = trade['epic']
            yf_ticker = epic_to_yf[epic]
            direction = trade['direction']
            pnl = trade.get('outcome_pnl', 0.0)
            xgb_prob = trade.get('xgboost_prob', 0.5)
            
            try:
                df = pd.DataFrame()
                if isinstance(df_bulk.columns, pd.MultiIndex):
                    df['Close'] = df_bulk['Close'][yf_ticker]
                else:
                    df['Close'] = df_bulk['Close']
                    
                df.dropna(inplace=True)
                df['returns'] = df['Close'].pct_change()
                df['volatility'] = df['returns'].rolling(window=20).std()
                df.fillna(0, inplace=True)
                df['xgb_proxy'] = xgb_prob
                df['news_proxy'] = 0.0 # Placeholder per NLP
                
                # Taglia i dati fino alla data del trade
                trade_date = pd.to_datetime(trade['opened_at']).tz_localize(None)
                df.index = pd.to_datetime(df.index).tz_localize(None)
                storico_precedente = df[df.index <= trade_date]
                
                if len(storico_precedente) >= 30:
                    feat_matrix = storico_precedente.iloc[-30:][['returns', 'volatility', 'xgb_proxy', 'news_proxy']].to_numpy(dtype=np.float32)
                    
                    expected_action = 1
                    if direction == "BUY": expected_action = 2
                    elif direction == "SELL": expected_action = 0
                    
                    self.precomputed_states.append((feat_matrix, expected_action, pnl))
            except Exception as e:
                logger.warning(f"Impossibile ricostruire stato per {epic}: {e}")
                
        logger.info(f"Stati ricostruiti con successo: {len(self.precomputed_states)}")

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        if not self.precomputed_states:
            return np.zeros((self.dimensione_finestra, 4), dtype=np.float32), {}
            
        if self.current_trade_idx >= len(self.precomputed_states):
            self.current_trade_idx = 0
            
        self.current_obs, self.expected_action, self.current_pnl = self.precomputed_states[self.current_trade_idx]
        return self.current_obs, {}

    def step(self, action):
        reward = 0.0
        if not self.precomputed_states:
            return np.zeros((self.dimensione_finestra, 4), dtype=np.float32), 0.0, True, False, {}
            
        if action == self.expected_action:
            reward = self.current_pnl # Rafforza se PnL positivo, punisce se PnL negativo
        elif (action == 0 and self.expected_action == 2) or (action == 2 and self.expected_action == 0):
            reward = -self.current_pnl # Inverso
        elif action == 1 and self.current_pnl < 0:
            reward = self.current_pnl * 2.0 # Penalità doppia se ha deciso di Holdare un asset in perdita
        elif action == 1 and self.current_pnl > 0:
            reward = -(self.current_pnl * 1.5) # FOMO: Penalità severa per essere rimasti fermi perdendo un'occasione di profitto
            
        # Logica "Day Trading Spregiudicato" (Rischio/Rendimento bilanciato)
        if reward < 0:
            reward *= 3.0 # Le perdite e le mancate occasioni bruciano il triplo, forzando l'IA all'azione
        elif reward > 0:
            reward *= 4.0 # I profitti incassati esplodono x4! Così l'IA capisce che il rischio vale l'azione.
            
        # --- MEGA-PREMIO A SCAGLIONI ---
        # Se Titano ha raggiunto l'obiettivo giornaliero, viene perdonato e premiato.
        if self.daily_bonus > 0:
            reward += self.daily_bonus
            
        self.current_trade_idx += 1
        return self.current_obs, float(reward), True, False, {}

def get_daily_bonus():
    try:
        import redis
        import json
        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
        data = r.get("portfolio_status")
        if data:
            status = json.loads(data)
            daily_pnl_pct = status.get("daily_pnl_pct", 0.0)
            logger.info(f"Rilevato PnL Giornaliero: {daily_pnl_pct:.2f}%")
            
            # Calcolo Scaglioni
            if daily_pnl_pct >= 3.0: return 50.0   # Scaglione 6: Jackpot
            elif daily_pnl_pct >= 2.5: return 35.0 # Scaglione 5
            elif daily_pnl_pct >= 2.0: return 20.0 # Scaglione 4
            elif daily_pnl_pct >= 1.5: return 10.0 # Scaglione 3
            elif daily_pnl_pct >= 1.0: return 5.0  # Scaglione 2
            elif daily_pnl_pct >= 0.5: return 2.0  # Scaglione 1
    except Exception as e:
        logger.error(f"Errore calcolo daily bonus: {e}")
    return 0.0

def perform_online_learning():
    logger.info("🌙 Palestra Notturna: Avvio procedura di Online Learning (Experience Replay)...")
    try:
        trades = db.get_recently_evaluated_trades(limit=100)
        if not trades:
            logger.info("Nessun trade valutato recente trovato per il retraining.")
            return

        daily_bonus = get_daily_bonus()
        if daily_bonus > 0:
            logger.info(f"🏆 MEGA-PREMIO A SCAGLIONI SBLOCCATO! Bonus per i trade di oggi: +{daily_bonus}")

        logger.info(f"Trovati {len(trades)} trade passati. Creazione Ambiente Replay...")
        
        env = DummyVecEnv([lambda: ExperienceReplayEnv(trades, daily_bonus=daily_bonus)])
        
        model_path = os.path.join(os.path.dirname(__file__), "models", "Titano_V6_Universale.zip")
        if not os.path.exists(model_path):
            logger.warning(f"Modello {model_path} non trovato. Retraining abortito.")
            return
            
        from main import EstrazioneCaratteristiche # Import per garantire la ricostruzione custom object se necessario
        
        logger.info("Caricamento cervello Titano per il ri-addestramento...")
        policy_kwargs = dict(
            features_extractor_class=EstrazioneCaratteristiche,
            features_extractor_kwargs=dict(dimensione_caratteristiche=2048),
            net_arch=dict(pi=[2048, 2048, 1024], vf=[2048, 2048, 1024])
        )
        model = PPO.load(
            model_path, 
            env=env, 
            device="cpu", 
            custom_objects={
                'EstrazioneCaratteristiche': EstrazioneCaratteristiche,
                'policy_kwargs': policy_kwargs
            }
        ) # Eseguiamo su CPU per non disturbare altri processi
        
        timesteps_necessari = len(env.envs[0].precomputed_states) * 10
        if timesteps_necessari > 0:
            logger.info(f"Esecuzione Replay (Timesteps: {timesteps_necessari})...")
            model.learn(total_timesteps=timesteps_necessari)
            model.save(model_path)
            logger.info("✅ Online Learning Completato! Titano si è aggiornato sulle sue esperienze.")
        else:
            logger.info("Dati insufficienti per l'addestramento.")
            
    except Exception as e:
        logger.error(f"Errore durante l'Online Learning: {e}", exc_info=True)

def schedule_nightly_learning():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(perform_online_learning, 'cron', hour=0, minute=0)
    scheduler.start()
    logger.info("Scheduler Notturno per Online Learning attivato (Mezzanotte).")
