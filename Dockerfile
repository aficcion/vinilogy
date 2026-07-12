FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# psycopg2-binary trae wheels → no hacen falta libpq/gcc. Solo requirements primero
# para aprovechar la cache de capas.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway inyecta PORT. 1 worker: el estado del flow OAuth vive en memoria
# (FlowStore) → con varios workers los logins fallarían al azar. --proxy-headers para
# obtener la IP real tras el proxy (rate limiting, logs). Sin --reload en prod.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --workers 1"]
