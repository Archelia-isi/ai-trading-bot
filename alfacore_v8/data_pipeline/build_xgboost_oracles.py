import pandas as pd
import numpy as np
import xgboost as xgb
import os
from dateutil.relativedelta import relativedelta

def build_xgboost_oracles(price_csv="raw_crypto_M15.csv"):
    """
    Applica la rigorosa Walk-Forward Validation su XGBoost (Zero Lookahead Bias).
    Addestra su finestre di 3 mesi, prevede il 4° mese, e scorre in avanti.
    """
    print("🌲 Inizializzazione Oracolo XGBoost (Walk-Forward Validation)...")
    
    if not os.path.exists(price_csv):
        print(f"⚠️ File {price_csv} non trovato. (Generazione Mockup per validazione struttura).")
        dates = pd.date_range(start='2024-01-01', end='2024-06-01', freq='15min')
        df = pd.DataFrame({'Datetime': dates, 'Close': np.random.uniform(60000, 70000, len(dates))})
    else:
        df = pd.read_csv(price_csv)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        
    df.sort_values('Datetime', inplace=True)
    
    # Feature Engineering Semplice (Senza Bias)
    df['Log_Return'] = np.log(df['Close'] / df['Close'].shift(1))
    df['Target'] = (df['Log_Return'].shift(-1) > 0).astype(int) # 1 se candela successiva sale
    df.dropna(inplace=True)
    
    features = ['Log_Return'] # Da espandere con RSI, MACD calcolati rigorosamente su storico
    
    start_date = df['Datetime'].min()
    end_date = df['Datetime'].max()
    
    current_train_start = start_date
    df['XGB_Prob'] = np.nan
    
    print(f"Inizio sliding window da {start_date.date()} a {end_date.date()}")
    
    # Modello ottimizzato GPU
    model = xgb.XGBClassifier(
        n_estimators=100, learning_rate=0.05, max_depth=4,
        tree_method='hist', device='cuda' 
    )
    
    while True:
        train_end = current_train_start + relativedelta(months=3)
        test_end = train_end + relativedelta(months=1)
        
        if train_end >= end_date:
            break
            
        # Filtro dataset
        train_mask = (df['Datetime'] >= current_train_start) & (df['Datetime'] < train_end)
        test_mask = (df['Datetime'] >= train_end) & (df['Datetime'] < test_end)
        
        df_train = df[train_mask]
        df_test = df[test_mask]
        
        if len(df_train) < 100 or len(df_test) < 10:
            current_train_start += relativedelta(months=1)
            continue
            
        X_train, y_train = df_train[features], df_train['Target']
        X_test = df_test[features]
        
        print(f"Addestramento: [{current_train_start.date()} -> {train_end.date()}] | Previsione: [{train_end.date()} -> {test_end.date()}]")
        
        model.fit(X_train, y_train)
        
        # Salviamo la PROBABILITA' (0-1) e non la classe secca
        probs = model.predict_proba(X_test)[:, 1]
        df.loc[test_mask, 'XGB_Prob'] = probs
        
        current_train_start += relativedelta(months=1)
        
    df.dropna(subset=['XGB_Prob'], inplace=True) # Elimina i primi 3 mesi (Periodo di Bootstrap)
    
    output_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(output_dir, "oracle_xgboost_probs.csv")
    
    df[['Datetime', 'XGB_Prob']].to_csv(output_file, index=False)
    print(f"✅ Walk-Forward XGBoost Completato. Output salvato in {output_file}.")

if __name__ == "__main__":
    build_xgboost_oracles()
