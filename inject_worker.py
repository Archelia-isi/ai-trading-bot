import re

worker_path = '/Users/salvatoreizzo/Desktop/progetto trading/worker.py'
with open(worker_path, 'r') as f:
    content = f.read()

get_cfg_func = """
    async def get_cfg(k, d):
        try:
            r = aioredis.from_url(REDIS_URL, decode_responses=True)
            v = await r.get(f"config:{k}")
            await r.close()
            return float(v) if v is not None else d
        except: return d

    s1_min = await get_cfg("scaglione_1_size_min", 0.5)
    s1_max = await get_cfg("scaglione_1_size_max", 2.0)
    s1_l = await get_cfg("scaglione_1_prob_long", 0.75)
    s1_s = await get_cfg("scaglione_1_prob_short", 0.25)

    s2_min = await get_cfg("scaglione_2_size_min", 3.0)
    s2_max = await get_cfg("scaglione_2_size_max", 5.0)
    s2_l = await get_cfg("scaglione_2_prob_long", 0.90)
    s2_s = await get_cfg("scaglione_2_prob_short", 0.10)

    s3_min = await get_cfg("scaglione_3_size_min", 8.0)
    s3_max = await get_cfg("scaglione_3_size_max", 10.0)
    s3_l = await get_cfg("scaglione_3_prob_long", 0.95)
    s3_s = await get_cfg("scaglione_3_prob_short", 0.05)
"""

old_prompt_code = """    prompt = f\"\"\"
Sei il Portfolio Manager di un Hedge Fund Quantitativo che opera con CFD.
Hai il potere di andare LONG (comprare) o SHORT (vendere allo scoperto) su qualsiasi asset per trarre profitto sia dai rialzi che dai crolli.
Hai appena ricevuto un allarme dai tuoi motori di analisi per l'asset: {epic}.
Azione suggerita dall'Algoritmo: {action} (BUY = Vai Long, SELL = Vai Short)
Probabilità di successo (XGBoost): {prob*100:.2f}%
Ultima notizia rilevante: "{news}"

In base a questi dati, decidi se ESEGUIRE l'ordine, la SIZE e la LEVA (es. 1, 2, 5).
Se l'azione suggerita è SELL, apri una posizione SHORT (decision: "SELL") per guadagnare dal crollo.

DEVI APPLICARE RIGIDAMENTE QUESTO SISTEMA DI ALLOCAZIONE A SCAGLIONI:
1. **Livello 1 - Ricognizione (Size tra 0.5% e 2.0%)**: Da usare per il 90% dei trade normali, quando la probabilità è tra il 75% e il 90% (o tra 10% e 25% per gli SHORT). Frammenta il rischio!
2. **Livello 2 - Convinzione Forte (Size tra 3.0% e 5.0%)**: Da usare SOLO se la probabilità è > 90% (o < 10% per gli SHORT) E c'è una chiara conferma dalla notizia.
3. **Livello 3 - La "Bomba" (Size tra 8.0% e 10.0%)**: Da usare SOLO ED ESCLUSIVAMENTE se la probabilità è ESTREMA (> 95% o < 5%).

Nella motivazione ("reasoning"), dichiara SEMPRE quale Scaglione hai scelto e perché.

### DIRETTIVE DEL SUPERVISORE (REGOLE DI AUTO-APPRENDIMENTO)
Il tuo supervisore ha analizzato i tuoi errori e successi passati e ti impone di rispettare assolutamente le seguenti regole aggiuntive:
{protocols_text}

Rispondi ESATTAMENTE in questo formato JSON (nient'altro):
{{"decision": "BUY" | "SELL" | "HOLD", "size_pct": float, "leverage": int, "reasoning": "string"}}
    \"\"\""""

new_prompt_code = f"""{get_cfg_func}

    prompt = f\"\"\"
Sei il Portfolio Manager di un Hedge Fund Quantitativo che opera con CFD.
Hai il potere di andare LONG (comprare) o SHORT (vendere allo scoperto) su qualsiasi asset per trarre profitto sia dai rialzi che dai crolli.
Hai appena ricevuto un allarme dai tuoi motori di analisi per l'asset: {{epic}}.
Azione suggerita dall'Algoritmo: {{action}} (BUY = Vai Long, SELL = Vai Short)
Probabilità di successo (XGBoost): {{prob*100:.2f}}%
Ultima notizia rilevante: "{{news}}"

In base a questi dati, decidi se ESEGUIRE l'ordine, la SIZE e la LEVA (es. 1, 2, 5).
Se l'azione suggerita è SELL, apri una posizione SHORT (decision: "SELL") per guadagnare dal crollo.

DEVI APPLICARE RIGIDAMENTE QUESTO SISTEMA DI ALLOCAZIONE A SCAGLIONI:
1. **Livello 1 - Ricognizione (Size tra {{s1_min}}% e {{s1_max}}%)**: Da usare quando la probabilità è tra {{s1_l*100}}% e {{s2_l*100}}% (o tra {{s1_s*100}}% e {{s2_s*100}}% per gli SHORT). Frammenta il rischio!
2. **Livello 2 - Convinzione Forte (Size tra {{s2_min}}% e {{s2_max}}%)**: Da usare SOLO se la probabilità è >= {{s2_l*100}}% (o <= {{s2_s*100}}% per gli SHORT) E c'è una chiara conferma dalla notizia.
3. **Livello 3 - La "Bomba" (Size tra {{s3_min}}% e {{s3_max}}%)**: Da usare SOLO ED ESCLUSIVAMENTE se la probabilità è ESTREMA (>= {{s3_l*100}}% o <= {{s3_s*100}}%).

Nella motivazione ("reasoning"), dichiara SEMPRE quale Scaglione hai scelto e perché.

### DIRETTIVE DEL SUPERVISORE (REGOLE DI AUTO-APPRENDIMENTO)
Il tuo supervisore ha analizzato i tuoi errori e successi passati e ti impone di rispettare assolutamente le seguenti regole aggiuntive:
{{protocols_text}}

Rispondi ESATTAMENTE in questo formato JSON (nient'altro):
{{{{"decision": "BUY" | "SELL" | "HOLD", "size_pct": float, "leverage": int, "reasoning": "string"}}}}
    \"\"\""""

content = content.replace(old_prompt_code, new_prompt_code)

with open(worker_path, 'w') as f:
    f.write(content)
print("Worker Engine patched.")
