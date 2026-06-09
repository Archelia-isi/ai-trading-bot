import pandas as pd
import os

def merge_master_datasets(is_crypto=True):
    """
    Incrocia i dati fisici (OHLCV) con gli Oracoli generati (XGBoost e FinBERT)
    usando rigorosamente merge_asof(direction='backward') per impedire
    qualsiasi contaminazione futura (Zero Lookahead Bias).
    """
    print(f"🧬 Avvio Fusione Master Dataset ({'CRYPTO' if is_crypto else 'TRAD'})...")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Nomi file
    file_prezzi = "raw_crypto_M15.csv" if is_crypto else "raw_trad_M1.csv"
    file_nlp = "oracle_crypto_nlp.csv" if is_crypto else "oracle_trad_nlp.csv"
    file_xgb = "oracle_xgboost_probs.csv" 
    
    percorso_prezzi = os.path.join(base_dir, file_prezzi)
    percorso_nlp = os.path.join(base_dir, file_nlp)
    percorso_xgb = os.path.join(base_dir, file_xgb)
    
    # 1. Caricamento Prezzi
    if not os.path.exists(percorso_prezzi):
        print(f"❌ File prezzi mancante: {percorso_prezzi}")
        return
    df_prezzi = pd.read_csv(percorso_prezzi)
    df_prezzi['Datetime'] = pd.to_datetime(df_prezzi['Datetime'])
    df_prezzi.sort_values('Datetime', inplace=True)
    
    # 2. Caricamento e Fusione Oracolo NLP
    if os.path.exists(percorso_nlp):
        df_nlp = pd.read_csv(percorso_nlp)
        df_nlp['Datetime'] = pd.to_datetime(df_nlp['Datetime'])
        df_nlp.sort_values('Datetime', inplace=True)
        
        # Unione asof backward: associa ad ogni candela l'ultima news disponibile PRIMA o DURANTE la candela
        df_master = pd.merge_asof(df_prezzi, df_nlp, on='Datetime', direction='backward')
        df_master.fillna({'BERT_Sentiment_EMA': 0.0, 'Time_Since_News_Scaled': 0.0}, inplace=True)
        print("✅ Oracolo NLP Fuso correttamente.")
    else:
        print("⚠️ Oracolo NLP mancante. Generazione dummy...")
        df_master = df_prezzi.copy()
        df_master['BERT_Sentiment_EMA'] = 0.0
        df_master['Time_Since_News_Scaled'] = 0.0
        
    # 3. Caricamento e Fusione Oracolo XGBoost
    if os.path.exists(percorso_xgb):
        df_xgb = pd.read_csv(percorso_xgb)
        df_xgb['Datetime'] = pd.to_datetime(df_xgb['Datetime'])
        df_xgb.sort_values('Datetime', inplace=True)
        
        df_master = pd.merge_asof(df_master, df_xgb, on='Datetime', direction='backward')
        df_master.dropna(subset=['XGB_Prob'], inplace=True) # Elimina le candele di bootstrap XGBoost
        print("✅ Oracolo XGBoost Fuso correttamente.")
    else:
        print("⚠️ Oracolo XGBoost mancante. Generazione dummy...")
        df_master['XGB_Prob'] = 0.5
        
    # 4. Feature Ingegneria Finale Rigorosa (Senza Lookahead)
    df_master['Log_Return'] = df_master['Close'] / df_master['Close'].shift(1) - 1
    # Implementa un ATR semplificato proxy (True Range approssimato)
    df_master['TR'] = df_master['High'] - df_master['Low']
    atr = df_master['TR'].rolling(14).mean()
    df_master['ATR_Z_Score'] = (atr - atr.rolling(50).mean()) / atr.rolling(50).std()
    df_master['Mom_50'] = df_master['Close'] / df_master['Close'].shift(50) - 1
    
    df_master.dropna(inplace=True)
    
    # 5. Esportazione
    output_name = "Master_Crypto_V8.csv" if is_crypto else "Master_Trad_V8.csv"
    output_file = os.path.join(base_dir, output_name)
    df_master.to_csv(output_file, index=False)
    print(f"🚀 FASE 1 COMPLETATA. Dataset Supremo generato: {output_file} (Righe: {len(df_master)})")

if __name__ == "__main__":
    merge_master_datasets(is_crypto=True)
    merge_master_datasets(is_crypto=False)
