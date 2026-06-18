FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Esegue il demone scraper storico
CMD ["python", "services/dashboard_engine/historical_data_scraper.py"]
