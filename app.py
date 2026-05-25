import streamlit as st
import pandas as pd
import numpy as np
from ui.components import render_sidebar, render_metrics, render_fake_chart, render_kill_switch
from core.capital_api import CapitalComAPI

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

    # Renderizzazione Sidebar (Profilo di rischio e Start/Stop)
    profilo_selezionato = render_sidebar()

    # Sezione Metriche
    st.markdown("### 📊 Panoramica Portafoglio (Demo)")
    render_metrics(st.session_state.capital_api)

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
