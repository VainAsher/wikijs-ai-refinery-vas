# VainAsherStudios Wiki.js AI Refinery — container image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    REFINERY_DATA=/data

WORKDIR /app

# Dependencies first for layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code (data/ is a mounted volume, never baked into the image).
COPY refinery ./refinery
COPY pipeline_templates ./pipeline_templates
COPY taxonomy.yml refinery_cli.py ./

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000

# Liveness probe used by Docker and Cloudflare. /healthz is always unauthenticated.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "refinery.app:app", "--host", "0.0.0.0", "--port", "8000"]
