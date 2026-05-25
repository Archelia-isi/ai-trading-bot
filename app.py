import streamlit as st
import pandas as pd
import numpy as np
from ui.components import render_sidebar, render_metrics, render_fake_chart, render_kill_switch

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

    # Renderizzazione Sidebar (Profilo di rischio e Start/Stop)
    profilo_selezionato = render_sidebar()

    # Sezione Metriche (Fittizie per ora, le collegheremo alle API nella Fase 2)
    st.markdown("### 📊 Panoramica Portafoglio (Demo)")
    render_metrics()

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
