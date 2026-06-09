import os
import sys
import pandas as pd
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecFrameStack
from stable_baselines3.common.callbacks import EvalCallback, StopTrainingOnNoModelImprovement

# Aggiunge la root del progetto al path per importare l'ambiente
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from environment.alfacore_env import AlfacoreEnv

def train_agent(is_crypto=True, total_timesteps=10_000_000):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    data_dir = os.path.join(base_dir, 'data_pipeline')
    models_dir = os.path.join(base_dir, 'models')
    os.makedirs(models_dir, exist_ok=True)
    
    # Nomi dei file
    file_name = "Master_Crypto_V8.csv" if is_crypto else "Master_Trad_V8.csv"
    model_name = "crypto_v8_best" if is_crypto else "trad_v8_best"
    
    csv_path = os.path.join(data_dir, file_name)
    if not os.path.exists(csv_path):
        print(f"❌ Errore: File {csv_path} non trovato. Esegui prima la Data Pipeline (Fase 1).")
        return
        
    print(f"\n🚀 Inizio Addestramento PPO - Asset: {'CRYPTO' if is_crypto else 'TRAD'}")
    df = pd.read_csv(csv_path)
    
    # ---------------------------------------------------------
    # 1. SPLIT CRONOLOGICO (80% Train, 20% Validation) - Zero Leakage
    # ---------------------------------------------------------
    split_idx = int(len(df) * 0.8)
    df_train = df.iloc[:split_idx].reset_index(drop=True)
    df_val = df.iloc[split_idx:].reset_index(drop=True)
    
    print(f"Dimensione Training Set: {len(df_train)} candele")
    print(f"Dimensione Validation Set: {len(df_val)} candele")
    
    # ---------------------------------------------------------
    # 2. INIZIALIZZAZIONE AMBIENTI E FRAME STACKING
    # ---------------------------------------------------------
    def make_env(data):
        return lambda: AlfacoreEnv(df=data, is_crypto=is_crypto)
        
    # Creazione Ambienti Vettorializzati
    train_env = DummyVecEnv([make_env(df_train)])
    val_env = DummyVecEnv([make_env(df_val)])
    
    # Applicazione FrameStacking (Memoria Spaziale a 10 livelli)
    train_env = VecFrameStack(train_env, n_stack=10)
    val_env = VecFrameStack(val_env, n_stack=10)
    
    # ---------------------------------------------------------
    # 3. CALLBACKS: EARLY STOPPING E SALVATAGGIO SOTA
    # ---------------------------------------------------------
    # Ferma il training se non ci sono miglioramenti per 5 valutazioni consecutive
    stop_train_callback = StopTrainingOnNoModelImprovement(max_no_improvement_evals=5, min_evals=5, verbose=1)
    
    # Valuta la rete ogni 50.000 step sul Validation Set
    eval_callback = EvalCallback(
        val_env,
        best_model_save_path=models_dir,
        log_path=models_dir,
        eval_freq=50_000,
        deterministic=True,
        render=False,
        callback_after_eval=stop_train_callback,
        verbose=1
    )
    
    # ---------------------------------------------------------
    # 4. ARCHITETTURA RETE NEURALE PPO
    # ---------------------------------------------------------
    model = PPO(
        "MlpPolicy",
        train_env,
        gamma=0.99,            # Lungimiranza elevata
        ent_coef=0.01,         # Esplorazione forzata (anti vicoli ciechi)
        learning_rate=3e-4,    # SOTA Policy Gradient
        n_steps=2048,          # Buffer VRAM ottimale
        device="cuda",         # Forzatura Hardware Accelerator
        verbose=1
    )
    
    # ---------------------------------------------------------
    # 5. ESECUZIONE
    # ---------------------------------------------------------
    try:
        model.learn(total_timesteps=total_timesteps, callback=eval_callback)
    except KeyboardInterrupt:
        print("⚠️ Addestramento interrotto manualmente.")
        
    # Dopo l'addestramento, rinomina il best_model generato dal callback
    best_model_path = os.path.join(models_dir, "best_model.zip")
    final_model_path = os.path.join(models_dir, f"{model_name}.zip")
    
    if os.path.exists(best_model_path):
        os.rename(best_model_path, final_model_path)
        print(f"✅ Addestramento completato! Modello supremo salvato in: {final_model_path}")
    else:
        print("⚠️ Attenzione: il modello non ha generato salvataggi validi (potrebbe aver fallito subito).")

if __name__ == "__main__":
    # Esegue l'addestramento in sequenza su entrambi gli ecosistemi
    train_agent(is_crypto=True, total_timesteps=10_000_000)
    train_agent(is_crypto=False, total_timesteps=10_000_000)
