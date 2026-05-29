import re

html_path = '/Users/salvatoreizzo/Desktop/progetto trading/services/dashboard_engine/templates/index.html'

with open(html_path, 'r') as f:
    content = f.read()

css_to_add = """
        /* Settings Buttons & Modals */
        .settings-btn {
            background: rgba(69, 162, 158, 0.1);
            border: 1px solid var(--border-color);
            color: var(--text-highlight);
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-family: 'Inter', sans-serif;
            font-weight: 600;
            transition: all 0.3s ease;
        }
        .settings-btn:hover {
            background: rgba(69, 162, 158, 0.3);
            box-shadow: 0 0 10px rgba(69, 162, 158, 0.5);
        }
        
        .modal-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.7);
            backdrop-filter: blur(5px);
            z-index: 1000;
        }
        
        .modal {
            display: none;
            position: fixed;
            top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            background: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 15px;
            padding: 25px;
            z-index: 1001;
            width: 90%;
            max-width: 500px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.8);
            color: #fff;
        }
        
        .modal-header {
            font-size: 1.3rem;
            font-weight: bold;
            margin-bottom: 20px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            padding-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .close-btn {
            cursor: pointer;
            font-size: 1.5rem;
            color: #ff5252;
        }
        
        .setting-row {
            margin-bottom: 15px;
            display: flex;
            flex-direction: column;
        }
        
        .setting-label {
            font-size: 0.9rem;
            margin-bottom: 5px;
            display: flex;
            justify-content: space-between;
        }
        
        .info-btn {
            cursor: pointer;
            background: none;
            border: none;
            color: var(--text-highlight);
            font-size: 1rem;
            padding: 0;
            margin-left: 5px;
        }
        
        .setting-input {
            background: rgba(0,0,0,0.5);
            border: 1px solid rgba(255,255,255,0.2);
            color: #fff;
            padding: 8px;
            border-radius: 5px;
            font-family: 'Inter', sans-serif;
            width: 100%;
            box-sizing: border-box;
        }
        
        .save-btn {
            width: 100%;
            background: var(--pos-color);
            color: white;
            border: none;
            padding: 12px;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: bold;
            cursor: pointer;
            margin-top: 15px;
        }
        .save-btn:hover { background: #388E3C; }
        
        /* Info Pop-up */
        .info-popup {
            display: none;
            position: absolute;
            background: #fff;
            color: #000;
            padding: 10px;
            border-radius: 5px;
            font-size: 0.8rem;
            width: 250px;
            z-index: 1002;
            box-shadow: 0 5px 15px rgba(0,0,0,0.5);
            pointer-events: none;
        }
"""

html_to_add = """
    <!-- Pannello di Controllo Parametri -->
    <div class="portfolio-panel" style="margin-top: 30px;">
        <div class="panel-header"><span class="panel-icon">⚙️</span> Pannello di Controllo Parametri</div>
        <div style="display: flex; gap: 15px; flex-wrap: wrap;">
            <button class="settings-btn" onclick="openModal('modal-scaglione-1')">⚙️ Scaglione 1 (Ricognizione)</button>
            <button class="settings-btn" onclick="openModal('modal-scaglione-2')">⚙️ Scaglione 2 (Convinzione Forte)</button>
            <button class="settings-btn" onclick="openModal('modal-scaglione-3')">⚙️ Scaglione 3 (Azione Estrema)</button>
            <button class="settings-btn" onclick="openModal('modal-rischio')">🛡️ Gestione Rischio Globale</button>
            <button class="settings-btn" onclick="openModal('modal-motori')">🏹 Motori Matematici</button>
        </div>
    </div>
    
    <div id="settings-overlay" class="modal-overlay" onclick="closeAllModals()"></div>
    <div id="info-popup" class="info-popup"></div>

    <!-- Modal Scaglione 1 -->
    <div id="modal-scaglione-1" class="modal">
        <div class="modal-header"><span>⚙️ Scaglione 1</span> <span class="close-btn" onclick="closeAllModals()">&times;</span></div>
        
        <div class="setting-row">
            <div class="setting-label">Dimensione Capitale Minima (%) <button class="info-btn" onmouseover="showInfo(event, 'Percentuale minima del portafoglio da investire in operazioni a rischio moderato.')" onmouseout="hideInfo()">ℹ️</button></div>
            <input type="number" step="0.1" id="scaglione_1_size_min" class="setting-input">
        </div>
        <div class="setting-row">
            <div class="setting-label">Dimensione Capitale Massima (%) <button class="info-btn" onmouseover="showInfo(event, 'Percentuale massima del portafoglio consentita per questo livello di rischio.')" onmouseout="hideInfo()">ℹ️</button></div>
            <input type="number" step="0.1" id="scaglione_1_size_max" class="setting-input">
        </div>
        <div class="setting-row">
            <div class="setting-label">Sicurezza Minima Acquisto (LONG) <button class="info-btn" onmouseover="showInfo(event, 'Probabilità matematica (es. 0.75 = 75%) richiesta all\\'Intelligenza Artificiale per autorizzare un investimento rialzista a questo livello.')" onmouseout="hideInfo()">ℹ️</button></div>
            <input type="number" step="0.01" id="scaglione_1_prob_long" class="setting-input">
        </div>
        <div class="setting-row">
            <div class="setting-label">Sicurezza Minima Vendita (SHORT) <button class="info-btn" onmouseover="showInfo(event, 'Probabilità matematica (es. 0.25 = 25%) richiesta all\\'Intelligenza Artificiale per autorizzare un investimento ribassista a questo livello.')" onmouseout="hideInfo()">ℹ️</button></div>
            <input type="number" step="0.01" id="scaglione_1_prob_short" class="setting-input">
        </div>
        <button class="save-btn" onclick="saveSettings(['scaglione_1_size_min', 'scaglione_1_size_max', 'scaglione_1_prob_long', 'scaglione_1_prob_short'])">Salva Modifiche</button>
    </div>

    <!-- Modal Scaglione 2 -->
    <div id="modal-scaglione-2" class="modal">
        <div class="modal-header"><span>⚙️ Scaglione 2</span> <span class="close-btn" onclick="closeAllModals()">&times;</span></div>
        <div class="setting-row"><div class="setting-label">Dimensione Capitale Minima (%) <button class="info-btn" onmouseover="showInfo(event, 'Percentuale minima per investimenti ad alta convinzione.')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.1" id="scaglione_2_size_min" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Dimensione Capitale Massima (%) <button class="info-btn" onmouseover="showInfo(event, 'Percentuale massima per investimenti ad alta convinzione.')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.1" id="scaglione_2_size_max" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Sicurezza Minima Acquisto (LONG) <button class="info-btn" onmouseover="showInfo(event, 'Probabilità matematica richiesta (es. 0.90) per un ingresso pesante a rialzo.')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.01" id="scaglione_2_prob_long" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Sicurezza Minima Vendita (SHORT) <button class="info-btn" onmouseover="showInfo(event, 'Probabilità matematica richiesta (es. 0.10) per un ingresso pesante a ribasso.')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.01" id="scaglione_2_prob_short" class="setting-input"></div>
        <button class="save-btn" onclick="saveSettings(['scaglione_2_size_min', 'scaglione_2_size_max', 'scaglione_2_prob_long', 'scaglione_2_prob_short'])">Salva Modifiche</button>
    </div>

    <!-- Modal Scaglione 3 -->
    <div id="modal-scaglione-3" class="modal">
        <div class="modal-header"><span>⚙️ Scaglione 3</span> <span class="close-btn" onclick="closeAllModals()">&times;</span></div>
        <div class="setting-row"><div class="setting-label">Dimensione Capitale Minima (%) <button class="info-btn" onmouseover="showInfo(event, 'Percentuale minima per occasioni estreme e irripetibili.')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.1" id="scaglione_3_size_min" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Dimensione Capitale Massima (%) <button class="info-btn" onmouseover="showInfo(event, 'Tetto massimo invalicabile di investimento per una singola operazione.')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.1" id="scaglione_3_size_max" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Sicurezza Estrema Acquisto (LONG) <button class="info-btn" onmouseover="showInfo(event, 'Probabilità quasi assoluta richiesta (es. 0.95) per operazioni estreme a rialzo.')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.01" id="scaglione_3_prob_long" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Sicurezza Estrema Vendita (SHORT) <button class="info-btn" onmouseover="showInfo(event, 'Probabilità quasi assoluta richiesta (es. 0.05) per operazioni estreme a ribasso.')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.01" id="scaglione_3_prob_short" class="setting-input"></div>
        <button class="save-btn" onclick="saveSettings(['scaglione_3_size_min', 'scaglione_3_size_max', 'scaglione_3_prob_long', 'scaglione_3_prob_short'])">Salva Modifiche</button>
    </div>

    <!-- Modal Rischio -->
    <div id="modal-rischio" class="modal">
        <div class="modal-header"><span>🛡️ Gestione Rischio Globale</span> <span class="close-btn" onclick="closeAllModals()">&times;</span></div>
        <div class="setting-row"><div class="setting-label">Esposizione Massima Globale (%) <button class="info-btn" onmouseover="showInfo(event, 'Blocca l\\'apertura di nuove operazioni se il portafoglio è già esposto sul mercato per questa percentuale (es. 50.0).')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.1" id="max_exposure" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Leva Finanziaria Massima Consentita <button class="info-btn" onmouseover="showInfo(event, 'Il Guardiano taglierà automaticamente ogni richiesta di leva superiore a questo valore (es. 5).')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="1" id="max_leverage" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Perdita Massima Tollerata (%) <button class="info-btn" onmouseover="showInfo(event, 'Soglia critica negativa (es. -3.0). Se il portafoglio totale scende a questo valore, il bot chiude tutte le posizioni e si blocca per la giornata.')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.1" id="max_drawdown" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Obiettivo di Profitto Giornaliero (%) <button class="info-btn" onmouseover="showInfo(event, 'Soglia di successo (es. 1.0). Se il portafoglio raggiunge questo profitto, il bot incassa i guadagni e conclude la giornata lavorativa.')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.1" id="daily_take_profit" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Soglia Modalità di Recupero Emergenza <button class="info-btn" onmouseover="showInfo(event, 'In caso di blocco per perdite, il bot può ignorare il divieto se scova una nuova occasione con probabilità superiore a questo valore (es. 0.90).')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.01" id="recovery_mode_prob" class="setting-input"></div>
        <button class="save-btn" onclick="saveSettings(['max_exposure', 'max_leverage', 'max_drawdown', 'daily_take_profit', 'recovery_mode_prob'])">Salva Modifiche</button>
    </div>

    <!-- Modal Motori -->
    <div id="modal-motori" class="modal">
        <div class="modal-header"><span>🏹 Motori Matematici</span> <span class="close-btn" onclick="closeAllModals()">&times;</span></div>
        <div class="setting-row"><div class="setting-label">Soglia Intervento Cacciatore (Acquisto) <button class="info-btn" onmouseover="showInfo(event, 'Scansiona l\\'intero mercato: spara segnali tecnici se la probabilità LONG supera questa soglia (es. 0.65).')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.01" id="hunter_long" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Soglia Intervento Cacciatore (Vendita) <button class="info-btn" onmouseover="showInfo(event, 'Scansiona l\\'intero mercato: spara segnali tecnici se la probabilità SHORT scende sotto questa soglia (es. 0.35).')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.01" id="hunter_short" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Soglia Conferma Segugio (Acquisto) <button class="info-btn" onmouseover="showInfo(event, 'Convalida notizie finanziarie positive se l\\'analisi tecnica successiva supera questa soglia LONG (es. 0.60).')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.01" id="segugio_long" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Soglia Conferma Segugio (Vendita) <button class="info-btn" onmouseover="showInfo(event, 'Convalida notizie finanziarie negative se l\\'analisi tecnica successiva scende sotto questa soglia SHORT (es. 0.40).')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.01" id="segugio_short" class="setting-input"></div>
        <div class="setting-row"><div class="setting-label">Rigidità Modello Predittivo (Lambda) <button class="info-btn" onmouseover="showInfo(event, 'Controllo di regolarizzazione di XGBoost (es. 10.0). Valori più alti rendono l\\'AI più conservativa e prudente, valori bassi la rendono aggressiva.')" onmouseout="hideInfo()">ℹ️</button></div><input type="number" step="0.1" id="xgboost_lambda" class="setting-input"></div>
        <button class="save-btn" onclick="saveSettings(['hunter_long', 'hunter_short', 'segugio_long', 'segugio_short', 'xgboost_lambda'])">Salva Modifiche</button>
    </div>
"""

js_to_add = """
        // Settings Management
        async function fetchSettings() {
            try {
                const res = await fetch('/api/settings');
                const data = await res.json();
                if (data.status === 'success') {
                    for (const [key, val] of Object.entries(data.settings)) {
                        const el = document.getElementById(key);
                        if (el) el.value = val;
                    }
                }
            } catch (e) { console.error('Errore caricamento impostazioni:', e); }
        }
        
        async function saveSettings(keys) {
            for (const key of keys) {
                const el = document.getElementById(key);
                if (el) {
                    try {
                        await fetch('/api/settings', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({ key: key, value: el.value })
                        });
                    } catch (e) { console.error('Errore salvataggio:', e); }
                }
            }
            alert('Modifiche salvate con successo!');
            closeAllModals();
        }

        function openModal(id) {
            document.getElementById('settings-overlay').style.display = 'block';
            document.getElementById(id).style.display = 'block';
        }
        
        function closeAllModals() {
            document.getElementById('settings-overlay').style.display = 'none';
            document.querySelectorAll('.modal').forEach(m => m.style.display = 'none');
        }
        
        function showInfo(e, text) {
            const popup = document.getElementById('info-popup');
            popup.textContent = text;
            popup.style.display = 'block';
            popup.style.left = (e.pageX + 10) + 'px';
            popup.style.top = (e.pageY + 10) + 'px';
        }
        
        function hideInfo() {
            document.getElementById('info-popup').style.display = 'none';
        }
        
        // Fetch on load
        fetchSettings();
"""

content = content.replace("        @keyframes slideIn {", css_to_add + "\n        @keyframes slideIn {")
content = content.replace("    <script src=\"https://cdnjs.cloudflare.com/ajax/libs/odometer.js/0.4.8/odometer.min.js\"></script>", html_to_add + "\n    <script src=\"https://cdnjs.cloudflare.com/ajax/libs/odometer.js/0.4.8/odometer.min.js\"></script>")
content = content.replace("        // Avvia connessione", js_to_add + "\n        // Avvia connessione")

with open(html_path, 'w') as f:
    f.write(content)
print("Injection successful.")
