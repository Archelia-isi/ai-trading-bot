FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the model during build so it's baked into the image
RUN python -c "from transformers import pipeline; pipeline('sentiment-analysis', model='ProsusAI/finbert')"

COPY . .

# Railway automatically passes PORT environment variable
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
