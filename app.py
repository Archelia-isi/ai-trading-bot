import streamlit as st
import pandas as pd
import numpy as np
from ui.components import render_sidebar, render_metrics, render_fake_chart, render_kill_switch
import time
from core.capital_api import CapitalComAPI
from core.gemini_sentiment import GeminiSentimentAnalyzer
from core.quant_engine import QuantEngine
from core.database import DatabaseManager
from core.notifier import TelegramNotifier

# Configurazione base della pagina Streamlit
st.set_page_config(
    page_title="AI Trading Bot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

def main():
    st.title("🤖 AI Quantitative Trading Bot")
    st.markdown("Dashboard di controllo e monitoraggio algoritmi in tempo reale.")

    # Inizializza variabili di stato
    if 'bot_running' not in st.session_state:
        st.session_state.bot_running = False
        
    if 'capital_api' not in st.session_state:
        api = CapitalComAPI()
        api.authenticate()
        st.session_state.capital_api = api

    # Inizializza i motori
    if 'gemini' not in st.session_state:
        st.session_state.gemini = GeminiSentimentAnalyzer()
    if 'db' not in st.session_state:
        st.session_state.db = DatabaseManager()
    if 'quant' not in st.session_state:
        st.session_state.quant = QuantEngine(st.session_state.capital_api, st.session_state.db)
    if 'notifier' not in st.session_state:
        st.session_state.notifier = TelegramNotifier()

    # Renderizzazione Sidebar (Profilo di rischio e Start/Stop)
    profilo_selezionato = render_sidebar()

    # Sezione Metriche
    st.markdown("### 📊 Panoramica Portafoglio (Demo)")
    render_metrics(st.session_state.capital_api)

    # Ciclo Esecutivo (quando si preme AVVIA)
    if st.session_state.bot_running:
        st.markdown("### 🔄 Esecuzione Motore in corso...")
        with st.spinner("Analisi Gemini e Quant Engine in funzione..."):
            
            # Parametri fittizi per la simulazione (in un caso reale verrebbero presi dai WebSocket Capital)
            asset_target = "Bitcoin (BTC)"
            prezzo_attuale = 65000.0
            
            # 1. Chiamata a Gemini per il Sentiment
            sentiment = st.session_state.gemini.analyze_market_sentiment(asset_target)
            score = sentiment.get("score", 50)
            
            st.info(f"**Ultimo Sentiment:** {score} / 100 - {sentiment.get('motivazione', '')}")
            
            # 2. Decisione del Quant Engine
            trade = st.session_state.quant.evaluate_and_trade(
                asset=asset_target, 
                sentiment_score=score, 
                profile_name=profilo_selezionato,
                current_price=prezzo_attuale
            )
            
            # 3. Azione e Notifica
            if trade:
                st.success(f"Operazione Eseguita! {trade['action']} su {trade['asset']}")
                st.session_state.notifier.send_trade_alert(
                    asset=trade['asset'], 
                    profile=profilo_selezionato, 
                    action=trade['action'], 
                    price=trade['price']
                )
            
        # Riavvia il loop ogni 10 secondi per aggiornare dati e grafici
        time.sleep(10)
        st.rerun()

    # Grafico PnL
    st.markdown("### 📈 Andamento Profitti/Perdite")
    render_fake_chart()
    
    # Log degli eventi
    st.markdown("### 📋 Log Operazioni Recenti")
    st.info("In attesa di connessione a Capital.com e Gemini API...", icon="⏳")
    
    # Pulsante di emergenza Kill Switch in fondo
    render_kill_switch()

if __name__ == "__main__":
    main()
