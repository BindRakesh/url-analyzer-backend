FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libxss1 \
    && rm -rf /var/lib/apt/lists/*
RUN playwright install chromium

COPY src/ ./src/

ENV PORT=8080
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]