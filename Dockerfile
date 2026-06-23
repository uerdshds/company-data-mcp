# 魔搭(ModelScope) MCP 托管 / 函数计算 FC 用镜像
FROM python:3.11-slim

WORKDIR /app

# 系统依赖: pdfplumber 解析 PDF 需要的字体/图形库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY matcher.py server.py ./

# 魔搭 FC 通过 PORT 注入端口; 端点路径 /mcp; 默认 streamable-http
ENV PORT=8000 \
    MCP_HTTP_PATH=/mcp \
    MCP_TRANSPORT=streamable-http \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["python", "server.py"]
