FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fetch_playlists.py ./
COPY servidor ./servidor
COPY docs ./docs
ENV ALBUNS_DB=/data/albuns.db
CMD ["sh", "-c", "mkdir -p /data && uvicorn servidor.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
