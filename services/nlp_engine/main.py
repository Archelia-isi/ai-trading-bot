from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import pipeline
import torch
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="FinBERT NLP Microservice")

nlp_pipeline = None

class TextRequest(BaseModel):
    text: str

@app.on_event("startup")
def load_model():
    global nlp_pipeline
    logger.info("Avvio caricamento FinBERT in RAM...")
    try:
        device = 0 if torch.cuda.is_available() else -1
        nlp_pipeline = pipeline("sentiment-analysis", model="ProsusAI/finbert", device=device)
        logger.info("FinBERT caricato con successo e pronto.")
    except Exception as e:
        logger.error(f"Errore caricamento modello: {e}")

@app.post("/analyze")
def analyze_sentiment(request: TextRequest):
    if not nlp_pipeline:
        raise HTTPException(status_code=503, detail="Model is still loading or failed to load")
    
    try:
        results = nlp_pipeline(request.text)
        if len(results) > 0:
            result = results[0]
            label = result['label'].upper()
            score = float(result['score'])
            return {"label": label, "score": score}
        return {"label": "NEUTRAL", "score": 0.5}
    except Exception as e:
        logger.error(f"Errore inferenza: {e}")
        raise HTTPException(status_code=500, detail=str(e))
