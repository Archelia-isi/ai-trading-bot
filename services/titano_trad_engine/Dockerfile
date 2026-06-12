FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
# Installiamo build-essential per XGBoost se necessario
RUN apt-get update && apt-get install -y build-essential libgomp1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usiamo 1 solo worker perché il multiprocessing è gestito internamente (24 vCPU partizionate)
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
