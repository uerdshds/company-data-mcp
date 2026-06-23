"""以 stdio 方式启动打包后的服务并调用 —— 模拟魔搭托管的运行方式。"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))


async def main():
    # 等价于魔搭里的 "command + args" (这里直接用本包的 console 入口)
    params = StdioServerParameters(
        command=os.path.join(HERE, ".venv", "Scripts", "company-reconcile-mcp.exe"),
        args=[],
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("=== 工具列表 ===")
            for t in tools.tools:
                print(f"- {t.name}")

            result = await session.call_tool("reconcile_company_tables", {
                "file_a": os.path.join(HERE, "samples", "table_a.csv"),
                "file_b": os.path.join(HERE, "samples", "table_b.csv"),
                "date_tolerance_days": 1,
            })
            data = result.structuredContent or json.loads(result.content[0].text)
            print("\n=== 调用结果 ===")
            print(json.dumps(data["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
