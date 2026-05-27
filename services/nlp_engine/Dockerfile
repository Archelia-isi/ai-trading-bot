FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-scarica il modello FinBERT durante il build per evitare timeout
RUN python -c "from transformers import pipeline; pipeline('sentiment-analysis', model='ProsusAI/finbert')"

COPY . .

# Usiamo 4 worker Gunicorn per sfruttare la CPU
CMD uvicorn main:app --host 0.0.0.0 --port $PORT --workers 4
