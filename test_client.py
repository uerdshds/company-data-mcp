"""用 MCP 客户端连本地 StreamableHTTP 服务, 列工具并调用一次 (模拟 DEAP)。"""
import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("MCP_URL", "http://localhost:8000/mcp")
HERE = os.path.dirname(os.path.abspath(__file__))


async def main():
    async with streamablehttp_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("=== 工具列表 ===")
            for t in tools.tools:
                print(f"- {t.name}: {t.description.splitlines()[0] if t.description else ''}")

            print("\n=== 调用 reconcile_company_tables (tol=1) ===")
            result = await session.call_tool("reconcile_company_tables", {
                "file_a": os.path.join(HERE, "samples", "table_a.csv"),
                "file_b": os.path.join(HERE, "samples", "table_b.csv"),
                "date_tolerance_days": 1,
            })
            data = result.structuredContent or json.loads(result.content[0].text)
            print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
            print(f"matched={len(data['matched'])} "
                  f"to_review={len(data['to_review'])} "
                  f"unmatched={len(data['unmatched'])}")


if __name__ == "__main__":
    asyncio.run(main())
