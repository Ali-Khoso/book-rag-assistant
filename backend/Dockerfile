FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN groupadd --gid 10001 bookwise && useradd --uid 10001 --gid bookwise --no-create-home bookwise
COPY requirements.lock ./requirements.lock
RUN pip install --require-hashes -r requirements.lock
COPY --chown=bookwise:bookwise app ./app
RUN mkdir -p /app/.cache/models && chown -R bookwise:bookwise /app/.cache
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=8)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
