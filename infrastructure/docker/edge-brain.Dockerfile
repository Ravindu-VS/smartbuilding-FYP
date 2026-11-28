# Edge brain (Flask API + digital twin + AI control) with the dashboard built in.
# On the Raspberry Pi the edge brain runs natively under systemd (BLE needs BlueZ D-Bus and GPIO); this image runs
# it everywhere else: Docker Compose, CI, Kubernetes, the cloud VM. Build context: the repository root.
ARG NODE_IMAGE=node:22-bookworm-slim
ARG PYTHON_IMAGE=python:3.12-slim

FROM ${NODE_IMAGE} AS dashboard
WORKDIR /src
COPY dashboard/fyp-research-twin/package.json dashboard/fyp-research-twin/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/fyp-research-twin/ ./
ENV NEXT_OUTPUT=export NEXT_PUBLIC_EDGE_URL=same-origin NEXT_TELEMETRY_DISABLED=1
RUN npx next build && test -f out/index.html

FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements/edge.txt requirements/edge.txt
RUN pip install -r requirements/edge.txt
COPY raspberry_pi/ raspberry_pi/
COPY twin/ twin/
COPY ml/ ml/
COPY rl/ rl/
COPY sbops/ sbops/
COPY models/ models/
COPY data/ data/
COPY experiments/configs/ experiments/configs/
COPY scripts/__init__.py scripts/__init__.py
COPY scripts/backup/ scripts/backup/
COPY --from=dashboard /src/out/ dashboard_dist/
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app \
 && mkdir -p /app/output && chown -R app:app /app/output /app/models
USER app
ENV API_HOST=0.0.0.0 API_PORT=8001 EDGE_DB=/app/output/edge_store.sqlite3 LOG_FORMAT=json \
    DASHBOARD_DIR=/app/dashboard_dist
EXPOSE 8001
VOLUME ["/app/output"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=4 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=4).status == 200 else 1)"
CMD ["python", "raspberry_pi/edge_brain.py"]
