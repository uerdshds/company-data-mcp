"""
公司名对碰 MCP Server (StreamableHTTP) —— 供钉钉 DEAP 自定义技能接入。

DEAP 要求: 传输类型 SSE / StreamableHTTP (不支持 Stdio)。本服务用 StreamableHTTP,
服务路径默认 /message (与 ngrok 暴露的 URL 对齐)。

运行:
    .venv/Scripts/python.exe server.py
    # 默认监听 0.0.0.0:8000, MCP 端点 = http://localhost:8000/message
    # 再用 ngrok 暴露:  ngrok http 8000
    # DEAP 里填:  https://<your>.ngrok-free.dev/message

可选鉴权:
    设置环境变量 MCP_API_KEY=xxx 后, 请求需带 Header  X-Api-Key: xxx
    (在 DEAP 自定义技能的"请求头"里加同名 Header)。
"""
from __future__ import annotations

import os
import tempfile
from typing import Annotated, Any, Optional
from urllib.parse import urlparse

import requests
from pydantic import Field

from mcp.server.fastmcp import FastMCP

from matcher import load_table, reconcile

PORT = int(os.environ.get("PORT", "8000"))

HTTP_PATH = os.environ.get("MCP_HTTP_PATH", "/mcp")

TRANSPORT = os.environ.get("MCP_TRANSPORT", "streamable-http")
API_KEY = os.environ.get("MCP_API_KEY")  

mcp = FastMCP(
    "company-reconcile",
    host="0.0.0.0",
    port=PORT,
    streamable_http_path=HTTP_PATH,
)


# 文件获取: 支持 http(s) URL (钉盘下载链接) 或本地路径
def _fetch(file_ref: str) -> tuple[bytes, str]:
    """返回 (文件字节, 文件名)。URL 则下载, 否则按本地路径读。"""
    if file_ref.lower().startswith(("http://", "https://")):
        resp = requests.get(file_ref, timeout=60)
        resp.raise_for_status()
        name = os.path.basename(urlparse(file_ref).path) or "download"
        # 没有扩展名时尝试从 Content-Disposition 取
        if "." not in name:
            cd = resp.headers.get("Content-Disposition", "")
            if "filename=" in cd:
                name = cd.split("filename=")[-1].strip('"; ')
        return resp.content, name
    with open(file_ref, "rb") as f:
        return f.read(), os.path.basename(file_ref)


# 工具: 公司名 + 日期 对碰

@mcp.tool(
    title="公司名对碰",
    annotations={"readOnlyHint": True, "openWorldHint": True},
)
def reconcile_company_tables(
    file_a: Annotated[str, Field(description="表A: 可下载的文件URL(钉盘链接)或本地路径, 支持 .xlsx/.csv/.pdf")],
    file_b: Annotated[str, Field(description="表B: 可下载的文件URL(钉盘链接)或本地路径, 支持 .xlsx/.csv/.pdf")],
    name_threshold: Annotated[int, Field(ge=0, le=100, description="公司名相似度阈值(0-100), 默认85, 越高越严格")] = 85,
    date_tolerance_days: Annotated[int, Field(ge=0, le=30, description="日期容差天数, 0=必须同一天(AND严格), 默认0")] = 0,
    name_col_a: Annotated[Optional[str], Field(description="表A名称列名, 留空自动识别")] = None,
    date_col_a: Annotated[Optional[str], Field(description="表A日期列名, 留空自动识别")] = None,
    name_col_b: Annotated[Optional[str], Field(description="表B名称列名, 留空自动识别")] = None,
    date_col_b: Annotated[Optional[str], Field(description="表B日期列名, 留空自动识别")] = None,
    strip_suffix: Annotated[bool, Field(description="比对时是否剥离'有限公司'等组织形式后缀, 默认False")] = False,
) -> dict[str, Any]:
    """
    把两份表格按【公司名称 + 日期】做模糊对碰 (AND逻辑: 名称与日期都满足才算匹配)。

    返回三档结果:
      - matched   : 名称相似度>=阈值 且 日期在容差内
      - to_review : 日期满足但名称相似度落在复核区间(阈值下10分内), 需人工确认
      - unmatched : 无日期匹配候选, 或名称相似度过低
    每条含 name_score(名称分) 与 day_gap(日期相差天数), 另附 summary 汇总。
    """
    bytes_a, name_a = _fetch(file_a)
    bytes_b, name_b = _fetch(file_b)

    table_a = load_table(bytes_a, name_a, name_col_a, date_col_a)
    table_b = load_table(bytes_b, name_b, name_col_b, date_col_b)

    res = reconcile(
        table_a, table_b,
        name_threshold=name_threshold,
        date_tolerance_days=date_tolerance_days,
        strip_suffix=strip_suffix,
    )
    return {
        "summary": res.summary,
        "matched": res.matched,
        "to_review": res.to_review,
        "unmatched": res.unmatched,
    }



# 启动: 带可选的 X-Api-Key 鉴权中间件

def main() -> None:
    # stdio: 供魔搭 FC 运行时包装 (无网络端口)
    if TRANSPORT == "stdio":
        print("[company-reconcile] stdio transport")
        mcp.run(transport="stdio")
        return

    # streamable-http: DEAP / 魔搭直连
    if API_KEY:
        import uvicorn
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse

        app = mcp.streamable_http_app()

        async def auth(request, call_next):
            if request.headers.get("X-Api-Key") != API_KEY:
                return JSONResponse({"error": "invalid X-Api-Key"}, status_code=401)
            return await call_next(request)

        app.add_middleware(BaseHTTPMiddleware, dispatch=auth)
        print(f"[company-reconcile] StreamableHTTP (+鉴权) on 0.0.0.0:{PORT}{HTTP_PATH}")
        uvicorn.run(app, host="0.0.0.0", port=PORT)
    else:
        print(f"[company-reconcile] StreamableHTTP on 0.0.0.0:{PORT}{HTTP_PATH} (无鉴权)")
        mcp.run(transport="streamable-http")


def main_stdio() -> None:
    """魔搭(ModelScope) 托管入口: 强制 stdio, 由平台 FC 运行时包装成 /mcp HTTP。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
