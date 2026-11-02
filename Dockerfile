FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AAC_MCP_CONTENT=/app/content-published \
    AAC_MCP_PORT=8321

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.txt

COPY aac_mcp ./aac_mcp
COPY content-published ./content-published

RUN mkdir -p /var/log/mcp && chown -R appuser:appuser /app /var/log/mcp

USER appuser
EXPOSE 8321

CMD ["python", "-c", "import uvicorn; from aac_mcp.server import create_app; uvicorn.run(create_app(), host='0.0.0.0', port=8321, log_level='info')"]

