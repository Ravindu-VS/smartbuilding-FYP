# MLflow tracking server + model registry, backed by PostgreSQL, artifacts served through the server.
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install mlflow==3.18.0 "psycopg[binary]==3.2.13" "prometheus-flask-exporter==0.23.2"
RUN useradd --system --uid 10001 --create-home --home-dir /home/mlflow --shell /usr/sbin/nologin mlflow \
 && mkdir -p /mlartifacts && chown mlflow /mlartifacts
USER mlflow
WORKDIR /home/mlflow
# MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false: no background workers for MLflow GenAI jobs (unused here, ~1.6 GB of processes)
ENV MLFLOW_DISABLE_TELEMETRY=true DO_NOT_TRACK=1 MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false
EXPOSE 5000
VOLUME ["/mlartifacts"]
HEALTHCHECK --interval=10s --timeout=4s --start-period=40s --retries=8 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3).status == 200 else 1)"
# MLFLOW_BACKEND_STORE_URI comes from the environment (contains the DB password, never baked in)
CMD ["sh", "-c", "exec mlflow server --host 0.0.0.0 --port 5000 --backend-store-uri \"$MLFLOW_BACKEND_STORE_URI\" --artifacts-destination /mlartifacts --serve-artifacts --expose-prometheus /tmp/mlflow-metrics --allowed-hosts \"${MLFLOW_ALLOWED_HOSTS:-*}\" --workers \"${MLFLOW_WORKERS:-1}\""]
