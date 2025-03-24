FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y libnss3 libatk1.0-0 libgbm1 && playwright install chromium
COPY src/ ./src/
ENV PORT=8080
CMD ["python", "src/main.py"]FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y libnss3 libatk1.0-0 libgbm1 && playwright install chromium
COPY src/ ./src/
ENV PORT=8080
CMD ["python", "src/main.py"]