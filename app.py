import streamlit as st
import pandas as pd
import numpy as np
from ui.components import render_sidebar, render_metrics, render_fake_chart, render_kill_switch
import time
import random
from core.capital_api import CapitalComAPI
from core.capital_api import CapitalComAPI
from core.gemini_sentiment import GeminiSentimentAnalyzer
from core.quant_engine import QuantEngine
from core.database import DatabaseManager
from core.notifier import TelegramNotifier
from core.market_discovery import MarketDiscovery

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
    if 'discovery' not in st.session_state:
        st.session_state.discovery = MarketDiscovery()
    
    # Memoria HFT
    if 'open_positions' not in st.session_state:
        st.session_state.open_positions = {}
    if 'cooldowns' not in st.session_state:
        st.session_state.cooldowns = {}

    # Renderizzazione Sidebar (Profilo di rischio e Start/Stop)
    profilo_selezionato = render_sidebar()

    # Sezione Metriche
    st.markdown("### 📊 Panoramica Portafoglio (Demo)")
    render_metrics(st.session_state.capital_api)

    # Ciclo Esecutivo (quando si preme AVVIA)
    if st.session_state.bot_running:
        st.markdown("### 🔄 Esecuzione Motore in corso...")
        
        # --- FASE 1: GESTIONE TRAILING STOP ---
        with st.spinner("🛡️ Fase 1: Gestione Posizioni Aperte (Trailing Stop)..."):
            current_time = time.time()
            to_remove = []
            
            for epic, pos in st.session_state.open_positions.items():
                current_price = st.session_state.capital_api.get_market_price(epic)
                clean_name = pos['name']
                
                if pos['action'] == 'LONG':
                    if current_price > pos['current_high']:
                        pos['current_high'] = current_price
                    
                    sl_price = pos['current_high'] * (1 - pos['sl_distance'])
                    if current_price <= sl_price:
                        st.warning(f"📉 TRAILING STOP COLPITO su {clean_name}! Vendita a €{current_price} (Max: €{pos['current_high']})")
                        to_remove.append(epic)
                        st.session_state.cooldowns[clean_name] = current_time + (2 * 3600) # 2 ore
                        
                elif pos['action'] == 'SHORT':
                    if current_price < pos['current_low']:
                        pos['current_low'] = current_price
                    
                    sl_price = pos['current_low'] * (1 + pos['sl_distance'])
                    if current_price >= sl_price:
                        st.warning(f"📈 TRAILING STOP COLPITO su {clean_name}! Ricopertura a €{current_price} (Min: €{pos['current_low']})")
                        to_remove.append(epic)
                        st.session_state.cooldowns[clean_name] = current_time + (2 * 3600)
            
            for epic in to_remove:
                del st.session_state.open_positions[epic]

        # --- FASE 2: CACCIA AGLI ASSET ---
        with st.spinner("🌍 Fase 2: Ricerca Web degli Asset Caldi tramite Google Search..."):
            
            # 1. Discovery
            trending_assets_names = st.session_state.discovery.get_trending_assets()
            st.write(f"**Asset individuati dalle news:** {', '.join(trending_assets_names)}")
            
            # 2. Iterazione sugli asset scoperti
            for raw_asset_name in trending_assets_names:
                st.markdown(f"#### Analisi: {raw_asset_name}")
                
                # Cerca lo strumento su Capital.com
                instrument = st.session_state.capital_api.search_instrument(raw_asset_name)
                if not instrument:
                    st.warning(f"L'asset '{raw_asset_name}' non è stato trovato su Capital.com. Saltato.")
                    continue
                
                epic = instrument['epic']
                clean_name = instrument['name']
                prezzo_attuale = st.session_state.capital_api.get_market_price(epic)
                st.write(f"↳ Match su Capital.com: **{clean_name}** ({epic}) a €{prezzo_attuale}")
                
                # 3. Sentiment & Quant
                sentiment = st.session_state.gemini.analyze_market_sentiment(clean_name)
                
                score = sentiment.get("score", 50)
                conviction = sentiment.get("conviction", 1)
                asset_risk = sentiment.get("asset_risk", "LOW")
                motivazione = sentiment.get("motivazione", "")
                
                st.info(f"Sentiment {clean_name}: Score {score}/100 | Conviction: {conviction}/10 | Rischio Asset: {asset_risk} \n\nMotivo: {motivazione}")
                
                # Check Cooldown
                in_cooldown = clean_name in st.session_state.cooldowns and time.time() < st.session_state.cooldowns[clean_name]
                if in_cooldown and conviction < 9:
                    st.warning(f"L'asset {clean_name} è in QUARANTENA (cooldown). Conviction ({conviction}) troppo bassa per forzare il blocco.")
                    continue
                
                # Check se già aperto
                if epic in st.session_state.open_positions:
                    st.write(f"{clean_name} già in portafoglio. Skippo acquisto.")
                    continue

                trade = st.session_state.quant.evaluate_and_trade(
                    asset=clean_name, 
                    sentiment_data=sentiment, 
                    profile_name=profilo_selezionato,
                    current_price=prezzo_attuale
                )
                
                if trade and trade['action']:
                    st.success(f"Operazione Eseguita! {trade['action']} su {trade['asset']}")
                    
                    # Salva in memoria per il Trailing Stop
                    st.session_state.open_positions[epic] = {
                        "name": clean_name,
                        "action": trade['action'],
                        "entry_price": prezzo_attuale,
                        "current_high": prezzo_attuale,
                        "current_low": prezzo_attuale,
                        "sl_distance": trade['sl_distance']
                    }
                    
                    st.session_state.notifier.send_trade_alert(
                        asset=trade['asset'], 
                        profile=profilo_selezionato, 
                        action=trade['action'], 
                        price=trade['price']
                    )
            
        # Pausa lunga per evitare rate limit e dare tempo al mercato
        time.sleep(180)
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
