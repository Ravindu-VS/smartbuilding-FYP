# Telemetry ingestion: MQTT -> PostgreSQL (+ ML prediction per reading).
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements/ingestion.txt requirements/ingestion.txt
RUN pip install -r requirements/ingestion.txt
COPY raspberry_pi/mqtt_bridge.py raspberry_pi/
COPY ingestion/ ingestion/
COPY sbops/ sbops/
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app
USER app
ENV INGEST_HTTP_PORT=8090 LOG_FORMAT=json
EXPOSE 8090
HEALTHCHECK --interval=10s --timeout=4s --start-period=20s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3).status == 200 else 1)"
CMD ["python", "-m", "ingestion.service"]
