# Model-serving API: loads the production model from the MLflow registry (FastAPI + uvicorn).
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements/serving.txt requirements/serving.txt
RUN pip install -r requirements/serving.txt
COPY ml/__init__.py ml/common.py ml/drift.py ml/
COPY mlops/__init__.py mlops/data.py mlops/
COPY mlops/serving/ mlops/serving/
COPY sbops/ sbops/
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app && mkdir -p /tmp/mlflow && chown app /tmp/mlflow
USER app
ENV MODEL_NAME=room-occupancy MODEL_ALIAS=production MODEL_POLL_SECONDS=60 LOG_FORMAT=json \
    MLFLOW_DISABLE_TELEMETRY=true DO_NOT_TRACK=1 HOME=/tmp
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=4s --start-period=30s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health/ready', timeout=3).status == 200 else 1)"
CMD ["uvicorn", "mlops.serving.app:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
