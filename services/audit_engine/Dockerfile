FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usiamo 1 solo worker per non mandare in crash la coda pubsub
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
