# Multi-stage build (Module 18): the build stage has the tools to make a wheel;
# the runtime stage has only Python, the wheel and the data. Smaller, and nothing
# in the running image can compile or fetch code.

FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY agent ./agent
COPY evals ./evals
COPY scripts ./scripts
COPY strategy ./strategy
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /wheels

FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir "$(ls /wheels/*.whl)[prod]" && rm -rf /wheels
COPY data/kb ./data/kb
COPY web ./web
ENV RETAILCO_ROOT=/app \
    RETAILCO_DB=/app/state/retailco.db \
    RETAILCO_TRACES=/app/state/traces.jsonl \
    PYTHONUNBUFFERED=1
RUN mkdir -p /app/state && chown app /app/state
USER app
EXPOSE 8000
# Liveness for Docker; orchestrators should also call /readyz before sending traffic.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=2)"
# migrate never deletes data, so approvals waiting at shutdown are still there after a restart.
CMD ["sh", "-c", "python -m scripts.migrate && exec uvicorn agent.api:app --host 0.0.0.0 --port 8000"]
