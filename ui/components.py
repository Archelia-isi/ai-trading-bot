import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

def render_sidebar():
    """Renderizza la barra laterale con i controlli principali"""
    with st.sidebar:
        st.header("⚙️ Impostazioni Bot")
        
        profili_rischio = {
            "Il Pirata 🏴‍☠️": "Crypto volatili, Meme Stocks (Leva Massima)",
            "Il Velocista ⚡": "Materie Prime, Tech USA (Leva Media)",
            "Il Moderato 🛡️": "Indici Azionari, Forex Major (Leva Bassa)",
            "La Fortezza 🏰": "Oro Spot, Titoli di Stato (Leva 1:1)"
        }
        
        profilo = st.selectbox(
            "Seleziona Profilo di Rischio", 
            options=list(profili_rischio.keys()),
            help="Scegli il profilo di rischio. Attenzione: influenzerà leve, size e soglie di intervento."
        )
        
        st.caption(f"**Target:** {profili_rischio[profilo]}")
        st.divider()
        
        st.subheader("Controllo Motore")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ AVVIA", type="primary", use_container_width=True, disabled=st.session_state.bot_running):
                st.session_state.bot_running = True
                st.rerun()
        with col2:
            if st.button("⏸️ FERMA", type="secondary", use_container_width=True, disabled=not st.session_state.bot_running):
                st.session_state.bot_running = False
                st.rerun()
                
        if st.session_state.bot_running:
            st.success("🟢 Bot Attivo e in ascolto")
        else:
            st.warning("🔴 Bot Fermo")
            
        st.divider()
        st.subheader("Database")
        if st.button("🗑️ Svuota Database", help="Cancella tutti i log dei trade simulati o vecchi.", use_container_width=True):
            if 'db' in st.session_state:
                st.session_state.db.truncate_logs()
                st.toast("Database svuotato con successo!", icon="✅")
                st.rerun()
            
        return profilo

def render_metrics(api):
    """Renderizza i KPI del portafoglio"""
    saldo = api.get_account_balance()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Saldo (Paper Trading)", f"€ {saldo:,.2f}", "")
    col2.metric("Posizioni Aperte", "0", "")
    col3.metric("Drawdown Attuale", "0.00%", "-")
    col4.metric("Ultimo Sentiment", "In attesa...", "")

def render_fake_chart():
    """Renderizza un grafico fittizio per il PnL per testare la UI"""
    # Generiamo un grafico fittizio per dare l'idea della dashboard
    date_rng = pd.date_range(start='2023-01-01', end='2023-01-10', freq='h')
    df = pd.DataFrame(date_rng, columns=['Data'])
    df['PnL Cumulativo (€)'] = np.random.randn(len(date_rng)).cumsum() * 100 + 10000
    
    fig = px.line(df, x='Data', y='PnL Cumulativo (€)', template="plotly_dark")
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=300)
    st.plotly_chart(fig, use_container_width=True)

from core.notifier import TelegramNotifier

def render_kill_switch():
    """Renderizza il bottone di emergenza per chiudere tutto"""
    st.divider()
    st.markdown("### ⚠️ Procedure di Emergenza")
    if st.button("🚨 KILL SWITCH MANUALE (Chiudi tutte le posizioni)", type="primary"):
        st.error("KILL SWITCH ATTIVATO! Invio segnale di chiusura massiva e arresto bot...", icon="🚨")
        # Logica di chiusura
        st.session_state.bot_running = False
        st.toast("Tutte le posizioni chiuse (Simulazione)", icon="✅")
        
        # Invio Allarme su Telegram
        notifier = TelegramNotifier()
        notifier.send_kill_switch_alert()
