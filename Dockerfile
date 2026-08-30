FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/reliefos

RUN groupadd --system reliefos && useradd --system --gid reliefos --home /opt/reliefos reliefos

COPY pyproject.toml README.md LICENSE ./
COPY app ./app
COPY web ./web

RUN python -m pip install --upgrade pip && python -m pip install .

RUN mkdir -p /opt/reliefos/runtime/media && chown -R reliefos:reliefos /opt/reliefos
USER reliefos

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
