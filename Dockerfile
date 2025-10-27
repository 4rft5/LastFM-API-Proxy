FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y nginx-full openssl supervisor && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask gunicorn requests

RUN rm -f /etc/nginx/sites-enabled/default && \
    rm -f /etc/nginx/sites-available/default

COPY app.py .
COPY nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

RUN mkdir -p /data /app/certs /var/log/supervisor /var/log/nginx

EXPOSE 80 443 8080

ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/scrobbles.db

ENTRYPOINT ["/entrypoint.sh"]