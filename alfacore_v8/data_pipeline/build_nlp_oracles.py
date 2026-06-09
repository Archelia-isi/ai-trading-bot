import pandas as pd
import numpy as np
import os
import torch
from transformers import pipeline

def build_nlp_oracles(csv_path="news_dump.csv", is_crypto=True, batch_size=256):
    """
    Processa un dump massivo di notizie utilizzando HuggingFace BERT ottimizzato per GPU A100.
    Applica il fix architettonico (Resampling + Sentiment EMA + Time Decay) per preservare
    la magnitudo dell'informazione e curare la sparsità neurale.
    """
    print("🧠 Inizializzazione Oracolo NLP (HuggingFace)...")
    
    # Controlla la disponibilità della GPU A100 (device=0)
    device = 0 if torch.cuda.is_available() else -1
    model_name = "ElfaI/finbert-sentiment" if not is_crypto else "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
    
    # Inizializza la pipeline
    nlp_pipe = pipeline("sentiment-analysis", model=model_name, device=device)
    
    # Simulazione caricamento se il file non esiste (solo per sviluppo)
    if not os.path.exists(csv_path):
        print(f"⚠️ File {csv_path} non trovato. Generazione dati dummy per il collaudo...")
        dates = pd.date_range(start='2024-01-01', end='2024-06-01', freq='2h')
        df_news = pd.DataFrame({'Datetime': dates, 'Text': ["Market is surging!"] * len(dates)})
    else:
        df_news = pd.read_csv(csv_path)
        df_news['Datetime'] = pd.to_datetime(df_news['Datetime'])
        
    texts = df_news['Text'].astype(str).tolist()
    
    print(f"🚀 Avvio inferenza batching GPU su {len(texts)} notizie...")
    raw_scores = []
    
    # Esecuzione in batching puro per GPU
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        results = nlp_pipe(batch)
        for res in results:
            # Converte sentiment in score (-1 a +1)
            score = res['score'] if res['label'] in ['POSITIVE', 'positive', 'bullish'] else -res['score']
            raw_scores.append(score)
            
    df_news['Raw_BERT_Score'] = raw_scores
    
    print("⏳ Applicazione FIX CRITICO: Resampling e Mappatura SOTA...")
    df_news.set_index('Datetime', inplace=True)
    
    # Raggruppiamo la forza per time-step (15m per crypto, 1m per trad)
    timeframe = '15min' if is_crypto else '1min'
    df_news_agg = df_news.resample(timeframe).agg(
        Raw_Shock=('Raw_BERT_Score', 'sum'),
        News_Volume=('Raw_BERT_Score', 'count')
    ).reset_index()
    
    df_news_agg.fillna(0, inplace=True)
    
    # Calcolo Sentiment EMA per decadimento shock
    df_news_agg['BERT_Sentiment_EMA'] = df_news_agg['Raw_Shock'].ewm(span=14, adjust=False).mean()
    
    # Calcolo Time Since News (per evitare la "cecità da sparsità" della rete)
    # Riavvia il contatore quando c'è una news (Raw_Shock != 0)
    df_news_agg['Bars_Since_News'] = df_news_agg.groupby(df_news_agg['Raw_Shock'] != 0).cumcount()
    
    # Scalatura min-max (es. massimale 4 ore: 16 barre da 15 min, o 240 da 1 min)
    max_bars = 16 if is_crypto else 240
    # Decadimento esponenziale: da 1 (recente) a 0 (molto vecchio)
    df_news_agg['Time_Since_News_Scaled'] = np.exp(-df_news_agg['Bars_Since_News'] / (max_bars / 2))
    
    output_dir = os.path.dirname(os.path.abspath(__file__))
    output_name = "oracle_crypto_nlp.csv" if is_crypto else "oracle_trad_nlp.csv"
    output_file = os.path.join(output_dir, output_name)
    
    df_news_agg.to_csv(output_file, index=False)
    print(f"✅ Oracolo NLP completato: Salato in {output_file}.")

if __name__ == "__main__":
    build_nlp_oracles(is_crypto=True)
