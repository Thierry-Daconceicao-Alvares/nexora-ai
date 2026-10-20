# One image for the API and the interface (different commands in compose).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE alembic.ini ./
COPY src ./src
RUN pip install ".[ui]"

COPY config ./config
COPY data ./data
COPY app ./app
COPY .streamlit ./.streamlit
COPY scripts ./scripts

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 nexora && chown -R nexora /app
USER nexora

ENV NEXORA_RULES_PATH=/app/config/rules.yaml \
    NEXORA_USERS_PATH=/app/config/demo_users.yaml \
    NEXORA_SYNTHETIC_DIR=/app/data/synthetic \
    NEXORA_KNOWLEDGE_BASE_DIR=/app/data/knowledge_base

EXPOSE 8000 8501
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "nexora.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
