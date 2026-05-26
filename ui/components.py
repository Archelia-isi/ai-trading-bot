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
    pos_list = api.get_all_positions()
    num_positions = len(pos_list)
    
    col1.metric("Saldo Capitale (Live)", f"€ {saldo:,.2f}", "")
    col2.metric("Posizioni Aperte", str(num_positions), "")
    
    # Calculate total UPL
    tot_upl = sum(p.get('position', {}).get('upl', 0.0) for p in pos_list)
    col3.metric("PnL Fluttuante", f"€ {tot_upl:,.2f}", f"{(tot_upl/saldo*100):.2f}%" if saldo > 0 else "")
    col4.metric("Ultimo Sentiment", "Attivo", "")

def render_portfolio(api):
    """Renderizza la tabella del portafoglio live con conversione in Euro."""
    col1, col2 = st.columns([8, 2])
    with col2:
        if st.button("🔄 Aggiorna Dati", use_container_width=True):
            st.rerun()
            
    positions = api.get_all_positions()
    
    if not positions:
        st.info("Nessuna posizione aperta al momento.")
        return
        
    exchange_rates = {}
    
    def get_eur_rate(currency):
        if currency == "EUR":
            return 1.0
        if currency in exchange_rates:
            return exchange_rates[currency]
            
        pair_epic = f"EUR{currency}"
        rate = api.get_market_price(pair_epic)
        if rate == 100.0 or rate == 0:
            fallbacks = {"USD": 1.05, "GBP": 0.85, "JPY": 160.0, "CHF": 0.95}
            rate = fallbacks.get(currency, 1.0)
            
        exchange_rates[currency] = rate
        return rate
        
    data = []
    
    for p in positions:
        pos = p.get('position', {})
        mkt = p.get('market', {})
        
        name = mkt.get('instrumentName', 'Unknown')
        direction = pos.get('direction', 'BUY')
        size = pos.get('size', 0.0)
        currency = pos.get('currency', 'EUR')
        entry_price = pos.get('level', 0.0)
        
        current_price = mkt.get('bid', 0.0) if direction == 'BUY' else mkt.get('offer', 0.0)
        
        upl_eur = pos.get('upl', 0.0)
        
        nominal_local = size * current_price
        
        rate = get_eur_rate(currency)
        nominal_eur = nominal_local / rate if rate else nominal_local
        investito_eur = (size * entry_price) / rate if rate else (size * entry_price)
        
        if investito_eur > 0:
            pnl_perc = (upl_eur / investito_eur) * 100
        else:
            pnl_perc = 0.0
            
        data.append({
            "Titolo": f"{'🟢' if direction=='BUY' else '🔴'} {name}",
            "Dir": direction,
            "Size": size,
            "Acquisto": f"{entry_price:,.4f} {currency}",
            "Attuale": f"{current_price:,.4f} {currency}",
            "Investito (€)": investito_eur,
            "Valore (€)": nominal_eur,
            "Guadagno/Perdita (€)": upl_eur,
            "Guadagno/Perdita (%)": pnl_perc
        })
        
    df = pd.DataFrame(data)
    
    def color_pnl(val):
        color = 'green' if val > 0 else 'red' if val < 0 else 'gray'
        return f'color: {color}'
        
    styled_df = df.style.format({
        "Investito (€)": "€ {:,.2f}",
        "Valore (€)": "€ {:,.2f}",
        "Guadagno/Perdita (€)": "€ {:,.2f}",
        "Guadagno/Perdita (%)": "{:,.2f} %"
    }).map(color_pnl, subset=["Guadagno/Perdita (€)", "Guadagno/Perdita (%)"])
    
    st.dataframe(styled_df, use_container_width=True, hide_index=True)

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
        # Logica di chiusura REALE
        st.session_state.bot_running = False
        
        if 'capital_api' in st.session_state and st.session_state.capital_api.is_authenticated:
            st.info("Chiusura di emergenza in corso sul broker...")
            pos_aperte = st.session_state.capital_api.get_all_positions()
            chiuse = 0
            for p in pos_aperte:
                deal_id = p.get('position', {}).get('dealId')
                if deal_id:
                    if hasattr(st.session_state.capital_api, 'close_position_by_deal_id'):
                        st.session_state.capital_api.close_position_by_deal_id(deal_id)
                    else:
                        epic = p.get('market', {}).get('epic')
                        st.session_state.capital_api.close_position_by_epic(epic)
                    chiuse += 1
                    
            # Puliamo la memoria locale
            if 'open_positions' in st.session_state:
                st.session_state.open_positions.clear()
                
            st.toast(f"Kill Switch Completato! {chiuse} posizioni chiuse forzatamente.", icon="✅")
        else:
            st.toast("Tutte le posizioni chiuse (Offline/Simulazione)", icon="✅")
        
        # Invio Allarme su Telegram
        notifier = TelegramNotifier()
        notifier.send_kill_switch_alert()
