FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY matcher.py server.py ./


ENV PORT=8000 \
    MCP_HTTP_PATH=/mcp \
    MCP_TRANSPORT=streamable-http \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["python", "server.py"]
