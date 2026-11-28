# Training job: data validation -> training -> MLflow tracking/registry -> promotion gate. Runs and exits.
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements/trainer.txt requirements/trainer.txt
RUN pip install -r requirements/trainer.txt
COPY ml/__init__.py ml/common.py ml/drift.py ml/
COPY mlops/ mlops/
COPY sbops/ sbops/
COPY data/raw/kaggle_occupancy/ data/raw/kaggle_occupancy/
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app
USER app
ENV LOG_FORMAT=json MLFLOW_DISABLE_TELEMETRY=true DO_NOT_TRACK=1 HOME=/tmp
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}
CMD ["python", "-m", "mlops.train", "--if-no-production"]
